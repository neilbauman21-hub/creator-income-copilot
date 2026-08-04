"""core/parsers/ko_fi.py — Ko-fi payments export parser.

Reads raw CSV text from a Ko-fi payments export (Payment Date, Gross,
Item, Email/Buyer) and normalizes it into SaleRecord objects. Header
matching is case-insensitive, whitespace-normalized and synonym-based.
Quantity defaults to 1 when no quantity column is present. Invalid rows
are reported as warnings, never raised.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from core.models import SaleRecord

SUPPORTED_SOURCES: dict[str, str] = {
    "kofi": "Ko-fi payments export (Payment Date, Gross, Item, Email/Buyer)",
}


def detect(headers: list[str]) -> bool:
    """True when headers look like a Ko-fi payments export.

    Signature: a 'Payment Date' column is present
    (case/whitespace/punctuation-insensitive).
    """
    norm = [_normalize_header(h) for h in headers]
    return any("payment date" in h for h in norm)


# Canonical field -> accepted (normalized) header synonyms, best first.
# Earlier entries win when several headers match the same field.
_SYNONYMS: dict[str, list[str]] = {
    "order_id": [
        "transaction id", "transaction number", "payment id",
        "payment reference", "reference", "order number", "order id",
    ],
    "date": [
        "payment date", "date", "paid date", "paid at", "created at",
        "transaction date", "datetime", "timestamp",
    ],
    "product": [
        "item", "item name", "product", "product name", "title",
        "post title", "shop item", "product title",
    ],
    "price": [
        "gross", "gross amount", "amount", "total", "price",
        "revenue", "net", "net amount", "order total",
    ],
    "currency": ["currency", "currency code", "currency symbol"],
    "quantity": ["quantity", "qty", "units", "count"],
    "email": [
        "email", "buyer email", "email address", "buyer",
        "customer email", "purchaser email",
    ],
    "status": ["payment status", "status", "payment type", "state"],
    "type": ["type", "transaction type"],
    "refunded": [
        "refunded", "refund status", "refund", "is refunded",
        "refund date",
    ],
    "question": [
        "message", "note", "notes", "comment", "comments",
        "question", "buyer message",
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
    """Lowercase, strip punctuation, collapse whitespace: 'Payment Date' -> 'payment date'."""
    return re.sub(r"[^a-z0-9]+", " ", header.strip().lower()).strip()


def _clean(value: str) -> str:
    return (value or "").strip()


def _parse_date(raw: str) -> datetime | None:
    """Parse a date cell across ISO, US, and human-readable formats."""
    s = _clean(raw)
    if not s:
        return None
    s = re.sub(r"(?:UTC|GMT)$", "", s, flags=re.IGNORECASE).strip()
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


def _parse_price(raw: str) -> float | None:
    """Parse a price cell (symbols, thousand separators, optional cents)."""
    s = _clean(raw)
    if not s:
        return None
    s = s.replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    try:
        return float(s)
    except ValueError:
        return None


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
    if not s or s.lower() in _EMPTY_VALUES | {"no question", "none"}:
        return None
    return s


def _clean_currency(raw: str) -> str:
    s = _clean(raw)
    if not s:
        return "USD"
    if s in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[s]
    return s.upper()


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
    price = _parse_price(price_raw)
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
    type_raw = get("type")
    if type_raw.strip() and "refund" in type_raw.strip().lower():
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
        source="kofi",
    )


def _parse_impl(text: str) -> tuple[list[SaleRecord], list[str]]:
    warnings: list[str] = []
    rows = [
        row for row in csv.reader(io.StringIO(text.lstrip("\ufeff")))
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        return [], ["CSV is empty — no rows to parse"]

    headers = rows[0]
    colmap = _map_headers(headers)

    missing = [f for f in _REQUIRED_FIELDS if f not in colmap]
    if missing:
        warnings.append(
            f"Could not find required columns: {', '.join(missing)} "
            "(detected source: kofi)"
        )
        return [], warnings

    records: list[SaleRecord] = []
    for row_no, row in enumerate(rows[1:], start=2):
        try:
            record = _parse_row(row_no, row, colmap, warnings)
            if record is not None:
                records.append(record)
        except Exception as exc:  # noqa: BLE001 — never crash on a bad row
            warnings.append(f"Row {row_no}: unexpected error ({exc!r}) — skipped")

    if not records and not warnings:
        warnings.append("No valid sales rows found")
    return records, warnings


def parse(text: str) -> tuple[list[SaleRecord], list[str]]:
    """Parse Ko-fi payments export CSV text into (records, warnings).

    Expects columns like 'Payment Date', 'Gross', 'Item', and 'Email'
    (or 'Buyer'). Quantity defaults to 1 when absent. Invalid rows are
    skipped and reported as warnings — never raised.
    """
    try:
        return _parse_impl(text)
    except Exception as exc:  # noqa: BLE001 — never raise, even on garbage input
        return [], [f"Failed to parse Ko-fi export ({exc!r})"]
