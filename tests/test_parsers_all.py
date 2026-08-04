"""Pass 3 (EXPANSION.md): fixtures for ALL 6 source formats, exact numbers.

Each source is parsed by its own parser module directly:
  * payhip / gumroad / generic -> core.parser.parse_csv(source_hint=...)
    (these schemas live in the built-in synonym engine, no dedicated module)
  * shopify / kofi / lemon      -> core.parsers.<module>.parse(text)

Exact per-record fields AND exact build_report aggregates are asserted, so
a regression in any parser or in analytics shows up as a red test.
"""
from datetime import datetime

import pytest

from core.analytics import build_report
from core.models import AnalyticsReport, SaleRecord
from core.parser import parse_csv
from core.parsers.ko_fi import parse as parse_kofi
from core.parsers.lemon import parse as parse_lemon
from core.parsers.shopify import parse as parse_shopify

PAYHIP_CSV = (
    "Order ID,Order Date,Product,Price,Currency,Quantity,Customer Email,Order Status,Buyer Question\n"
    "ORD-2001,2026-07-01 09:14:22,Notion Template Pack,19.00,USD,1,alice@example.com,Completed,\n"
    'ORD-2002,2026-07-02 10:30:00,Notion Template Pack,19.00,USD,2,bob@example.com,Completed,'
    '"Can I get a PDF, please?"\n'
    "ORD-2003,2026-07-03 11:00:00,Ebook Guide,9.99,EUR,1,carol@example.com,Refunded,\n"
)

GUMROAD_CSV = (
    "sale_id,email,product_name,price_cents,created_at,quantity,currency,refunded\n"
    "G-2001,alice@example.com,Minimal Notion Pack,1900,2026-07-01T10:00:00Z,1,usd,false\n"
    "G-2002,bob@example.com,Minimal Notion Pack,3800,2026-07-02 11:30:00,2,usd,true\n"
    "G-2003,carol@example.com,PDF Side Hustle Guide,1900,7/3/2026,1,usd,false\n"
)

SHOPIFY_CSV = (
    "Name,Created at,Total,Lineitem quantity,Lineitem name,Financial status,Email\n"
    "#1001,2026-07-01 12:00:00,25.00,1,Coffee Mug,paid,alice@example.com\n"
    "#1002,2026-07-02 13:00:00,40.00,2,Coffee Mug,paid,bob@example.com\n"
    "#1003,2026-07-03 14:00:00,15.00,1,Sticker Pack,refunded,carol@example.com\n"
)

KOFI_CSV = (
    "Payment Date,Gross,Item,Email,Payment Type\n"
    "2026-07-01 09:00:00,5.00,Coffee,alice@example.com,Donation\n"
    "2026-07-02 10:00:00,10.00,Digital Product,bob@example.com,Refund\n"
    "2026-07-03 11:00:00,5.00,Membership,carol@example.com,Donation\n"
)

LEMON_CSV = (
    "Order,Created,Total,Product,Email,Status\n"
    "LS-3001,2026-07-01 08:00:00,25.00,Pro Plan,alice@example.com,paid\n"
    "LS-3002,2026-07-02 09:00:00,50.00,Pro Plan,bob@example.com,refunded\n"
    "LS-3003,2026-07-03 10:00:00,12.50,Starter,carl@example.com,paid\n"
)

GENERIC_CSV = (
    "Date,Product,Amount,Quantity,Email,Question\n"
    "2026-07-01,Widget Pro,50.00,1,joe@example.com,\n"
    "2026-07-02,Widget Pro,-50.00,1,jane@example.com,Do you ship internationally?\n"
    "2026-07-03,Gadget Mini,25.00,2,,\n"
)


# --------------------------------------------------------------------------
# payhip (built-in engine, explicit source_hint)
# --------------------------------------------------------------------------
def test_payhip_records_exact() -> None:
    records, warnings = parse_csv(PAYHIP_CSV, source_hint="payhip")
    assert warnings == []
    assert len(records) == 3

    r0, r1, r2 = records
    assert r0.order_id == "ORD-2001"
    assert r0.date == datetime(2026, 7, 1, 9, 14, 22)
    assert r0.product == "Notion Template Pack"
    assert r0.price == 19.0
    assert r0.currency == "USD"
    assert r0.quantity == 1
    assert r0.customer_email == "alice@example.com"
    assert r0.question is None
    assert r0.refunded is False

    assert r1.order_id == "ORD-2002"
    assert r1.date == datetime(2026, 7, 2, 10, 30, 0)
    assert r1.price == 19.0
    assert r1.quantity == 2
    assert r1.question == "Can I get a PDF, please?"

    assert r2.order_id == "ORD-2003"
    assert r2.date == datetime(2026, 7, 3, 11, 0, 0)
    assert r2.product == "Ebook Guide"
    assert r2.price == 9.99
    assert r2.currency == "EUR"
    assert r2.refunded is True

    assert {r.source for r in records} == {"payhip"}


def test_payhip_report_exact() -> None:
    records, _ = parse_csv(PAYHIP_CSV, source_hint="payhip")
    report = build_report(records)
    assert report.total_revenue == 57.0          # 19 + 19*2 ; refunded excluded
    assert report.total_orders == 2
    assert report.unique_customers == 2
    assert report.avg_order_value == 28.5
    assert report.repeat_purchase_rate == 0.0
    assert report.period_start == "2026-07-01"
    assert report.period_end == "2026-07-03"
    top = report.top_products[0]
    assert top.name == "Notion Template Pack"
    assert top.revenue == 57.0
    assert top.units == 3
    assert top.share_pct == 100.0
    assert top.refunds == 0
    assert [(d.date, d.revenue, d.orders) for d in report.revenue_by_day] == [
        ("2026-07-01", 19.0, 1),
        ("2026-07-02", 38.0, 1),
        ("2026-07-03", 0.0, 0),
    ]


# --------------------------------------------------------------------------
# gumroad (built-in engine, explicit source_hint; price_cents -> dollars)
# --------------------------------------------------------------------------
def test_gumroad_records_exact() -> None:
    records, warnings = parse_csv(GUMROAD_CSV, source_hint="gumroad")
    assert warnings == []
    assert len(records) == 3

    r0, r1, r2 = records
    assert r0.order_id == "G-2001"
    assert r0.date == datetime(2026, 7, 1, 10, 0, 0)
    assert r0.product == "Minimal Notion Pack"
    assert r0.price == 19.0          # 1900 cents / 100
    assert r0.currency == "USD"
    assert r0.quantity == 1
    assert r0.refunded is False

    assert r1.order_id == "G-2002"
    assert r1.date == datetime(2026, 7, 2, 11, 30, 0)
    assert r1.price == 38.0
    assert r1.quantity == 2
    assert r1.refunded is True

    assert r2.order_id == "G-2003"
    assert r2.date == datetime(2026, 7, 3)     # US m/d/Y
    assert r2.product == "PDF Side Hustle Guide"
    assert r2.price == 19.0
    assert r2.refunded is False

    assert {r.source for r in records} == {"gumroad"}


def test_gumroad_report_exact() -> None:
    records, _ = parse_csv(GUMROAD_CSV, source_hint="gumroad")
    report = build_report(records)
    assert report.total_revenue == 38.0
    assert report.total_orders == 2
    assert report.unique_customers == 2
    assert report.avg_order_value == 19.0
    top0, top1 = report.top_products
    # G-2002 (refunded) is Minimal Notion Pack: refund counted, revenue not.
    assert (top0.name, top0.revenue, top0.units, top0.share_pct, top0.refunds) == (
        "Minimal Notion Pack", 19.0, 1, 50.0, 1,
    )
    assert (top1.name, top1.revenue, top1.units, top1.share_pct, top1.refunds) == (
        "PDF Side Hustle Guide", 19.0, 1, 50.0, 0,
    )
    assert [(d.date, d.revenue, d.orders) for d in report.revenue_by_day] == [
        ("2026-07-01", 19.0, 1),
        ("2026-07-02", 0.0, 0),
        ("2026-07-03", 19.0, 1),
    ]


# --------------------------------------------------------------------------
# shopify (dedicated module, direct parse; Total is order total -> /qty)
# --------------------------------------------------------------------------
def test_shopify_records_exact() -> None:
    records, warnings = parse_shopify(SHOPIFY_CSV)
    assert warnings == []
    assert len(records) == 3

    r0, r1, r2 = records
    assert r0.order_id == "#1001"
    assert r0.date == datetime(2026, 7, 1, 12, 0, 0)
    assert r0.product == "Coffee Mug"
    assert r0.price == 25.0
    assert r0.currency == "USD"
    assert r0.quantity == 1
    assert r0.refunded is False

    assert r1.order_id == "#1002"
    assert r1.date == datetime(2026, 7, 2, 13, 0, 0)
    assert r1.price == 20.0          # 40.00 order total / qty 2
    assert r1.quantity == 2
    assert r1.refunded is False

    assert r2.order_id == "#1003"
    assert r2.date == datetime(2026, 7, 3, 14, 0, 0)
    assert r2.product == "Sticker Pack"
    assert r2.price == 15.0
    assert r2.refunded is True       # Financial status = refunded

    assert {r.source for r in records} == {"shopify"}


def test_shopify_report_exact() -> None:
    records, _ = parse_shopify(SHOPIFY_CSV)
    report = build_report(records)
    assert report.total_revenue == 65.0          # 25 + 20*2
    assert report.total_orders == 2
    assert report.unique_customers == 2
    assert report.avg_order_value == 32.5
    top = report.top_products[0]
    # Refunded #1003 is Sticker Pack, so Coffee Mug refunds stays 0.
    assert (top.name, top.revenue, top.units, top.share_pct, top.refunds) == (
        "Coffee Mug", 65.0, 3, 100.0, 0,
    )
    assert [(d.date, d.revenue, d.orders) for d in report.revenue_by_day] == [
        ("2026-07-01", 25.0, 1),
        ("2026-07-02", 40.0, 1),
        ("2026-07-03", 0.0, 0),
    ]


# --------------------------------------------------------------------------
# kofi (dedicated module, direct parse; Payment Type refund detection)
# --------------------------------------------------------------------------
def test_kofi_records_exact() -> None:
    records, warnings = parse_kofi(KOFI_CSV)
    assert warnings == []
    assert len(records) == 3

    r0, r1, r2 = records
    assert r0.date == datetime(2026, 7, 1, 9, 0, 0)
    assert r0.product == "Coffee"
    assert r0.price == 5.0
    assert r0.currency == "USD"
    assert r0.quantity == 1
    assert r0.customer_email == "alice@example.com"
    assert r0.refunded is False

    assert r1.date == datetime(2026, 7, 2, 10, 0, 0)
    assert r1.product == "Digital Product"
    assert r1.price == 10.0
    assert r1.refunded is True       # Payment Type = Refund

    assert r2.date == datetime(2026, 7, 3, 11, 0, 0)
    assert r2.product == "Membership"
    assert r2.price == 5.0
    assert r2.refunded is False

    assert {r.source for r in records} == {"kofi"}


def test_kofi_report_exact() -> None:
    records, _ = parse_kofi(KOFI_CSV)
    report = build_report(records)
    assert report.total_revenue == 10.0
    assert report.total_orders == 2
    assert report.unique_customers == 2
    assert report.avg_order_value == 5.0
    top0, top1 = report.top_products
    assert (top0.name, top0.revenue, top0.units, top0.share_pct) == (
        "Coffee", 5.0, 1, 50.0,
    )
    assert (top1.name, top1.revenue, top1.units, top1.share_pct) == (
        "Membership", 5.0, 1, 50.0,
    )
    assert [(d.date, d.revenue, d.orders) for d in report.revenue_by_day] == [
        ("2026-07-01", 5.0, 1),
        ("2026-07-02", 0.0, 0),
        ("2026-07-03", 5.0, 1),
    ]


# --------------------------------------------------------------------------
# lemon (dedicated module, direct parse; Status refund detection)
# --------------------------------------------------------------------------
def test_lemon_records_exact() -> None:
    records, warnings = parse_lemon(LEMON_CSV)
    assert warnings == []
    assert len(records) == 3

    r0, r1, r2 = records
    assert r0.order_id == "LS-3001"
    assert r0.date == datetime(2026, 7, 1, 8, 0, 0)
    assert r0.product == "Pro Plan"
    assert r0.price == 25.0
    assert r0.currency == "USD"
    assert r0.quantity == 1
    assert r0.refunded is False

    assert r1.order_id == "LS-3002"
    assert r1.date == datetime(2026, 7, 2, 9, 0, 0)
    assert r1.price == 50.0
    assert r1.refunded is True       # Status = refunded

    assert r2.order_id == "LS-3003"
    assert r2.date == datetime(2026, 7, 3, 10, 0, 0)
    assert r2.product == "Starter"
    assert r2.price == 12.5
    assert r2.refunded is False

    assert {r.source for r in records} == {"lemon"}


def test_lemon_report_exact() -> None:
    records, _ = parse_lemon(LEMON_CSV)
    report = build_report(records)
    assert report.total_revenue == 37.5
    assert report.total_orders == 2
    assert report.unique_customers == 2
    assert report.avg_order_value == 18.75
    top0, top1 = report.top_products
    assert (top0.name, top0.revenue, top0.units, top0.share_pct, top0.refunds) == (
        "Pro Plan", 25.0, 1, 66.67, 1,
    )
    assert (top1.name, top1.revenue, top1.units, top1.share_pct, top1.refunds) == (
        "Starter", 12.5, 1, 33.33, 0,
    )
    assert [(d.date, d.revenue, d.orders) for d in report.revenue_by_day] == [
        ("2026-07-01", 25.0, 1),
        ("2026-07-02", 0.0, 0),
        ("2026-07-03", 12.5, 1),
    ]


# --------------------------------------------------------------------------
# generic (built-in engine, explicit source_hint; negative price = refund)
# --------------------------------------------------------------------------
def test_generic_records_exact() -> None:
    records, warnings = parse_csv(GENERIC_CSV, source_hint="generic")
    assert warnings == []
    assert len(records) == 3

    r0, r1, r2 = records
    assert r0.date == datetime(2026, 7, 1)
    assert r0.product == "Widget Pro"
    assert r0.price == 50.0
    assert r0.currency == "USD"
    assert r0.quantity == 1
    assert r0.customer_email == "joe@example.com"
    assert r0.refunded is False

    assert r1.date == datetime(2026, 7, 2)
    assert r1.price == -50.0
    assert r1.refunded is True       # negative price
    assert r1.question == "Do you ship internationally?"

    assert r2.date == datetime(2026, 7, 3)
    assert r2.product == "Gadget Mini"
    assert r2.price == 25.0
    assert r2.quantity == 2
    assert r2.customer_email is None

    assert {r.source for r in records} == {"generic"}


def test_generic_report_exact() -> None:
    records, _ = parse_csv(GENERIC_CSV, source_hint="generic")
    report = build_report(records)
    assert report.total_revenue == 100.0         # 50 + 25*2
    assert report.total_orders == 2
    assert report.unique_customers == 1          # row 3 has no email
    assert report.avg_order_value == 50.0
    top0, top1 = report.top_products             # tie on revenue -> alpha order
    assert (top0.name, top0.revenue, top0.units, top0.share_pct, top0.refunds) == (
        "Gadget Mini", 50.0, 2, 50.0, 0,
    )
    assert (top1.name, top1.revenue, top1.units, top1.share_pct, top1.refunds) == (
        "Widget Pro", 50.0, 1, 50.0, 1,
    )
    assert [(d.date, d.revenue, d.orders) for d in report.revenue_by_day] == [
        ("2026-07-01", 50.0, 1),
        ("2026-07-02", 0.0, 0),
        ("2026-07-03", 50.0, 1),
    ]


# --------------------------------------------------------------------------
# routing: parse_csv auto-detects the dedicated parsers without a hint
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected_source"),
    [
        (SHOPIFY_CSV, "shopify"),
        (KOFI_CSV, "kofi"),
        (LEMON_CSV, "lemon"),
    ],
)
def test_auto_detect_dedicated_sources(text: str, expected_source: str) -> None:
    records, warnings = parse_csv(text)
    assert warnings == []
    assert records
    assert {r.source for r in records} == {expected_source}


def test_all_fixtures_yield_sale_records() -> None:
    """Every fixture parses into SaleRecord instances (type contract)."""
    for records, _ in (
        parse_csv(PAYHIP_CSV, source_hint="payhip"),
        parse_csv(GUMROAD_CSV, source_hint="gumroad"),
        parse_shopify(SHOPIFY_CSV),
        parse_kofi(KOFI_CSV),
        parse_lemon(LEMON_CSV),
        parse_csv(GENERIC_CSV, source_hint="generic"),
    ):
        assert records
        assert all(isinstance(r, SaleRecord) for r in records)
