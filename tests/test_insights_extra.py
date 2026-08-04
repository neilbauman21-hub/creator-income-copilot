"""Tests for core/insights_extra.py and its wiring in core/report.py.

Covers:
- ``deep_dive_insights`` turning a canonical analytics2 ``extra`` dict into
  the four heuristic insight categories (currency concentration risk, cohort
  retention warnings, anomaly explanations, best-selling-day insight) with
  hand-computed numbers;
- tolerance: empty/missing/garbage ``extra`` never raises and yields fewer
  (or zero) strings; several plausible analytics2 key shapes are accepted;
- the lazy ``core.analytics2`` import: recompute-from-records via a fake
  module, graceful degradation when analytics2 is missing;
- report.py integration: deep-dive strings are PREPENDED to
  ``insights.insights`` in both the presence and absence of analytics2.

No network calls: build_analyze_response runs keyless (heuristic path), and
the OPENROUTER_API_KEY env var is explicitly removed in the tests that touch
it so the LLM path can never fire.
"""
import sys
from datetime import datetime

import pytest

from core.insights_extra import deep_dive_insights
from core.models import AnalyticsReport, SaleRecord
from core.report import build_analyze_response


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _records() -> list[SaleRecord]:
    """Tiny 3-order dataset (all USD) used for pipeline-level tests."""
    return [
        SaleRecord(
            order_id="1", date=datetime(2026, 7, 1, 10, 0), product="Planner",
            price=25.0, currency="USD", customer_email="a@x.com",
        ),
        SaleRecord(
            order_id="2", date=datetime(2026, 7, 2, 10, 0), product="Planner",
            price=25.0, currency="USD", customer_email="a@x.com",
        ),
        SaleRecord(
            order_id="3", date=datetime(2026, 7, 3, 10, 0), product="Kit",
            price=15.0, currency="USD", customer_email="b@x.com",
        ),
    ]


def _canonical_extra() -> dict:
    """Hand-built extra dict in the canonical analytics2 shape.

    Currencies: USD $900 + EUR $100 -> USD carries exactly 90% (concentration).
    Cohorts: 2026-05 repeats at 5.0% (warning); 2026-06 latest, 0 repeats.
    Anomalies: 2026-07-04 $480 vs ~$120 expected (z=3.4) -> spike.
    Seasonality: Saturday best ($310/day); weekends $300/day vs $100 weekday.
    """
    return {
        "currency": {"currencies": {"USD": 900.0, "EUR": 100.0}, "total_usd": 1008.0},
        "cohorts": [
            {"month": "2026-05", "customers": 20, "repeat_rate": 5.0},
            {"month": "2026-06", "customers": 15, "repeat_rate": 0.0},
        ],
        "anomalies": [
            {"date": "2026-07-04", "revenue": 480.0, "expected": 120.0, "z_score": 3.4}
        ],
        "seasonality": {
            "best_day": "Saturday", "best_day_avg": 310.0,
            "weekday_avg": 100.0, "weekend_avg": 300.0,
        },
    }


class _FakeAnalytics2:
    """Stand-in for core.analytics2 with the spec'd function names."""

    def currency_report(self, records):
        return {"currencies": {"USD": 900.0, "EUR": 100.0}, "total_usd": 1008.0}

    def cohort_analysis(self, records):
        return [{"month": "2026-05", "customers": 20, "repeat_rate": 5.0}]

    def anomaly_detection(self, records):
        return [{"date": "2026-07-04", "revenue": 480.0, "expected": 120.0, "z_score": 3.4}]

    def seasonality(self, records):
        return {
            "best_day": "Saturday", "best_day_avg": 310.0,
            "weekday_avg": 100.0, "weekend_avg": 300.0,
        }

    def price_metrics(self, records):
        return {"aov_trend_pct": 12.0}


def _inject_fake_analytics2(monkeypatch) -> None:
    """Make `from core import analytics2` resolve to the fake module."""
    import core as core_pkg

    fake = _FakeAnalytics2()
    monkeypatch.setattr(core_pkg, "analytics2", fake, raising=False)
    monkeypatch.setitem(sys.modules, "core.analytics2", fake)


def _simulate_analytics2_missing(monkeypatch) -> None:
    """Force `from core import analytics2` to raise ImportError."""
    import core as core_pkg

    monkeypatch.delattr(core_pkg, "analytics2", raising=False)
    monkeypatch.setitem(sys.modules, "core.analytics2", None)


def _keyless(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# deep_dive_insights — canonical extra
# ---------------------------------------------------------------------------

def test_canonical_extra_produces_all_categories():
    out = deep_dive_insights(AnalyticsReport(), _canonical_extra())
    joined = "\n".join(out)
    # Currency concentration: USD $900 of $1000 -> 90%.
    assert "Currency concentration: 90% of revenue is in USD" in joined
    # Cohort retention: 20 customers at 5.0% repeat -> warning; newest -> note.
    assert "Cohort retention warning: 2026-05 (20 customers) repeats at only 5.0%" in joined
    assert "Cohort 2026-06 (15 customers) shows no repeat purchases yet" in joined
    # Anomaly: $480 vs ~$120 = +300% above baseline, z=+3.4 launch spike.
    assert "Revenue anomaly on 2026-07-04: $480 vs ~$120 expected (+300% above baseline)" in joined
    assert "launch spike" in joined
    # Seasonality: best day + weekend edge ($300 vs $100 = 3x).
    assert "Best-selling day: Saturday (avg $310/day)" in joined
    assert "Weekends outperform weekdays: $300/day vs $100/day on weekdays" in joined
    # Deterministic: exactly 1 + 2 + 1 + 2 = 6 strings for this input.
    assert len(out) == 6


def test_anomaly_drop_phrasing():
    extra = {
        "anomalies": [
            {"date": "2026-07-09", "revenue": 40.0, "expected": 120.0, "z_score": -2.1}
        ]
    }
    out = deep_dive_insights(AnalyticsReport(), extra)
    joined = "\n".join(out)
    assert "Revenue anomaly on 2026-07-09: $40 vs ~$120 expected (67% below baseline)" in joined
    assert "sharp drop" in joined
    assert "checkout failures or a refund wave" in joined


def test_best_and_worst_day():
    extra = {"seasonality": {"best_day": "Saturday", "worst_day": "Tuesday",
                             "best_day_avg": 310.0, "worst_day_avg": 90.0}}
    out = deep_dive_insights(AnalyticsReport(), extra)
    joined = "\n".join(out)
    assert "Best-selling day: Saturday (avg $310/day)" in joined
    assert "Slowest day: Tuesday (avg $90/day)" in joined


# ---------------------------------------------------------------------------
# deep_dive_insights — tolerance / degenerate inputs
# ---------------------------------------------------------------------------

def test_empty_and_missing_extra_yield_nothing():
    assert deep_dive_insights(AnalyticsReport(), {}) == []
    assert deep_dive_insights(AnalyticsReport(), None) == []
    assert deep_dive_insights(AnalyticsReport(), "not a dict") == []
    assert deep_dive_insights(AnalyticsReport(), [1, 2, 3]) == []


def test_missing_keys_skip_gracefully():
    out = deep_dive_insights(
        AnalyticsReport(), {"seasonality": {"best_day": "Friday"}}
    )
    assert len(out) == 1
    assert out[0] == "Best-selling day: Friday — time launches and promos around it."


def test_garbage_structures_never_raise():
    garbage = {
        "currency": ["USD", 900.0],
        "cohorts": [{"customers": "many", "repeat_rate": "low"}, "nonsense", 42],
        "anomalies": [{"date": 7}, None, "spike"],
        "seasonality": {"best_day": {"nested": True}, "weekday_avg": "x"},
    }
    out = deep_dive_insights(AnalyticsReport(), garbage)
    assert isinstance(out, list)
    assert all(isinstance(s, str) for s in out)


def test_flat_currency_shape_and_single_currency_rules():
    # Flat dict with meta keys mixed in — USD still resolves to 90%.
    flat = {"USD": 900.0, "EUR": 100.0, "total_usd": 1008.0, "base_currency": "USD"}
    out = deep_dive_insights(AnalyticsReport(), {"currency": flat})
    assert out and "Currency concentration: 90% of revenue is in USD" in out[0]

    # Single USD currency -> no risk string (no noise for typical stores).
    out = deep_dive_insights(AnalyticsReport(), {"currency": {"USD": 500.0}})
    assert out == []

    # Single non-USD currency -> FX exposure warning.
    out = deep_dive_insights(AnalyticsReport(), {"currency": {"EUR": 500.0}})
    assert out and "All revenue is in EUR" in out[0] and "EUR/USD" in out[0]


def test_non_usd_fx_threshold():
    extra = {"currency": {"currencies": {"USD": 550.0, "EUR": 450.0}, "non_usd_pct": 45.0}}
    out = deep_dive_insights(AnalyticsReport(), extra)
    assert out == [
        "45% of revenue is non-USD — FX swings can move your reported "
        "earnings; pricing in USD would stabilize it."
    ]


# ---------------------------------------------------------------------------
# Lazy analytics2 import (recompute-from-records when extra has no outputs)
# ---------------------------------------------------------------------------

def test_lazy_recompute_from_records_with_fake_analytics2(monkeypatch):
    _inject_fake_analytics2(monkeypatch)
    out = deep_dive_insights(AnalyticsReport(), {"records": _records()})
    assert out and out[0] == (
        "Currency concentration: 90% of revenue is in USD — nearly all "
        "income rides on a single currency."
    )
    # The fake's other outputs flow through the same lazy path.
    assert any("Revenue anomaly on 2026-07-04" in s for s in out)


def test_lazy_recompute_skips_when_no_records():
    # No records -> no analytics2 import attempted, no outputs needed.
    assert deep_dive_insights(AnalyticsReport(), {}) == []


# ---------------------------------------------------------------------------
# report.py integration
# ---------------------------------------------------------------------------

def test_report_prepends_deep_dive_when_analytics2_present(monkeypatch):
    _keyless(monkeypatch)
    _inject_fake_analytics2(monkeypatch)
    resp = build_analyze_response(_records(), [])
    # Deep-dive strings are PREPENDED to the heuristic insights.
    assert resp.insights.insights[0].startswith("Currency concentration")
    assert any("Revenue anomaly on 2026-07-04" in s for s in resp.insights.insights)
    assert resp.insights.used_fallback is True  # keyless -> heuristic path
    assert resp.analytics.total_orders == 3


def test_report_graceful_without_analytics2(monkeypatch):
    _keyless(monkeypatch)
    _simulate_analytics2_missing(monkeypatch)
    resp = build_analyze_response(_records(), [])
    # Unchanged behaviour: 3-6 heuristic insights, no deep-dive prepend.
    assert 3 <= len(resp.insights.insights) <= 6
    assert resp.insights.used_fallback is True
    first = resp.insights.insights[0]
    for prefix in ("Currency concentration", "Revenue anomaly", "Best-selling day", "Cohort"):
        assert not first.startswith(prefix), f"deep-dive leaked without analytics2: {first}"
    assert resp.analytics.total_orders == 3
