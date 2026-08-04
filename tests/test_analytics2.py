"""Tests for core/analytics2.py.

Every fixture is hand-computed and verifiable on paper:

* currency_report: 5 currencies, known FX rates -> exact mix + $77.70 total.
* cohort_analysis: 3 monthly cohorts with exact repeat rates (66.67 / 50.0).
* anomaly_detection: 9x$10 + $40 spike -> mean 13, std 9, z = +3.0 exactly;
  9x$100 + $10 drop -> mean 91, std 27, z = -3.0 exactly.
* seasonality: 14 days (2026-07-01 Wed .. 07-14 Tue), revenue 10..140 by
  day, so weekday/weekend totals and per-day averages are trivially exact.
* price_metrics: AOV halves, a Planner product discounted below 60% of its
  own median, and 3 price clusters from a 25% gap rule.
"""
from datetime import datetime

from core.analytics2 import (
    anomaly_detection,
    cohort_analysis,
    currency_report,
    price_metrics,
    seasonality,
)
from core.models import SaleRecord


def _rec(month, day, price, product="P", email=None, currency="USD",
         qty=1, refunded=False):
    return SaleRecord(
        date=datetime(2026, month, day, 12, 0),
        product=product,
        price=price,
        currency=currency,
        quantity=qty,
        customer_email=email,
        refunded=refunded,
    )


# ---------------------------------------------------------------------------
# currency_report
# ---------------------------------------------------------------------------

def test_currency_report_mix_and_fx_normalized_total():
    # 8 net orders across 5 currencies + 1 refunded EUR order (excluded).
    # Raw revenue: USD 35, EUR 15, GBP 10, CAD 10, AUD 10.
    # FX: EUR 15*1.08=16.20, GBP 10*1.27=12.70, CAD 10*0.73=7.30, AUD 10*0.65=6.50.
    records = [
        _rec(1, 1, 10.0, currency="USD"),
        _rec(1, 1, 10.0, currency="EUR"),
        _rec(2, 2, 20.0, currency="USD"),
        _rec(2, 2, 10.0, currency="GBP"),
        _rec(3, 3, 10.0, currency="CAD"),
        _rec(3, 3, 10.0, currency="AUD"),
        _rec(4, 4, 5.0, currency="USD"),
        _rec(4, 4, 5.0, currency="EUR"),
        _rec(5, 5, 10.0, currency="EUR", refunded=True),
    ]
    report = currency_report(records)
    assert report["total_orders"] == 8
    assert report["fx_normalized_total_usd"] == 77.70  # 35+16.2+12.7+7.3+6.5
    assert report["fx_rates_used"] == {
        "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "AUD": 0.65,
    }
    # revenue desc, name asc among the $10 currencies: USD, EUR, AUD, CAD, GBP
    assert [c["currency"] for c in report["currencies"]] == [
        "USD", "EUR", "AUD", "CAD", "GBP",
    ]
    usd = report["currencies"][0]
    assert usd["orders"] == 3
    assert usd["revenue"] == 35.0
    assert usd["share_pct"] == 43.75          # 35/80
    assert usd["fx_normalized_usd"] == 35.0
    eur = report["currencies"][1]
    assert eur["orders"] == 2                  # refunded EUR order excluded
    assert eur["revenue"] == 15.0
    assert eur["share_pct"] == 18.75           # 15/80
    assert eur["fx_normalized_usd"] == 16.20
    assert report["currencies"][2]["fx_normalized_usd"] == 6.50   # AUD
    assert report["currencies"][3]["fx_normalized_usd"] == 7.30   # CAD
    assert report["currencies"][4]["fx_normalized_usd"] == 12.70  # GBP
    assert sum(c["share_pct"] for c in report["currencies"]) == 100.0


def test_currency_report_unknown_currency_assumed_at_parity():
    records = [_rec(1, 1, 100.0, currency="JPY"), _rec(1, 1, 10.0)]
    report = currency_report(records)
    assert report["fx_normalized_total_usd"] == 110.0
    jpy = report["currencies"][0]              # 100 > 10, so JPY ranks first
    assert jpy["currency"] == "JPY"
    assert jpy["fx_normalized_usd"] == 100.0
    assert report["fx_rates_used"]["JPY"] == 1.0  # assumption surfaced


# ---------------------------------------------------------------------------
# cohort_analysis
# ---------------------------------------------------------------------------

def test_cohort_analysis_exact_repeat_rates():
    # a,b,c first buy in July; d,e in August; f,g in September.
    # July: a(2 orders), b(1), c(2)  -> 3 customers, 2 repeat, 5 orders
    # Aug:  d(3), e(1)               -> 2 customers, 1 repeat, 4 orders
    # Sep:  f(1), g(2)               -> 2 customers, 1 repeat, 3 orders
    # h's only order is refunded (no cohort); the None-email record is untrackable.
    records = [
        _rec(7, 1, 10.0, email="a@test.com"),
        _rec(7, 2, 10.0, email="b@test.com"),
        _rec(7, 3, 10.0, email="c@test.com"),
        _rec(7, 5, 10.0, email="c@test.com"),
        _rec(8, 2, 10.0, email="a@test.com"),
        _rec(8, 3, 10.0, email="d@test.com"),
        _rec(8, 4, 10.0, email="d@test.com"),
        _rec(8, 5, 10.0, email="e@test.com"),
        _rec(9, 1, 10.0, email="d@test.com"),
        _rec(9, 2, 10.0, email="f@test.com"),
        _rec(9, 3, 10.0, email="g@test.com"),
        _rec(10, 1, 10.0, email="g@test.com"),
        _rec(8, 10, 10.0, email="h@test.com", refunded=True),
        _rec(8, 11, 10.0, email=None),
    ]
    cohorts = cohort_analysis(records)
    assert [c["cohort"] for c in cohorts] == ["2026-07", "2026-08", "2026-09"]
    jul, aug, sep = cohorts
    assert jul["customers"] == 3 and jul["repeat_customers"] == 2
    assert jul["repeat_rate_pct"] == 66.67     # 2/3
    assert jul["avg_orders_per_customer"] == 1.67  # 5/3
    assert aug["customers"] == 2 and aug["repeat_customers"] == 1
    assert aug["repeat_rate_pct"] == 50.0      # 1/2
    assert aug["avg_orders_per_customer"] == 2.0  # 4/2
    assert sep["customers"] == 2 and sep["repeat_customers"] == 1
    assert sep["repeat_rate_pct"] == 50.0
    assert sep["avg_orders_per_customer"] == 1.5  # 3/2
    assert sum(c["customers"] for c in cohorts) == 7  # h + no-email excluded


# ---------------------------------------------------------------------------
# anomaly_detection
# ---------------------------------------------------------------------------

def test_anomaly_detection_spike_day_flagged():
    # 10-day series: nine $10 days, one $40 day.
    # mean = 13, population std = 9 -> z = (40-13)/9 = 3.0 (> 2 sigma).
    records = [_rec(7, day, 10.0) for day in range(1, 10)] + [_rec(7, 10, 40.0)]
    anomalies = anomaly_detection(records)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a["date"] == "2026-07-10"
    assert a["revenue"] == 40.0
    assert a["z_score"] == 3.0
    assert a["direction"] == "spike"
    assert a["magnitude"] == 27.0              # 40 - mean(13)


def test_anomaly_detection_drop_day_flagged():
    # 10-day series: nine $100 days, one $10 day.
    # mean = 91, population std = 27 -> z = (10-91)/27 = -3.0.
    records = [_rec(7, day, 100.0) for day in range(1, 10)] + [_rec(7, 10, 10.0)]
    anomalies = anomaly_detection(records)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a["date"] == "2026-07-10"
    assert a["z_score"] == -3.0
    assert a["direction"] == "drop"
    assert a["magnitude"] == -81.0             # 10 - mean(91)


def test_anomaly_detection_flat_series_no_flags():
    records = [_rec(7, day, 50.0) for day in range(1, 6)]  # std = 0
    assert anomaly_detection(records) == []


# ---------------------------------------------------------------------------
# seasonality
# ---------------------------------------------------------------------------

def test_seasonality_split_and_best_worst_day():
    # 2026-07-01 is a Wednesday. Revenue 10..140 by day over 14 days
    # (Wed..Tue twice). Weekday total: Mon 190, Tue 210, Wed 90, Thu 110,
    # Fri 130 = 730. Weekend total: Sat 150, Sun 170 = 320. Total 1050.
    records = [
        _rec(7, 1, 10.0), _rec(7, 2, 20.0), _rec(7, 3, 30.0),
        _rec(7, 4, 40.0), _rec(7, 5, 50.0), _rec(7, 6, 60.0),
        _rec(7, 7, 70.0), _rec(7, 8, 80.0), _rec(7, 9, 90.0),
        _rec(7, 10, 100.0), _rec(7, 11, 110.0), _rec(7, 12, 120.0),
        _rec(7, 13, 130.0), _rec(7, 14, 140.0),
        _rec(7, 13, 1000.0, refunded=True),    # excluded: Monday stays 190
    ]
    s = seasonality(records)
    assert s["weekday_revenue"] == 730.0
    assert s["weekend_revenue"] == 320.0
    assert s["weekday_share_pct"] == 69.52     # 730/1050
    assert s["weekend_share_pct"] == 30.48     # 320/1050
    assert [d["day"] for d in s["day_of_week"]] == [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday",
    ]
    assert all(d["days"] == 2 for d in s["day_of_week"])
    by_day = {d["day"]: d for d in s["day_of_week"]}
    assert by_day["Monday"]["avg_revenue"] == 95.0     # 190/2
    assert by_day["Tuesday"]["avg_revenue"] == 105.0   # 210/2
    assert by_day["Wednesday"]["avg_revenue"] == 45.0  # 90/2
    assert by_day["Thursday"]["avg_revenue"] == 55.0
    assert by_day["Friday"]["avg_revenue"] == 65.0
    assert by_day["Saturday"]["avg_revenue"] == 75.0
    assert by_day["Sunday"]["avg_revenue"] == 85.0
    assert s["best_day"] == {"day": "Tuesday", "avg_revenue": 105.0}
    assert s["worst_day"] == {"day": "Wednesday", "avg_revenue": 45.0}


# ---------------------------------------------------------------------------
# price_metrics
# ---------------------------------------------------------------------------

def test_price_metrics_aov_first_vs_second_half():
    # 8 orders at 10..80: first half AOV (10+20+30+40)/4 = 25,
    # second half (50+60+70+80)/4 = 65 -> +160%.
    records = [
        _rec(7, day, float(price), product="Item")
        for day, price in enumerate([10, 20, 30, 40, 50, 60, 70, 80], start=1)
    ]
    m = price_metrics(records)
    assert m["orders_first_half"] == 4 and m["orders_second_half"] == 4
    assert m["aov_first_half"] == 25.0
    assert m["aov_second_half"] == 65.0
    assert m["aov_change_pct"] == 160.0


def test_price_metrics_aov_odd_count_gives_first_half_extra():
    # 7 orders at 10..70: first half (10..40)/4 = 25, second (50..70)/3 = 60.
    records = [
        _rec(7, day, float(price), product="Item")
        for day, price in enumerate([10, 20, 30, 40, 50, 60, 70], start=1)
    ]
    m = price_metrics(records)
    assert m["orders_first_half"] == 4 and m["orders_second_half"] == 3
    assert m["aov_first_half"] == 25.0
    assert m["aov_second_half"] == 60.0
    assert m["aov_change_pct"] == 140.0


def test_price_metrics_discount_heavy_products():
    # Planner sells at $10 x3 then $5: median 10, 60% threshold 6 -> the
    # $5 order is a deep discount -> flagged. Ebook/Course/Solo never go
    # below 60% of their own medians (single-order products can't flag).
    records = [
        _rec(7, 1, 10.0, product="Planner"),
        _rec(7, 2, 10.0, product="Planner"),
        _rec(7, 3, 10.0, product="Planner"),
        _rec(7, 4, 5.0, product="Planner"),
        _rec(7, 1, 5.0, product="Ebook"),
        _rec(7, 2, 5.0, product="Ebook"),
        _rec(7, 3, 5.0, product="Ebook"),
        _rec(7, 4, 5.0, product="Ebook"),
        _rec(7, 5, 100.0, product="Course"),
        _rec(7, 6, 100.0, product="Course"),
        _rec(7, 7, 50.0, product="Solo"),
    ]
    flags = price_metrics(records)["discount_heavy_products"]
    assert len(flags) == 1
    assert flags[0] == {
        "product": "Planner",
        "median_price": 10.0,
        "threshold_price": 6.0,
        "discounted_orders": 1,
        "total_orders": 4,
        "discount_share_pct": 25.0,
        "lowest_price": 5.0,
    }


def test_price_metrics_price_clusters():
    # Unique prices sorted: 10, 11, 12 (within 25% of each other) -> one
    # cluster; 25, 26 -> second; 50 (> 26*1.25) -> third.
    records = [
        _rec(7, 1, 10.0, product="A"),
        _rec(7, 2, 12.0, product="A"),
        _rec(7, 3, 11.0, product="A"),
        _rec(7, 4, 25.0, product="B"),
        _rec(7, 5, 26.0, product="B"),
        _rec(7, 6, 50.0, product="C"),
    ]
    clusters = price_metrics(records)["price_clusters"]
    assert clusters == [
        {"min": 10.0, "max": 12.0, "orders": 3},
        {"min": 25.0, "max": 26.0, "orders": 2},
        {"min": 50.0, "max": 50.0, "orders": 1},
    ]


# ---------------------------------------------------------------------------
# single-record edge case (second half is empty — ZeroDivisionError guard)
# ---------------------------------------------------------------------------

def test_price_metrics_single_record_no_crash():
    # n=1: mid=1, first=[record], second=[] -> second_aov must not raise.
    records = [_rec(7, 1, 25.0, product="Solo")]
    m = price_metrics(records)
    assert m["orders_first_half"] == 1 and m["orders_second_half"] == 0
    assert m["aov_first_half"] == 25.0
    assert m["aov_second_half"] == 0.0
    assert m["aov_change_pct"] == -100.0  # _change_pct(0, 25) -> -100%


# ---------------------------------------------------------------------------
# empty input safety
# ---------------------------------------------------------------------------

def test_empty_inputs_are_safe():
    cur = currency_report([])
    assert cur["total_orders"] == 0
    assert cur["fx_normalized_total_usd"] == 0.0
    assert cur["currencies"] == []
    assert cohort_analysis([]) == []
    assert anomaly_detection([]) == []
    s = seasonality([])
    assert s["weekday_revenue"] == 0.0 and s["weekend_revenue"] == 0.0
    assert s["weekday_share_pct"] == 0.0 and s["weekend_share_pct"] == 0.0
    assert s["best_day"] is None and s["worst_day"] is None
    assert all(d["avg_revenue"] == 0.0 for d in s["day_of_week"])
    m = price_metrics([])
    assert m["aov_first_half"] == 0.0 and m["aov_second_half"] == 0.0
    assert m["aov_change_pct"] == 0.0
    assert m["discount_heavy_products"] == []
    assert m["price_clusters"] == []
