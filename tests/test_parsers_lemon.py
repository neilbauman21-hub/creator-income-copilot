"""Tests for core.parsers.lemon.parse — Lemon Squeezy orders export."""
from datetime import datetime

import pytest

from core.models import SaleRecord
from core.parsers.lemon import SUPPORTED_SOURCES, parse


@pytest.fixture
def lemon_csv() -> str:
    return (
        "Order,Created,Total,Product,Email,Status\n"
        "LS-1001,2026-07-01T09:14:22.000Z,19.00,Notion Minimalist Pack,alice@example.com,paid\n"
        'LS-1002,2026-07-02 14:05:11,19.00,"Notion Minimalist Pack",bob@example.com,refunded\n'
        "LS-1003,2026-07-03T18:30:00.000Z,9.99,Ebook - Side Hustle Guide,carol@example.com,paid\n"
        "LS-1004,2026-07-04 11:00:00,9.99,Ebook - Side Hustle Guide,dave@example.com,pending\n"
        "LS-1005,2026-07-05 09:00:00,19.00,Notion Minimalist Pack,eve@example.com,partially_refunded\n"
    )


def test_supported_sources() -> None:
    assert "lemon" in SUPPORTED_SOURCES


def test_sale_record_shape(lemon_csv: str) -> None:
    records, warnings = parse(lemon_csv)
    assert warnings == []
    assert len(records) == 5
    assert isinstance(records[0], SaleRecord)
    rec = records[0]
    assert rec.order_id == "LS-1001"
    assert rec.date == datetime(2026, 7, 1, 9, 14, 22)
    assert rec.product == "Notion Minimalist Pack"
    assert rec.price == 19.0
    assert rec.currency == "USD"
    assert rec.quantity == 1
    assert rec.customer_email == "alice@example.com"
    assert rec.question is None
    assert rec.refunded is False
    assert rec.source == "lemon"


def test_iso_millisecond_and_plain_datetime_dates(lemon_csv: str) -> None:
    records, _ = parse(lemon_csv)
    assert records[0].date == datetime(2026, 7, 1, 9, 14, 22)
    assert records[1].date == datetime(2026, 7, 2, 14, 5, 11)
    assert records[3].date == datetime(2026, 7, 4, 11, 0, 0)


def test_quoted_product_with_comma(lemon_csv: str) -> None:
    records, warnings = parse(lemon_csv)
    assert warnings == []
    assert records[1].product == "Notion Minimalist Pack"


def test_refund_via_status(lemon_csv: str) -> None:
    records, _ = parse(lemon_csv)
    assert [r.refunded for r in records] == [False, True, False, False, True]


def test_pending_status_not_refunded(lemon_csv: str) -> None:
    records, _ = parse(lemon_csv)
    assert records[3].refunded is False
    assert records[3].order_id == "LS-1004"


def test_partial_refund_matches_refund(lemon_csv: str) -> None:
    records, _ = parse(lemon_csv)
    assert records[4].refunded is True


def test_negative_total_marks_refund() -> None:
    text = (
        "Order,Created,Total,Product,Email,Status\n"
        "LS-2001,2026-07-06 10:00:00,-19.00,Notion Minimalist Pack,frank@example.com,paid\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert records[0].refunded is True
    assert records[0].price == -19.0


def test_missing_optional_columns_fallback() -> None:
    text = (
        "Created,Product,Total\n"
        "2026-07-01,Notion Pack,19.00\n"
        "2026-07-02,Ebook,9.99\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert len(records) == 2
    for rec in records:
        assert rec.quantity == 1
        assert rec.customer_email is None
        assert rec.currency == "USD"
        assert rec.order_id == ""
        assert rec.refunded is False


def test_bad_date_row_warned_and_skipped() -> None:
    text = (
        "Order,Created,Total,Product,Email,Status\n"
        "LS-3001,2026-07-01 09:00:00,10.00,Good Product,a@example.com,paid\n"
        "LS-3002,not-a-date,5.00,Bad Product,b@example.com,paid\n"
        "LS-3003,2026-07-03 09:00:00,7.00,Another Product,c@example.com,paid\n"
    )
    records, warnings = parse(text)
    assert len(records) == 2
    assert records[0].product == "Good Product"
    assert records[1].product == "Another Product"
    assert any("Row 3" in w and "date" in w and "skipped" in w for w in warnings)


def test_bad_price_row_warned_and_skipped() -> None:
    text = (
        "Order,Created,Total,Product,Email,Status\n"
        "LS-4001,2026-07-01 09:00:00,10.00,Good Product,a@example.com,paid\n"
        "LS-4002,2026-07-02 09:00:00,free,Bad Product,b@example.com,paid\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert records[0].product == "Good Product"
    assert any("Row 3" in w and "price" in w and "skipped" in w for w in warnings)


def test_case_and_whitespace_insensitive_headers() -> None:
    text = (
        "ORDER,CREATED,TOTAL,PRODUCT,EMAIL,STATUS\n"
        "LS-5001,2026-07-01 09:00:00,12.50,Thing,buyer@example.com,paid\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert records[0].order_id == "LS-5001"
    assert records[0].product == "Thing"
    assert records[0].price == 12.5
    assert records[0].customer_email == "buyer@example.com"


def test_bom_and_crlf_handled() -> None:
    text = (
        "\ufeffOrder,Created,Total,Product,Email,Status\r\n"
        "LS-6001,2026-07-01 09:00:00,19.00,Notion Pack,a@example.com,paid\r\n"
    )
    records, warnings = parse(text)
    assert warnings == []
    assert len(records) == 1
    assert records[0].order_id == "LS-6001"


def test_ragged_row_warned_and_skipped() -> None:
    text = (
        "Order,Created,Total,Product,Email,Status\n"
        "LS-7001,2026-07-01 09:00:00,10.00,Product A,a@example.com,paid\n"
        "LS-7002,2026-07-02 09:00:00,Product B\n"
    )
    records, warnings = parse(text)
    assert len(records) == 1
    assert any("Row 3" in w and "skipped" in w for w in warnings)


def test_empty_csv_warns() -> None:
    records, warnings = parse("")
    assert records == []
    assert warnings and "empty" in warnings[0].lower()


def test_missing_required_columns_warns() -> None:
    records, warnings = parse("Order,Email,Status\nLS-1,a@example.com,paid\n")
    assert records == []
    assert any("required columns" in w for w in warnings)


def test_never_raises_on_garbage() -> None:
    garbage_inputs = [
        "not,a,csv,at,all\n\x00\x01\x02binary\xff\xfe\n",
        "Order,Created,Total,Product,Email,Status\n",
        "a,b,c\n1,2,3\n",
        "Order,Created,Total,Product,Email,Status\n"
        'LS-8,"2026-13-99",NaN,,x@example.com,paid\n',
        None,
        42,
        b"Order,Created,Total,Product,Email,Status\n",
    ]
    for text in garbage_inputs:
        records, warnings = parse(text)  # type: ignore[arg-type]
        assert isinstance(records, list)
        assert isinstance(warnings, list)
