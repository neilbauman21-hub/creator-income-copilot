"""core/parser.py — CSV sales parsing with schema auto-detection.

Reads raw CSV text (Payhip orders export, Gumroad sales export, or a
generic date/product/price schema) and normalizes it into SaleRecord
objects. Header matching is case-insensitive, whitespace-normalized and
synonym-based. Invalid rows are reported as warnings, never raised.

Since Pass 2 (EXPANSION.md) this module is the FACADE for the
core/parsers/ package: source_hint may name a dedicated parser
("shopify", "kofi", "lemon"), which is imported lazily so this module
keeps working even if one of those modules is missing. Payhip / Gumroad
/ generic schemas are parsed in place by the synonym engine below.
"""
from __future__ import annotations
import csv
import importlib
import io
import re
from datetime import datetime
from types import ModuleType
from core.models import SaleRecord

# Canonical field -> accepted (normalized) header synonyms, best first.
# Earlier entries win when several headers match the same field.
_SYNONYMS: dict[str, list[str]] = {
    "order_id": [
        "order id", "order number", "sale id", "sale number",
        "transaction id", "transaction number",
    ],
    "date": [
        "order date", "purchase date", "sale date", "created at",
        "datetime", "date", "created", "purchased at", "order placed",
        "sale timestamp", "timestamp", "order time",
    ],
    "product": [
        "product", "product name", "product title", "item", "item name",
        "title", "product permalink",
    ],
    "price": [
        "price", "amount", "total", "revenue", "order total", "sale price",
        "product price", "price cents", "amount cents", "total cents",
        "gross amount", "net amount",
    ],
    "currency": ["currency", "currency code", "currency symbol"],
    "quantity": ["quantity", "qty", "units", "count", "qty purchased"],
    "email": [
        "customer email", "email", "buyer email", "email address",
        "purchaser email",
    ],
    "status": ["status", "order status", "payment status", "state"],
    "refunded": [
        "refunded", "refund status", "refund", "is refunded",
        "refund date",
    ],
    "question": [
        "buyer question", "question", "questions", "buyer message",
        "message", "notes", "note", "comment", "comments",
        "special instructions", "order notes",
    ],
}

_REQUIRED_FIELDS = ("date", "product", "price")

_TRUE_VALUES = {"refunded", "refund", "yes", "true", "1", "y", "full", "partial"}
_FALSE_VALUES = {
    "", "no", "false", "0", "n", "none", "null", "na", "n/a", "-", "--",
    "not refunded", "no refund", "pending", "processing", "in progress",
    "void", "0.0",
}
_EMPTY_VALUES = {"", "none", "null", "na", "n/a", "-", "--", "nan", "guest", "anonymous"}
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
# Union precomputed once — _clean_question runs per row and must not allocate a set each call.
_EMPTY_QUESTION_VALUES = _EMPTY_VALUES | {"no question", "none"}
# Deletion table for _parse_price: strip currency symbols + thousand separators in one C pass.
_PRICE_STRIP_TABLE = str.maketrans("", "", ",$€£")

_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
    "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y",
    "%m/%d/%y %I:%M:%S %p", "%m/%d/%y %I:%M %p", "%m/%d/%y",
    "%b %d, %Y %I:%M:%S %p", "%b %d, %Y %I:%M %p", "%b %d, %Y",
    "%b %d %Y %I:%M:%S %p", "%b %d %Y %I:%M %p", "%b %d %Y",
    "%B %d, %Y %I:%M:%S %p", "%B %d, %Y %I:%M %p", "%B %d, %Y",
    "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y",
    "%d.%m.%Y %H:%M", "%d.%m.%Y",
]


def _normalize_header(header: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace: 'Price (USD)' -> 'price usd'."""
    return re.sub(r"[^a-z0-9]+", " ", header.strip().lower()).strip()


def _clean(value: str) -> str:
    return (value or "").strip()


def _parse_date(raw: str) -> datetime | None:
    """Parse a date cell across ISO, US, and human-readable formats."""
    s = _clean(raw)
    if not s:
        return None
    # Strip trailing UTC/GMT (any case) — string ops instead of a per-row regex.
    if len(s) >= 3 and s[-3:].upper() in ("UTC", "GMT"):
        s = s[:-3].strip()
    if s.endswith("Z"):
        s = s[:-1].strip()
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_price(raw: str, divide_by_100: bool = False) -> float | None:
    """Parse a price cell (symbols, thousand separators, optional cents)."""
    s = _clean(raw)
    if not s:
        return None
    s = s.translate(_PRICE_STRIP_TABLE)
    try:
        value = float(s)
    except ValueError:
        return None
    if divide_by_100:
        value /= 100.0
    return value


def _parse_int(raw: str) -> int | None:
    """Parse an integer cell, tolerating decimal-looking values like '2.0'."""
    s = _clean(raw)
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _parse_bool_refund(raw: str) -> bool:
    """Interpret a refunded/refund-status cell as a boolean."""
    s = _clean(raw).lower()
    if s in _TRUE_VALUES:
        return True
    if s in _FALSE_VALUES:
        return False
    # Any other non-empty value (e.g. a refund date) counts as refunded.
    return bool(s)


def _clean_email(raw: str) -> str | None:
    s = _clean(raw)
    if not s or s.lower() in _EMPTY_VALUES:
        return None
    return s


def _clean_question(raw: str) -> str | None:
    s = _clean(raw)
    if not s or s.lower() in _EMPTY_QUESTION_VALUES:
        return None
    return s


def _clean_currency(raw: str) -> str:
    s = _clean(raw)
    if not s:
        return "USD"
    if s in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[s]
    return s.upper()


def _detect_source(headers_norm: list[str], hint: str | None) -> str:
    """Pick the schema family: explicit hint wins, else header signatures."""
    if hint in ("payhip", "gumroad", "generic"):
        return hint
    joined = " ".join(headers_norm)
    if "order id" in joined and ("order date" in joined or "order status" in joined):
        return "payhip"
    if "sale id" in joined and ("created at" in joined or "refunded" in joined):
        return "gumroad"
    return "generic"


def _map_headers(headers: list[str]) -> dict[str, int]:
    """Map each canonical field to the best-matching header column index."""
    mapping: dict[str, tuple[int, int]] = {}
    for idx, header in enumerate(headers):
        norm = _normalize_header(header)
        if not norm:
            continue
        best: tuple[str, int] | None = None
        for field, synonyms in _SYNONYMS.items():
            if norm in synonyms:
                prio = synonyms.index(norm)
                if best is None or prio < best[1]:
                    best = (field, prio)
        if best is None:
            continue
        field, prio = best
        if field not in mapping or prio < mapping[field][0]:
            mapping[field] = (prio, idx)
    return {field: idx for field, (prio, idx) in mapping.items()}


def _parse_row(
    row_no: int,
    row: list[str],
    colmap: dict[str, int],
    source: str,
    price_is_cents: bool,
    warnings: list[str],
) -> SaleRecord | None:
    """Parse one data row into a SaleRecord, or warn and return None."""
    def get(field: str) -> str:
        idx = colmap.get(field)
        if idx is None or idx >= len(row):
            return ""
        return row[idx] or ""

    date_raw = get("date")
    dt = _parse_date(date_raw)
    if dt is None:
        warnings.append(f"Row {row_no}: invalid or missing date {date_raw!r} — skipped")
        return None

    product = _clean(get("product"))
    if not product:
        warnings.append(f"Row {row_no}: missing product name — skipped")
        return None

    price_raw = get("price")
    price = _parse_price(price_raw, divide_by_100=price_is_cents)
    if price is None:
        warnings.append(f"Row {row_no}: invalid price {price_raw!r} — skipped")
        return None

    qty_raw = get("quantity")
    qty = _parse_int(qty_raw) if qty_raw.strip() else 1
    if qty is None or qty <= 0:
        warnings.append(f"Row {row_no}: invalid quantity {qty_raw!r} — defaulted to 1")
        qty = 1

    refunded = False
    refund_raw = get("refunded")
    if refund_raw.strip():
        refunded = _parse_bool_refund(refund_raw)
    status_raw = get("status")
    if status_raw.strip() and "refund" in status_raw.strip().lower():
        refunded = True
    if price < 0:
        refunded = True

    return SaleRecord(
        order_id=_clean(get("order_id")),
        date=dt,
        product=product,
        price=price,
        currency=_clean_currency(get("currency")),
        quantity=qty,
        customer_email=_clean_email(get("email")),
        question=_clean_question(get("question")),
        refunded=refunded,
        source=source,
    )


# --- Pass 2: dedicated parser routing (core/parsers package) ---------------
# source_hint values that route to a dedicated parser module.
_DEDICATED_SOURCES = ("shopify", "kofi", "lemon")

# source -> module path for lazy imports (imported only when needed).
_PARSER_MODULES: dict[str, str] = {
    "shopify": "core.parsers.shopify",
    "kofi": "core.parsers.ko_fi",
    "lemon": "core.parsers.lemon",
}

# Header signatures used for auto-detection when a parser module exists but
# lacks its own detect(headers) -> bool. Matched against NORMALIZED headers,
# substring-style, in _DEDICATED_SOURCES order (first match wins).
_DETECT_MARKERS: dict[str, tuple[str, ...]] = {
    "shopify": ("lineitem name",),
    "kofi": ("payment date",),
    "lemon": ("order", "created"),
}

_VALID_HINTS = (None, "payhip", "gumroad", "generic", "shopify", "kofi", "lemon")


def _load_parser(source: str) -> ModuleType | None:
    """Lazily import a dedicated parser module; None when unavailable.

    A broader than ImportError catch is intentional: sibling agents may be
    writing these modules concurrently, and a half-written file (e.g. a
    syntax error) must never make parse_csv raise.
    """
    module_name = _PARSER_MODULES.get(source)
    if module_name is None:
        return None
    try:
        return importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 — missing/broken module degrades gracefully
        return None


def _run_dedicated(
    module: ModuleType, text: str, warnings: list[str]
) -> tuple[list[SaleRecord], list[str]] | None:
    """Run a dedicated parser's parse(text); None when unusable or failed."""
    parse = getattr(module, "parse", None)
    if not callable(parse):
        return None
    try:
        result = parse(text)
    except Exception as exc:  # noqa: BLE001 — never crash on a bad parser
        warnings.append(f"Dedicated parser raised {exc!r}")
        return None
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], list)
        and isinstance(result[1], list)
    ):
        return result
    return None


def _detect_dedicated(headers: list[str]) -> str | None:
    """Return the first dedicated source whose header signature matches.

    Each module's own detect(headers) -> bool is preferred when present;
    otherwise the _DETECT_MARKERS fallback is used. A module that is
    missing or whose detect() misbehaves still falls back to markers, so
    routing never crashes. Order: shopify -> kofi -> lemon.
    """
    normalized = [_normalize_header(h) for h in headers]
    for source in _DEDICATED_SOURCES:
        module = _load_parser(source)
        matched = False
        detect = getattr(module, "detect", None) if module is not None else None
        if callable(detect):
            try:
                matched = bool(detect(headers))
            except Exception:  # noqa: BLE001 — a broken detect must not crash routing
                matched = False
        if not matched:
            markers = _DETECT_MARKERS.get(source, ())
            matched = all(any(m in h for h in normalized) for m in markers)
        if matched:
            return source
    return None


def parse_csv(text: str, source_hint: str | None = None) -> tuple[list[SaleRecord], list[str]]:
    """Parse CSV text into (records, warnings).

    source_hint may be "payhip", "gumroad" or "generic" (handled by the
    built-in synonym engine), or "shopify", "kofi", "lemon" (routed to the
    matching core/parsers/<name> module, imported lazily). With
    source_hint=None the header row is scanned — dedicated parsers first
    (shopify, kofi, lemon), then the built-in payhip/gumroad/generic
    detection. A missing or failing dedicated parser falls back to the
    built-in engine with a warning. Invalid rows are skipped and reported
    as warnings — never raised.
    """
    warnings: list[str] = []
    if source_hint not in _VALID_HINTS:
        warnings.append(f"Unknown source_hint {source_hint!r} — ignoring, auto-detecting")
        source_hint = None

    rows = [
        row for row in csv.reader(io.StringIO(text.lstrip("\ufeff")))
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        return [], ["CSV is empty — no rows to parse"]

    headers = rows[0]

    # Pass 2 routing: explicit dedicated hint wins, else header detection.
    dedicated = source_hint if source_hint in _DEDICATED_SOURCES else None
    if dedicated is None and source_hint is None:
        dedicated = _detect_dedicated(headers)

    if dedicated is not None:
        module = _load_parser(dedicated)
        if module is None:
            warnings.append(
                f"Dedicated parser for {dedicated!r} is not available "
                f"(core.parsers.{dedicated} missing) — using built-in parsing"
            )
        else:
            result = _run_dedicated(module, text, warnings)
            if result is not None:
                return result
            warnings.append(
                f"Dedicated parser for {dedicated!r} failed — using built-in parsing"
            )
        source_hint = None  # let the built-in engine auto-detect below

    colmap = _map_headers(headers)
    source = _detect_source([_normalize_header(h) for h in headers], source_hint)

    missing = [f for f in _REQUIRED_FIELDS if f not in colmap]
    if missing:
        warnings.append(
            f"Could not find required columns: {', '.join(missing)} "
            f"(detected source: {source})"
        )
        return [], warnings

    price_col = colmap["price"]
    price_is_cents = _normalize_header(headers[price_col]).endswith("cents")

    records: list[SaleRecord] = []
    for row_no, row in enumerate(rows[1:], start=2):
        try:
            record = _parse_row(row_no, row, colmap, source, price_is_cents, warnings)
            if record is not None:
                records.append(record)
        except Exception as exc:  # noqa: BLE001 — never crash on a bad row
            warnings.append(f"Row {row_no}: unexpected error ({exc!r}) — skipped")

    if not records and not warnings:
        warnings.append("No valid sales rows found")
    return records, warnings
