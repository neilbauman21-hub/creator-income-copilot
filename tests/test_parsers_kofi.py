"""Tests for core.parsers.ko_fi.parse — Ko-fi payments export schema."""
from datetime import datetime

import pytest

from core.models import SaleRecord
from core.parsers.ko_fi import SUPPORTED_SOURCES, parse


@pytest.fixture
def kofi_csv() -> str:
    return (
        "Payment Date,Gross,Item,Email,Currency\n"
        "2026-06-01,5.00,Sticker Pack,alice@example.com,USD\n"
        "2026-06-02,10.00,Coffee Support,bob@example.com,USD\n"
        "2026-06-03,15.00,Digital Zine,carol@example.com,EUR\n"
    )


@pytest.fixture
def kofi_buyer_csv() -> str:
    return (
        "Payment Date,Gross,Item,Buyer\n"
        "2026-06-05,7.50,Membership Tier,Jane Doe\n"
    )


@pytest.fixture
def kofi_qty_csv() -> str:
    return (
        "Payment Date,Gross,Item,Email,Quantity\n"
        "2026-06-06,25.00,Sticker Pack 10x,alice@example.com,10\n"
    )


def test_supported_sources_exports_kofi() -> None:
    assert "kofi" in SUPPORTED_SOURCES
    assert "Ko-fi" in SUPPORTED_SOURCES["kofi"]


def test_parse_basic_rows(kofi_csv: str) -> None:
    records, warnings = parse(kofi_csv)
    assert warnings == []
    assert len(records) == 3
    assert all(isinstance(r, SaleRecord) for r in records)
    assert all(r.source == "kofi" for r in records)


def test_exact_field_values(kofi_csv: str) -> None:
    records, _ = parse(kofi_csv)
    r0 = records[0]
    assert r0.date == datetime(2026, 6, 1)
    assert r0.product == "Sticker Pack"
    assert r0.price == 5.0
    assert r0.currency == "USD"
    assert r0.quantity == 1
    assert r0.customer_email == "alice@example.com"
    assert r0.order_id == ""
    assert r0.question is None
    assert r0.refunded is False
    assert records[1].date == datetime(2026, 6, 2)
    assert records[1].product == "Coffee Support"
    assert records[1].price == 10.0
    assert records[1].customer_email == "bob@example.com"
    assert records[2].date == datetime(2026, 6, 3)
    assert records[2].product == "Digital Zine"
    assert records[2].price == 15.0
    assert records[2].currency == "EUR"
    assert records[2].customer_email == "carol@example.com"


def test_quantity_defaults_to_one(kofi_csv: str) -> None:
    records, _ = parse(kofi_csv)
    assert all(r.quantity == 1 for r in records)


def test_buyer_column_used_as_customer(kofi_buyer_csv: str) -> None:
    records, warnings = parse(kofi_buyer_csv)
    assert warnings == []
    assert len(records) == 1
    assert records[0].date == datetime(2026, 6, 5)
    assert records[0].product == "Membership Tier"
    assert records[0].price == 7.5
    assert records[0].quantity == 1
    assert records[0].customer_email == "Jane Doe"


def test_quantity_column_parsed(kofi_qty_csv: str) -> None:
    records, warnings = parse(kofi_qty_csv)
    assert warnings == []
    assert len(records) == 1
    assert records[0].quantity == 10
    assert records[0].price == 25.0


def test_negative_gross_marks_refund() -> None:
    text = (
        "Payment Date,Gross,Item,Email\n"
        "2026-06-01,5.00,Sticker Pack,alice@example.com\n"
        "2026-06-02,-5.00,Sticker Pack,alice@example.com\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert records[0].refunded is False
    assert records[1].refunded is True
    assert records[1].price == -5.0


def test_status_refund_marks_refund() -> None:
    text = (
        "Payment Date,Gross,Item,Email,Payment Status\n"
        "2026-06-01,5.00,Sticker Pack,alice@example.com,Completed\n"
        "2026-06-02,5.00,Sticker Pack,bob@example.com,Refunded\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert records[0].refunded is False
    assert records[1].refunded is True


def test_type_column_refund_marks_refund() -> None:
    text = (
        "Payment Date,Gross,Item,Email,Type,Payment ID\n"
        "2026-06-01,5.00,Sticker Pack,alice@example.com,Sale,KOFI-1\n"
        "2026-06-02,5.00,Sticker Pack,bob@example.com,Refund,KOFI-2\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert records[0].refunded is False
    assert records[1].refunded is True
    assert records[1].order_id == "KOFI-2"


def test_invalid_price_row_warned_and_skipped() -> None:
    text = (
        "Payment Date,Gross,Item,Email\n"
        "2026-06-01,5.00,Sticker Pack,alice@example.com\n"
        "2026-06-02,not-a-price,Bad Item,bob@example.com\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert records[0].product == "Sticker Pack"
    assert any("Row 3" in w and "price" in w and "skipped" in w for w in warnings)


def test_missing_product_row_warned_and_skipped() -> None:
    text = (
        "Payment Date,Gross,Item,Email\n"
        "2026-06-01,5.00,Sticker Pack,alice@example.com\n"
        "2026-06-02,5.00,,bob@example.com\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert any("Row 3" in w and "product" in w and "skipped" in w for w in warnings)


def test_bad_date_row_warned_and_skipped() -> None:
    text = (
        "Payment Date,Gross,Item,Email\n"
        "not-a-date,5.00,Sticker Pack,alice@example.com\n"
    )
    records, warnings = parse(text)
    assert records == []
    assert any("date" in w and "skipped" in w for w in warnings)


def test_missing_optional_columns_defaults() -> None:
    text = (
        "Payment Date,Gross,Item\n"
        "2026-06-01,5.00,Sticker Pack\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert len(records) == 1
    assert records[0].quantity == 1
    assert records[0].customer_email is None
    assert records[0].currency == "USD"
    assert records[0].order_id == ""
    assert records[0].question is None


def test_currency_symbol_tolerated() -> None:
    text = (
        "Payment Date,Gross,Item,Email\n"
        "2026-06-01,$5.00,Sticker Pack,alice@example.com\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert records[0].price == 5.0
    assert records[0].currency == "USD"


def test_thousands_separator_in_gross() -> None:
    text = (
        "Payment Date,Gross,Item,Email\n"
        '2026-06-01,"1,250.00",Big Bundle,alice@example.com\n'
    )
    records, warnings = parse(text)
    assert warnings == []
    assert records[0].price == 1250.0


def test_case_and_whitespace_insensitive_headers() -> None:
    text = (
        "PAYMENT  DATE,GROSS,ITEM,EMAIL\n"
        "2026-06-01,5.00,Sticker Pack,alice@example.com\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert records[0].date == datetime(2026, 6, 1)
    assert records[0].product == "Sticker Pack"
    assert records[0].price == 5.0


def test_invalid_quantity_defaults_to_one() -> None:
    text = (
        "Payment Date,Gross,Item,Email,Quantity\n"
        "2026-06-01,5.00,Sticker Pack,alice@example.com,many\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert records[0].quantity == 1
    assert any("quantity" in w for w in warnings)


def test_missing_required_columns_warns() -> None:
    records, warnings = parse("Name,Age\nAlice,30\n")
    assert records == []
    assert any("required columns" in w for w in warnings)


def test_empty_csv_warns() -> None:
    records, warnings = parse("")
    assert records == []
    assert warnings and "empty" in warnings[0].lower()


def test_ragged_row_warned_and_skipped() -> None:
    text = (
        "Payment Date,Gross,Item,Email\n"
        "2026-06-01,5.00,Sticker Pack,alice@example.com\n"
        "2026-06-02,5.00\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert any("Row 3" in w and "skipped" in w for w in warnings)


def test_never_raises_on_garbage() -> None:
    for text in (
        "",
        "   ",
        "\x00\xff\xfe",
        "a,b,c\n1,2",
        "Payment Date,Gross,Item\n2026-06-01",
    ):
        records, warnings = parse(text)
        assert isinstance(records, list)
        assert isinstance(warnings, list)
        assert all(isinstance(r, SaleRecord) for r in records)
