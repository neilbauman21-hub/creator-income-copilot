"""Tests for core.parsers.shopify.parse — Shopify orders export schema."""
from datetime import datetime

import pytest

from core.models import SaleRecord
from core.parsers.shopify import SUPPORTED_SOURCES, parse


@pytest.fixture
def shopify_csv() -> str:
    """Realistic Shopify orders export: order total, per-line-item rows.

    Includes extra real-world columns (Subtotal, Shipping, Tags) that must be
    ignored in favour of 'Total', and one order (#1007) split across two
    line-item rows — exactly how Shopify exports multi-item orders.
    """
    return (
        "Name,Email,Created at,Total,Subtotal,Shipping,Currency,"
        "Lineitem quantity,Lineitem name,Financial status,Tags\n"
        "#1001,alice@example.com,2026-06-01 14:32:00 -0400,29.00,29.00,0.00,USD,1,Notion Minimalist Pack,paid,\n"
        "#1002,bob@example.com,2026-06-02 09:15:00 -0400,58.00,58.00,0.00,USD,2,Notion Minimalist Pack,paid,\n"
        '#1003,carol@example.com,2026-06-03 18:45:00 -0400,9.99,9.99,0.00,USD,1,"Ebook - Side Hustle Guide",refunded,\n'
        "#1004,dave@example.com,2026-06-04 11:20:00 -0400,19.99,19.99,4.00,USD,1,PDF Invoice Template,voided,\n"
        "#1005,eve@example.com,2026-06-05 08:05:00 -0400,35.00,35.00,0.00,USD,1,Notion Minimalist Pack,partially refunded,\n"
        "#1006,alice@example.com,2026-06-06 10:00:00 -0400,9.99,9.99,0.00,USD,3,Ebook - Side Hustle Guide,paid,\n"
        "#1007,frank@example.com,2026-06-07 12:30:00 -0400,12.00,12.00,0.00,USD,1,Sticker Pack,paid,\n"
        "#1007,frank@example.com,2026-06-07 12:30:00 -0400,8.00,8.00,0.00,USD,1,Mini Poster,paid,\n"
    )


def test_shopify_sale_record_shape(shopify_csv: str) -> None:
    records, warnings = parse(shopify_csv)
    assert warnings == []
    assert isinstance(records[0], SaleRecord)
    rec = records[0]
    assert rec.order_id == "#1001"
    assert rec.date == datetime(2026, 6, 1, 14, 32, 0)
    assert rec.product == "Notion Minimalist Pack"
    assert rec.price == 29.0
    assert rec.currency == "USD"
    assert rec.quantity == 1
    assert rec.customer_email == "alice@example.com"
    assert rec.refunded is False
    assert rec.source == "shopify"


def test_shopify_offset_datetime_stripped_to_naive(shopify_csv: str) -> None:
    records, warnings = parse(shopify_csv)
    assert warnings == []
    assert records[0].date == datetime(2026, 6, 1, 14, 32, 0)
    assert records[0].date.tzinfo is None


def test_shopify_price_is_total_per_unit_when_qty_gt_1(shopify_csv: str) -> None:
    records, warnings = parse(shopify_csv)
    assert warnings == []
    # qty 2, total 58.00 -> per-unit price 29.00 (58 / 2)
    assert records[1].order_id == "#1002"
    assert records[1].quantity == 2
    assert records[1].price == 29.0
    # qty 3, total 9.99 -> per-unit price 3.33 (9.99 / 3, rounded)
    assert records[5].quantity == 3
    assert records[5].price == 3.33


def test_shopify_price_times_quantity_equals_order_total(shopify_csv: str) -> None:
    """SaleRecord invariant: per-unit price * quantity == Shopify order Total."""
    records, warnings = parse(shopify_csv)
    assert warnings == []
    totals = [29.00, 58.00, 9.99, 19.99, 35.00, 9.99, 12.00, 8.00]
    for rec, total in zip(records, totals):
        assert round(rec.price * rec.quantity, 2) == total


def test_shopify_refund_via_financial_status(shopify_csv: str) -> None:
    records, warnings = parse(shopify_csv)
    assert warnings == []
    # 'refunded' -> refunded
    assert records[2].refunded is True
    # 'partially refunded' contains 'refund' -> refunded
    assert records[4].refunded is True
    # 'paid' -> not refunded
    assert records[0].refunded is False
    # 'voided' contains no 'refund' -> not refunded
    assert records[3].refunded is False


def test_shopify_multi_lineitem_order_split_into_rows(shopify_csv: str) -> None:
    records, warnings = parse(shopify_csv)
    assert warnings == []
    assert records[6].order_id == "#1007"
    assert records[7].order_id == "#1007"
    assert records[6].product == "Sticker Pack"
    assert records[7].product == "Mini Poster"
    assert records[6].price == 12.0
    assert records[7].price == 8.0
    assert records[6].customer_email == records[7].customer_email == "frank@example.com"


def test_shopify_source_set_on_all_records(shopify_csv: str) -> None:
    records, _ = parse(shopify_csv)
    assert {r.source for r in records} == {"shopify"}


def test_shopify_case_and_whitespace_insensitive_headers_with_bom() -> None:
    text = (
        "\ufeffNAME,  EMAIL,  CREATED AT,  TOTAL,  LINEITEM QUANTITY,"
        "  LINEITEM  NAME,  FINANCIAL  STATUS\n"
        "#2001,  buyer@example.com,  2026-06-10 08:00:00 -0400,  45.00,"
        "  3,  Notion  Pack,  PAID\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert len(records) == 1
    rec = records[0]
    assert rec.order_id == "#2001"
    assert rec.date == datetime(2026, 6, 10, 8, 0, 0)
    assert rec.product == "Notion  Pack"  # inner spacing preserved in values
    assert rec.quantity == 3
    assert rec.price == 15.0  # 45.00 / 3
    assert rec.refunded is False


def test_shopify_bad_date_row_warned_and_skipped() -> None:
    text = (
        "Name,Created at,Total,Lineitem quantity,Lineitem name,Financial status\n"
        "#3001,2026-06-01 10:00:00 -0400,10.00,1,Product A,paid\n"
        "#3002,not-a-date,5.00,1,Product B,paid\n"
        "#3003,2026-06-03 10:00:00 -0400,7.00,1,Product C,paid\n"
    )
    records, warnings = parse(text)
    assert len(records) == 2
    assert [r.order_id for r in records] == ["#3001", "#3003"]
    assert any("Row 3" in w and "date" in w and "skipped" in w for w in warnings)


def test_shopify_bad_price_row_warned_and_skipped() -> None:
    text = (
        "Name,Created at,Total,Lineitem quantity,Lineitem name\n"
        "#3001,2026-06-01 10:00:00 -0400,10.00,1,Product A\n"
        "#3002,2026-06-02 10:00:00 -0400,free,1,Product B\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert records[0].order_id == "#3001"
    assert any("Row 3" in w and "price" in w and "skipped" in w for w in warnings)


def test_shopify_missing_product_warned_and_skipped() -> None:
    text = (
        "Name,Created at,Total,Lineitem quantity,Lineitem name\n"
        "#4001,2026-06-01 10:00:00 -0400,10.00,1,Product A\n"
        "#4002,2026-06-02 10:00:00 -0400,5.00,1,\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert any("Row 3" in w and "product" in w and "skipped" in w for w in warnings)


def test_shopify_bad_quantity_defaults_to_1() -> None:
    text = (
        "Name,Created at,Total,Lineitem quantity,Lineitem name\n"
        "#5001,2026-06-01 10:00:00 -0400,30.00,abc,Product A\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert records[0].quantity == 1
    assert records[0].price == 30.0  # not divided
    assert any("Row 2" in w and "quantity" in w and "defaulted" in w for w in warnings)


def test_shopify_missing_optional_columns_fallback() -> None:
    text = (
        "Name,Created at,Total,Lineitem name\n"
        "#6001,2026-06-01 10:00:00 -0400,29.00,Notion Pack\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    rec = records[0]
    assert rec.quantity == 1
    assert rec.price == 29.0
    assert rec.customer_email is None
    assert rec.currency == "USD"
    assert rec.refunded is False


def test_shopify_negative_total_marks_refund() -> None:
    text = (
        "Name,Created at,Total,Lineitem quantity,Lineitem name,Financial status\n"
        "#7001,2026-06-01 10:00:00 -0400,-29.00,1,Notion Pack,paid\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert records[0].refunded is True
    assert records[0].price == -29.0


def test_shopify_empty_csv_warns() -> None:
    records, warnings = parse("")
    assert records == []
    assert warnings and "empty" in warnings[0].lower()


def test_shopify_missing_required_columns_warns() -> None:
    records, warnings = parse("Name,Email\n#9001,alice@example.com\n")
    assert records == []
    assert any("required columns" in w and "shopify" in w for w in warnings)


def test_shopify_never_raises_on_garbage() -> None:
    # Ragged rows, missing cells, unicode — must warn, never raise.
    text = (
        "Name,Created at,Total,Lineitem quantity,Lineitem name\n"
        "#8001,2026-06-01 10:00:00 -0400,10.00,1,Ünïcode Pröduct\n"
        "#8002\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert records[0].product == "Ünïcode Pröduct"
    assert any("Row 3" in w and "skipped" in w for w in warnings)


def test_shopify_never_raises_on_non_str_input() -> None:
    # Non-string input (e.g. None from a malformed upload) must warn, never raise.
    for bad in (None, 123, b"Name,Created at\n"):
        records, warnings = parse(bad)
        assert records == []
        assert warnings and "Expected CSV text" in warnings[0]


def test_supported_sources_exported() -> None:
    assert isinstance(SUPPORTED_SOURCES, dict)
    assert "shopify" in SUPPORTED_SOURCES
    assert "Name" in SUPPORTED_SOURCES["shopify"]
    assert "Financial status" in SUPPORTED_SOURCES["shopify"]
