"""Tests for core/analytics.py.

The main fixture is a hand-computed 13-order dataset spanning exactly two
7-day windows (2026-07-01..2026-07-14), so every number is verifiable by
hand: totals, shares, momentum, trends, churn signals, daily series.
"""
from datetime import datetime

from core.analytics import build_report
from core.models import SaleRecord


def _rec(product, day, price, email=None, qty=1, question=None, refunded=False):
    return SaleRecord(
        product=product,
        date=datetime(2026, 7, day, 12, 0),
        price=price,
        quantity=qty,
        customer_email=email,
        question=question,
        refunded=refunded,
    )


def _fixture():
    """13 orders, 2026-07-01..2026-07-14.

    Notion Planner ($10): 6 net orders = $60, 1 refund on 07-09.
      prior 7d (07-01..07-07): 07-01 x2, 07-02, 07-03 = $40
      last 7d (07-08..07-14):  07-09, 07-10            = $20
    Ebook ($5): 6 net orders = $35 (one qty-2 order), no refunds.
      prior 7d: 07-05 x2, 07-06 = $15
      last 7d:  07-08, 07-12 (qty2), 07-14 = $20
    """
    return [
        _rec("Notion Planner", 1, 10.0, "a1@test.com"),
        _rec("Notion Planner", 1, 10.0, "a1@test.com"),
        _rec("Notion Planner", 2, 10.0, "a2@test.com"),
        _rec(
            "Notion Planner", 3, 10.0, "a3@test.com",
            question="Do you have a resume template pack?",
        ),
        _rec("Notion Planner", 9, 10.0, "a1@test.com"),
        _rec("Notion Planner", 10, 10.0, "a4@test.com"),
        _rec("Notion Planner", 9, 10.0, "a5@test.com", refunded=True),
        _rec("Ebook", 5, 5.0, "b1@test.com"),
        _rec(
            "Ebook", 5, 5.0, "b2@test.com",
            question="Do you have a resume template pack?",
        ),
        _rec("Ebook", 6, 5.0, "b3@test.com"),
        _rec("Ebook", 8, 5.0, "b1@test.com"),
        _rec("Ebook", 12, 5.0, "b4@test.com", qty=2),
        _rec("Ebook", 14, 5.0, "b5@test.com", question="Is there a PDF version?"),
    ]


def test_headline_numbers():
    report = build_report(_fixture())
    assert report.period_start == "2026-07-01"
    assert report.period_end == "2026-07-14"
    assert report.total_revenue == 95.0          # 60 + 35, refund excluded
    assert report.total_orders == 12             # 13 records - 1 refund
    assert report.unique_customers == 9          # a1-a4, b1-b5
    assert report.avg_order_value == 7.92        # 95 / 12
    assert report.repeat_purchase_rate == 22.22  # 2 of 9 customers (a1, b1)


def test_top_products_ranked_by_revenue():
    report = build_report(_fixture())
    assert [p.name for p in report.top_products] == ["Notion Planner", "Ebook"]

    planner = report.top_products[0]
    assert planner.units == 6
    assert planner.revenue == 60.0
    assert planner.share_pct == 63.16            # 60/95
    assert planner.refunds == 1
    assert planner.avg_price == 10.0
    assert planner.momentum == "down"
    assert planner.momentum_pct == -50.0         # (20-40)/40

    ebook = report.top_products[1]
    assert ebook.units == 7
    assert ebook.revenue == 35.0
    assert ebook.share_pct == 36.84              # 35/95
    assert ebook.refunds == 0
    assert ebook.avg_price == 5.0
    assert ebook.momentum == "up"
    assert ebook.momentum_pct == 33.33           # (20-15)/15


def test_revenue_by_day_chronological_full_period():
    report = build_report(_fixture())
    expected = [
        ("2026-07-01", 20.0, 2),
        ("2026-07-02", 10.0, 1),
        ("2026-07-03", 10.0, 1),
        ("2026-07-04", 0.0, 0),
        ("2026-07-05", 10.0, 2),
        ("2026-07-06", 5.0, 1),
        ("2026-07-07", 0.0, 0),
        ("2026-07-08", 5.0, 1),
        ("2026-07-09", 10.0, 1),   # refunded order on 07-09 excluded
        ("2026-07-10", 10.0, 1),
        ("2026-07-11", 0.0, 0),
        ("2026-07-12", 10.0, 1),   # qty-2 ebook order
        ("2026-07-13", 0.0, 0),
        ("2026-07-14", 5.0, 1),
    ]
    got = [(d.date, d.revenue, d.orders) for d in report.revenue_by_day]
    assert got == expected


def test_trends():
    report = build_report(_fixture())
    got = [
        (t.label, t.direction, t.magnitude_pct, t.description)
        for t in report.trends
    ]
    assert got == [
        (
            "Overall revenue",
            "down",
            -27.27,  # (40-55)/55
            "Revenue was $40.00 in the last 7 days vs $55.00 in the prior 7 days (-27.27%).",
        ),
        (
            "Notion Planner",
            "down",
            -50.0,
            "Revenue for 'Notion Planner' was $20.00 in the last 7 days vs $40.00 in the prior 7 days (-50.00%).",
        ),
        (
            "Ebook",
            "up",
            33.33,
            "Revenue for 'Ebook' was $20.00 in the last 7 days vs $15.00 in the prior 7 days (+33.33%).",
        ),
    ]


def test_churn_signals():
    report = build_report(_fixture())
    got = [
        (s.product, s.signal_type, s.severity, s.description)
        for s in report.churn_signals
    ]
    assert got == [
        (
            "Notion Planner",
            "high_refund_rate",
            "medium",  # 14.29% > 10% but <= 25%
            "Refund rate 14.29% (1 of 7 orders) exceeds the 10% threshold.",
        ),
        (
            "Notion Planner",
            "slowing_sales",
            "high",  # 50% drop from prior-7 top product
            "'Notion Planner' was the top product but revenue dropped from $40.00 (prior 7 days) to $20.00 (last 7 days).",
        ),
    ]


def test_questions_deduped_in_order():
    report = build_report(_fixture())
    assert report.questions == [
        "Do you have a resume template pack?",
        "Is there a PDF version?",
    ]


def test_empty_records_returns_defaults():
    report = build_report([])
    assert report.total_revenue == 0.0
    assert report.total_orders == 0
    assert report.unique_customers == 0
    assert report.avg_order_value == 0.0
    assert report.repeat_purchase_rate == 0.0
    assert report.period_start == ""
    assert report.period_end == ""
    assert report.top_products == []
    assert report.revenue_by_day == []
    assert report.trends == []
    assert report.churn_signals == []
    assert report.questions == []


def test_low_repeat_rate_signal():
    records = [
        _rec("Sticker Pack", 1, 3.0, "c1@test.com"),
        _rec("Sticker Pack", 2, 3.0, "c2@test.com"),
        _rec("Sticker Pack", 3, 3.0, "c3@test.com"),
    ]
    report = build_report(records)
    assert report.repeat_purchase_rate == 0.0
    signals = {s.signal_type: s for s in report.churn_signals}
    assert "low_repeat_rate" in signals
    assert signals["low_repeat_rate"].product == "All products"
    assert signals["low_repeat_rate"].severity == "high"
    assert (
        signals["low_repeat_rate"].description
        == "Only 0.00% of customers made a repeat purchase (below the 15% threshold)."
    )


def test_momentum_from_zero_windows():
    records = [
        _rec("New Launch", 10, 5.0, "x1@test.com"),
        _rec("New Launch", 12, 5.0, "x1@test.com"),
        _rec("Old Thing", 1, 3.0, "y1@test.com"),
    ]
    report = build_report(records)
    stats = {p.name: p for p in report.top_products}
    assert stats["New Launch"].momentum == "up"
    assert stats["New Launch"].momentum_pct == 100.0   # prior window empty
    assert stats["Old Thing"].momentum == "down"
    assert stats["Old Thing"].momentum_pct == -100.0   # nothing in last window

    overall = report.trends[0]
    assert overall.label == "Overall revenue"
    assert overall.direction == "up"
    assert overall.magnitude_pct == 233.33             # (10-3)/3

    slowing = [s for s in report.churn_signals if s.signal_type == "slowing_sales"]
    assert len(slowing) == 1
    assert slowing[0].product == "Old Thing"
    assert slowing[0].severity == "high"


def test_all_refunded_no_crash():
    records = [
        _rec("Notion Planner", 1, 10.0, "a1@test.com", refunded=True),
        _rec("Notion Planner", 2, 10.0, "a2@test.com", refunded=True),
    ]
    report = build_report(records)
    assert report.total_revenue == 0.0
    assert report.total_orders == 0
    assert report.unique_customers == 0
    assert report.avg_order_value == 0.0
    assert report.top_products == []
    assert report.period_start == "2026-07-01"
    assert report.period_end == "2026-07-02"
    assert len(report.revenue_by_day) == 2
    assert all(d.revenue == 0.0 and d.orders == 0 for d in report.revenue_by_day)
    signals = {s.signal_type: s for s in report.churn_signals}
    assert "high_refund_rate" in signals
    assert signals["high_refund_rate"].severity == "high"
