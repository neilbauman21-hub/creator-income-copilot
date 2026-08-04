"""Tests for core.parser.parse_csv — Payhip / Gumroad / generic schemas."""
from datetime import datetime

import pytest

from core.models import SaleRecord
from core.parser import parse_csv


@pytest.fixture
def payhip_csv() -> str:
    return (
        "Order ID,Order Date,Product,Price,Currency,Quantity,Customer Email,Order Status,Buyer Question\n"
        "ORD-1001,2026-07-01 09:14:22,Notion Minimalist Pack,19.00,USD,1,alice@example.com,Completed,\n"
        'ORD-1002,"Jul 2, 2026 2:05:11 PM",Notion Minimalist Pack,19.00,USD,2,bob@example.com,Completed,Can I get a PDF version?\n'
        "ORD-1003,2026-07-03 18:30:00,Ebook - Side Hustle Guide,9.99,USD,1,carol@example.com,Refunded,\n"
        "ORD-1004,2026-07-04 11:00:00,Ebook - Side Hustle Guide,9.99,USD,1,dave@example.com,Completed,\n"
        'ORD-1005,2026-07-05 09:00:00,Notion Minimalist Pack,19.00,USD,1,eve@example.com,Completed,"Do you have a dark theme, and can I get a refund?"\n'
    )


@pytest.fixture
def gumroad_csv() -> str:
    return (
        "sale_id,email,product_name,price_cents,created_at,quantity,currency,refunded\n"
        "G-1001,alice@example.com,Minimal Notion Pack,1900,2026-07-01T10:00:00Z,1,usd,false\n"
        "G-1002,bob@example.com,Minimal Notion Pack,1900,2026-07-02 11:30:00,2,usd,true\n"
        "G-1003,carol@example.com,PDF Side Hustle Guide,999,7/3/2026,1,usd,false\n"
    )


@pytest.fixture
def generic_csv() -> str:
    return (
        "Date,Product,Amount,Quantity,Email,Question\n"
        "2026-07-01,Widget Pro,49.5,1,joe@example.com,\n"
        "2026-07-02,Widget Pro,-49.5,1,jane@example.com,Do you ship internationally?\n"
        "2026-07-03,Gadget Mini,29.99,2,,\n"
    )


def test_sale_record_shape(payhip_csv: str) -> None:
    records, warnings = parse_csv(payhip_csv)
    assert warnings == []
    assert isinstance(records[0], SaleRecord)
    rec = records[0]
    assert rec.order_id == "ORD-1001"
    assert rec.date == datetime(2026, 7, 1, 9, 14, 22)
    assert rec.product == "Notion Minimalist Pack"
    assert rec.price == 19.0
    assert rec.currency == "USD"
    assert rec.quantity == 1
    assert rec.customer_email == "alice@example.com"
    assert rec.question is None
    assert rec.refunded is False
    assert rec.source == "payhip"


def test_payhip_human_date_and_quantity(payhip_csv: str) -> None:
    records, warnings = parse_csv(payhip_csv)
    assert warnings == []
    rec = records[1]
    assert rec.date == datetime(2026, 7, 2, 14, 5, 11)
    assert rec.quantity == 2


def test_payhip_question_capture(payhip_csv: str) -> None:
    records, _ = parse_csv(payhip_csv)
    assert records[1].question == "Can I get a PDF version?"
    assert records[0].question is None


def test_payhip_quoted_question_with_comma(payhip_csv: str) -> None:
    records, warnings = parse_csv(payhip_csv)
    assert warnings == []
    assert records[4].question == "Do you have a dark theme, and can I get a refund?"


def test_payhip_refund_via_status(payhip_csv: str) -> None:
    records, _ = parse_csv(payhip_csv)
    assert records[2].refunded is True
    assert records[0].refunded is False


def test_payhip_source_autodetected(payhip_csv: str) -> None:
    records, _ = parse_csv(payhip_csv)
    assert {r.source for r in records} == {"payhip"}


def test_gumroad_cents_converted_to_dollars(gumroad_csv: str) -> None:
    records, warnings = parse_csv(gumroad_csv)
    assert warnings == []
    assert records[0].price == 19.0
    assert records[2].price == 9.99


def test_gumroad_iso_and_us_dates(gumroad_csv: str) -> None:
    records, _ = parse_csv(gumroad_csv)
    assert records[0].date == datetime(2026, 7, 1, 10, 0, 0)
    assert records[2].date == datetime(2026, 7, 3)


def test_gumroad_refunded_boolean(gumroad_csv: str) -> None:
    records, _ = parse_csv(gumroad_csv)
    assert records[0].refunded is False
    assert records[1].refunded is True
    assert records[2].refunded is False


def test_gumroad_currency_normalized_upper(gumroad_csv: str) -> None:
    records, _ = parse_csv(gumroad_csv)
    assert {r.currency for r in records} == {"USD"}


def test_gumroad_source_autodetected(gumroad_csv: str) -> None:
    records, _ = parse_csv(gumroad_csv)
    assert {r.source for r in records} == {"gumroad"}


def test_generic_source_autodetected(generic_csv: str) -> None:
    records, warnings = parse_csv(generic_csv)
    assert warnings == []
    assert {r.source for r in records} == {"generic"}


def test_generic_negative_price_marks_refund(generic_csv: str) -> None:
    records, _ = parse_csv(generic_csv)
    assert records[1].refunded is True
    assert records[1].price == -49.5
    assert records[0].refunded is False


def test_generic_question_and_missing_email(generic_csv: str) -> None:
    records, _ = parse_csv(generic_csv)
    assert records[1].question == "Do you ship internationally?"
    assert records[2].customer_email is None
    assert records[2].quantity == 2


def test_missing_optional_columns_fallback() -> None:
    text = (
        "Order Date,Product,Price\n"
        "2026-07-01,Notion Pack,19.00\n"
        "2026-07-02,Ebook,9.99\n"
    )
    records, warnings = parse_csv(text)
    assert warnings == []
    assert len(records) == 2
    for rec in records:
        assert rec.quantity == 1
        assert rec.customer_email is None
        assert rec.currency == "USD"
        assert rec.order_id == ""
        assert rec.question is None
        assert rec.refunded is False


def test_bad_date_row_warned_and_skipped() -> None:
    text = (
        "Order Date,Product,Price\n"
        "2026-07-01,Good Product,10.00\n"
        "not-a-date,Bad Product,5.00\n"
        "2026-07-03,Another Product,7.00\n"
    )
    records, warnings = parse_csv(text)
    assert len(records) == 2
    assert records[0].product == "Good Product"
    assert records[1].product == "Another Product"
    assert any("Row 3" in w and "date" in w and "skipped" in w for w in warnings)


def test_bad_price_row_warned_and_skipped() -> None:
    text = (
        "Date,Product,Price\n"
        "2026-07-01,Good Product,10.00\n"
        "2026-07-02,Bad Product,free\n"
    )
    records, warnings = parse_csv(text)
    assert len(records) == 1
    assert any("Row 3" in w and "price" in w and "skipped" in w for w in warnings)


def test_refund_detection_status_and_boolean_columns() -> None:
    text = (
        "Date,Product,Amount,Status,Refunded\n"
        "2026-07-01,Product A,10.00,Completed,No\n"
        "2026-07-02,Product B,20.00,Refunded,\n"
        "2026-07-03,Product C,30.00,Completed,Yes\n"
        "2026-07-04,Product D,40.00,Completed,\n"
    )
    records, warnings = parse_csv(text)
    assert warnings == []
    assert [r.refunded for r in records] == [False, True, True, False]


def test_refund_detection_via_refund_date_column() -> None:
    text = (
        "Date,Product,Amount,Refund Date\n"
        "2026-07-01,Product A,10.00,\n"
        "2026-07-02,Product B,20.00,2026-07-05\n"
    )
    records, warnings = parse_csv(text)
    assert warnings == []
    assert records[0].refunded is False
    assert records[1].refunded is True


def test_case_and_whitespace_insensitive_headers() -> None:
    text = (
        "ORDER  DATE,PRODUCT,AMOUNT,QUANTITY,EMAIL\n"
        "2026-07-01,Thing,12.50,3,buyer@example.com\n"
    )
    records, warnings = parse_csv(text)
    assert warnings == []
    assert records[0].product == "Thing"
    assert records[0].quantity == 3
    assert records[0].price == 12.5


def test_ragged_row_warned_and_skipped() -> None:
    text = (
        "Order Date,Product,Price,Quantity\n"
        "2026-07-01,Product A,10.00,1\n"
        "2026-07-02,Product B\n"
    )
    records, warnings = parse_csv(text)
    assert len(records) == 1
    assert any("Row 3" in w and "skipped" in w for w in warnings)


def test_empty_csv_warns() -> None:
    records, warnings = parse_csv("")
    assert records == []
    assert warnings and "empty" in warnings[0].lower()


def test_missing_required_columns_warns() -> None:
    records, warnings = parse_csv("Name,Age\nAlice,30\n")
    assert records == []
    assert any("required columns" in w for w in warnings)


def test_source_hint_override(payhip_csv: str) -> None:
    records, _ = parse_csv(payhip_csv, source_hint="gumroad")
    assert {r.source for r in records} == {"gumroad"}


def test_invalid_source_hint_ignored_with_warning(payhip_csv: str) -> None:
    records, warnings = parse_csv(payhip_csv, source_hint="stripe")
    assert {r.source for r in records} == {"payhip"}
    assert any("source_hint" in w for w in warnings)
