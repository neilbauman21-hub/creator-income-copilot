"""Pass 3 (EXPANSION.md): 50 randomized CSV fuzz tests, fixed seed.

Each fuzz CSV is produced by a randomized generator (`_generate_fuzz_csv`)
covering: random column permutations, missing columns (incl. required),
BOM prefix, CRLF vs LF line endings, quoted commas, unicode product
names, negative/zero prices, duplicate order IDs, huge quantities, and
mixed date formats (ISO / US m/d/Y / EU d/m/Y / epoch seconds).

Hard invariants asserted for EVERY generated CSV (the contract from
EXPANSION.md):
  * parse_csv(text) never raises and returns (list[SaleRecord], list[str])
  * build_report(records) never raises and returns an AnalyticsReport

Note on spec wording vs. implementation: the core parser handles hostile
input by warn-and-skip (bad dates/prices), warn-and-default (bad qty),
or marking refunded (negative prices); duplicate order IDs and huge
quantities are currently kept as-is by the parser. The invariant we
enforce is the hard contract: never raise, always produce a valid report.
"""
from __future__ import annotations

import csv
import io
import random
from datetime import datetime

import pytest

from core.analytics import build_report
from core.models import AnalyticsReport, SaleRecord
from core.parser import parse_csv

SEED = 20260804
NUM_FUZZ = 50

PRODUCTS = [
    "Notion Minimalist Pack",
    "Ebook - Side Hustle Guide",
    "Café ☕ Starter Kit",
    "日本語テンプレート",
    "Sticker Pack, Deluxe",
    "API Course (2026)",
    "München Travel Guide",
    "Pro Template — v2",
]

PRICE_POOL = ["19.00", "9.99", "5.00", "0.00", "-12.50", "49.50", "250", "1,299.99", "$7.99", "free", "not-a-price", ""]

QTY_POOL = ["1", "2", "3", "0", "-1", "999999999999", "2.5", ""]

DATE_POOL = [
    "2026-07-01 09:14:22",       # ISO with time
    "2026-07-02",                # ISO date only
    "2026-07-03T10:30:00Z",      # ISO with Z suffix
    "07/04/2026",                # US m/d/Y
    "07/05/2026 2:05:11 PM",     # US m/d/Y with time
    "06/07/2026",                # EU d/m/Y (parses as US)
    "05.07.2026",                # EU d.m.Y
    "1751385600",                # epoch seconds (unparseable -> warn+skip)
    "not-a-date",                # garbage -> warn+skip
    "",                          # empty -> warn+skip
]

SCHEMAS: dict[str, list[str]] = {
    "payhip": ["Order ID", "Order Date", "Product", "Price", "Currency", "Quantity", "Customer Email", "Order Status", "Buyer Question"],
    "gumroad": ["sale_id", "email", "product_name", "price_cents", "created_at", "quantity", "currency", "refunded"],
    "shopify": ["Name", "Created at", "Total", "Lineitem quantity", "Lineitem name", "Financial status", "Email"],
    "kofi": ["Payment Date", "Gross", "Item", "Email", "Payment Type"],
    "lemon": ["Order", "Created", "Total", "Product", "Email", "Status"],
    "generic": ["Date", "Product", "Amount", "Quantity", "Email", "Question"],
}

REQUIRED: dict[str, list[str]] = {
    "payhip": ["Order Date", "Product", "Price"],
    "gumroad": ["created_at", "product_name", "price_cents"],
    "shopify": ["Created at", "Lineitem name", "Total"],
    "kofi": ["Payment Date", "Item", "Gross"],
    "lemon": ["Created", "Product", "Total"],
    "generic": ["Date", "Product", "Amount"],
}


def _generate_fuzz_csv(seed: int) -> tuple[str, set[str]]:
    """Generate one randomized CSV plus the set of features it exercises."""
    rng = random.Random(seed)
    features: set[str] = set()

    schema_name = rng.choice(list(SCHEMAS))
    headers = list(SCHEMAS[schema_name])

    # Random column permutation.
    if rng.random() < 0.55:
        rng.shuffle(headers)
        features.add("permuted")

    # Randomly drop 1-2 columns; sometimes a required one.
    if rng.random() < 0.55 and len(headers) > 2:
        drop = rng.sample(headers, rng.randint(1, min(2, len(headers) - 1)))
        for col in drop:
            headers.remove(col)
        features.add("missing_col")
        if any(col in REQUIRED[schema_name] for col in drop):
            features.add("missing_required")

    used_ids: list[str] = []

    def pick_product() -> str:
        p = rng.choice(PRODUCTS)
        if any(ord(c) > 127 for c in p):
            features.add("unicode")
        if "," in p:
            features.add("quoted_comma")
        return p

    def cell(header: str) -> str:
        h = header.lower()
        if "quantity" in h or "qty" in h or "units" in h or "count" in h:
            v = rng.choice(QTY_POOL)
            if v == "999999999999":
                features.add("huge_qty")
            return v
        if "lineitem" in h:
            return pick_product()
        if "date" in h or "created" in h:
            v = rng.choice(DATE_POOL)
            if v.startswith("1751"):
                features.add("epoch")
            elif "/" in v:
                features.add("us_or_eu_date")
            elif "." in v:
                features.add("eu_date")
            elif v in ("not-a-date", ""):
                features.add("bad_date")
            else:
                features.add("iso_date")
            return v
        if "price" in h or "total" in h or "amount" in h or "gross" in h:
            v = rng.choice(PRICE_POOL)
            if v == "0.00":
                features.add("zero_price")
            elif v.startswith("-"):
                features.add("neg_price")
            elif v in ("free", "not-a-price"):
                features.add("bad_price")
            return v
        if "product" in h or "item" in h or "title" in h:
            return pick_product()
        if "email" in h:
            return rng.choice(["alice@example.com", "bob@example.com", "guest", ""])
        if "currency" in h:
            return rng.choice(["USD", "usd", "€", "EUR", ""])
        if "refund" in h:
            return rng.choice(["", "false", "no", "true", "refunded", "2026-07-10"])
        if "status" in h or "state" in h or "type" in h:
            return rng.choice(["completed", "paid", "refunded", "Refund", "pending", "donation", ""])
        if "order" in h or "sale" in h or "id" in h or "name" in h:
            if used_ids and rng.random() < 0.3:
                features.add("dup_id")
                return rng.choice(used_ids)
            oid = f"{schema_name.upper()}-{rng.randint(1000, 9999)}"
            used_ids.append(oid)
            return oid
        if "question" in h or "message" in h or "note" in h or "comment" in h:
            v = rng.choice(["", "Do you ship internationally?", "Can I get a PDF, please?", "ありがとうございます！"])
            if "," in v:
                features.add("quoted_comma")
            return v
        return ""

    lineterm = "\r\n" if rng.random() < 0.4 else "\n"
    if lineterm == "\r\n":
        features.add("crlf")

    rows = [[cell(h) for h in headers] for _ in range(rng.randint(2, 12))]

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator=lineterm)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    text = buf.getvalue()

    if rng.random() < 0.3:
        text = "\ufeff" + text
        features.add("bom")

    if rng.random() < 0.06:
        text = ""
        features.add("empty")
    elif rng.random() < 0.08:
        text = text.split(lineterm)[0] + lineterm
        features.add("header_only")

    return text, features


# Deterministic set of 50 fuzz cases (fixed seed -> reproducible failures).
FUZZ_CASES: list[tuple[str, set[str]]] = [_generate_fuzz_csv(SEED + i) for i in range(NUM_FUZZ)]


@pytest.mark.parametrize("case", FUZZ_CASES, ids=[f"fuzz-{i:02d}" for i in range(NUM_FUZZ)])
def test_fuzz_parse_and_report_never_raise(case: tuple[str, set[str]]) -> None:
    text, _features = case

    # parse_csv must NEVER raise and must return (records, warnings).
    result = parse_csv(text)
    assert isinstance(result, tuple) and len(result) == 2
    records, warnings = result
    assert isinstance(records, list)
    assert isinstance(warnings, list)
    assert all(isinstance(r, SaleRecord) for r in records)
    assert all(isinstance(r.date, datetime) for r in records)
    assert all(isinstance(r.product, str) and r.product for r in records)
    assert all(isinstance(r.price, float) for r in records)

    # build_report must NEVER raise and must return an AnalyticsReport.
    report = build_report(records)
    assert isinstance(report, AnalyticsReport)
    assert isinstance(report.total_revenue, float)
    assert isinstance(report.total_orders, int)
    assert isinstance(report.period_start, str)
    assert isinstance(report.period_end, str)


def test_fuzz_suite_covers_all_required_categories() -> None:
    """Guard that the 50 cases actually exercise every required dimension."""
    seen: set[str] = set()
    for _text, feats in FUZZ_CASES:
        seen |= feats
    required = {
        "bom",
        "crlf",
        "permuted",
        "missing_col",
        "missing_required",
        "quoted_comma",
        "unicode",
        "neg_price",
        "zero_price",
        "dup_id",
        "huge_qty",
        "iso_date",
        "us_or_eu_date",
        "eu_date",
        "epoch",
        "empty",
    }
    missing = required - seen
    assert not missing, f"fuzz suite missing categories: {sorted(missing)}"


def test_fuzz_is_deterministic() -> None:
    """Same seed -> identical CSVs, so failures are reproducible."""
    for seed in (SEED, SEED + 1, SEED + NUM_FUZZ - 1):
        a = _generate_fuzz_csv(seed)
        b = _generate_fuzz_csv(seed)
        assert a == b
