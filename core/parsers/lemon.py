"""core/parsers/lemon.py — Lemon Squeezy orders CSV parsing.

Reads raw CSV text from a Lemon Squeezy orders export (columns: Order,
Created, Total, Product, Email, Status) and normalizes it into SaleRecord
objects. Header matching is case-insensitive, whitespace-normalized and
synonym-based, mirroring core/parser.py. Invalid rows are reported as
warnings, never raised.

Refund detection: an order is marked refunded when its Status cell
contains "refund" (e.g. "refunded", "partially_refunded"), or when the
Total is negative.
"""
from __future__ import annotations

import csv
import io

from core.models import SaleRecord
from core.parser import (
    _clean,
    _clean_currency,
    _clean_email,
    _normalize_header,
    _parse_date,
    _parse_int,
    _parse_price,
)

SUPPORTED_SOURCES = {"lemon", "lemonsqueezy", "lemon squeezy"}


def detect(headers: list[str]) -> bool:
    """True when headers look like a Lemon Squeezy orders export.

    Signature: an 'Order' column and a 'Created' column are both present
    (case/whitespace/punctuation-insensitive).
    """
    norm = [_normalize_header(h) for h in headers]
    return any("order" in h for h in norm) and any("created" in h for h in norm)


# Canonical field -> accepted (normalized) header synonyms, best first.
# Earlier entries win when several headers match the same field.
_SYNONYMS: dict[str, list[str]] = {
    "order_id": ["order", "order id", "order number", "sale id"],
    "date": ["created", "created at", "date", "order date", "purchase date"],
    "product": ["product", "product name", "product title", "item", "variant"],
    "price": ["total", "amount", "order total", "price", "subtotal"],
    "currency": ["currency", "currency code"],
    "quantity": ["quantity", "qty", "units"],
    "email": ["email", "customer email", "buyer email", "user email"],
    "status": ["status", "order status", "payment status", "state"],
}

_REQUIRED_FIELDS = ("date", "product", "price")


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
    status_raw = get("status")
    if "refund" in status_raw.strip().lower():
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
        refunded=refunded,
        source="lemon",
    )


def parse(text: str) -> tuple[list[SaleRecord], list[str]]:
    """Parse Lemon Squeezy orders CSV text into (records, warnings).

    Invalid rows are skipped and reported as warnings — never raised.
    """
    warnings: list[str] = []
    if not isinstance(text, str):
        warnings.append(f"Expected CSV text, got {type(text).__name__} — nothing parsed")
        return [], warnings
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
            f"(detected source: lemon)"
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
