"""Tests for core/llm.py.

Covers the keyless heuristic fallback (used_fallback=True, valid LLMInsights),
the heuristic path on a hand-built report with real numbers, graceful
handling of an empty report, and the LLM-path degradation (network error /
invalid JSON / success) — ALL fully mocked, so no test ever touches the
network.
"""
import json
import logging

import httpx
import pytest

from core.llm import generate_insights, heuristic_insights
from core.models import (
    AnalyticsReport,
    ChurnSignal,
    ProductStats,
    Trend,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _report() -> AnalyticsReport:
    """Hand-built report with real, verifiable numbers.

    Total revenue $2,450 across 98 orders from 71 unique customers; the top
    product 'Notion Life Planner' ($1,550, 63.3% share, momentum up) and a
    customer question pointing at a template product.
    """
    return AnalyticsReport(
        period_start="2026-07-01",
        period_end="2026-07-14",
        total_revenue=2450.0,
        total_orders=98,
        unique_customers=71,
        avg_order_value=25.0,
        repeat_purchase_rate=18.5,
        top_products=[
            ProductStats(
                name="Notion Life Planner",
                units=62,
                revenue=1550.0,
                share_pct=63.3,
                refunds=2,
                avg_price=25.0,
                momentum="up",
                momentum_pct=34.0,
            ),
            ProductStats(
                name="Resume Kit PDF",
                units=36,
                revenue=900.0,
                share_pct=36.7,
                refunds=0,
                avg_price=25.0,
                momentum="flat",
                momentum_pct=0.0,
            ),
        ],
        revenue_by_day=[
            {"date": "2026-07-01", "revenue": 120.0, "orders": 5},
            {"date": "2026-07-02", "revenue": 130.0, "orders": 6},
        ],
        trends=[
            Trend(
                label="Last 7 days vs prior 7",
                direction="up",
                magnitude_pct=21.0,
                description=(
                    "Revenue grew 21% week-over-week, led by Notion Life Planner."
                ),
            )
        ],
        churn_signals=[
            ChurnSignal(
                product="Notion Life Planner",
                signal_type="high_refund_rate",
                severity="medium",
                description=(
                    "Notion Life Planner refunds are 3.2% of units sold — "
                    "worth watching."
                ),
            )
        ],
        questions=["Do you have a resume template pack?"],
    )


class _FakeResponse:
    """Minimal stand-in for httpx.Response used by the mocked LLM tests."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _llm_payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


# ---------------------------------------------------------------------------
# Keyless / heuristic fallback
# ---------------------------------------------------------------------------

def test_no_key_returns_heuristic_fallback():
    insights = generate_insights(_report(), api_key=None)
    assert insights.used_fallback is True
    assert 3 <= len(insights.insights) <= 6
    assert insights.promo_email.subject
    assert insights.promo_email.body
    assert insights.next_product.name
    assert insights.next_product.rationale
    assert insights.next_product.evidence
    # Identical to calling the exported heuristic directly.
    assert insights == heuristic_insights(_report())


def test_heuristic_insights_real_numbers():
    insights = heuristic_insights(_report())
    assert insights.used_fallback is True
    joined = "\n".join(insights.insights)
    # Real report numbers must appear verbatim in the insight text.
    assert "2,450" in joined
    assert "98 orders" in joined
    assert "Notion Life Planner" in joined
    assert "1,550" in joined
    # Promo email is built from the top product's real numbers.
    assert "Notion Life Planner" in insights.promo_email.subject
    assert "1,550" in insights.promo_email.body
    # Next product comes from the customer question demand signal.
    assert insights.next_product.name == "Resume Template"
    assert "resume template pack" in insights.next_product.evidence.lower()


def test_empty_report_no_raise():
    report = AnalyticsReport()  # everything defaulted / empty
    insights = generate_insights(report, api_key=None)
    assert insights.used_fallback is True
    assert 3 <= len(insights.insights) <= 6
    assert insights.promo_email.subject  # generic store-level email
    assert insights.next_product.name  # neutral first-product suggestion
    # The keyless path must never raise even on a degenerate report.
    heuristic_insights(report)


# ---------------------------------------------------------------------------
# LLM path (fully mocked — no network)
# ---------------------------------------------------------------------------

def test_llm_network_error_falls_back(monkeypatch, caplog):
    def _boom(*args, **kwargs):
        raise httpx.ConnectError("connection refused", request=None)

    monkeypatch.setattr("core.llm.httpx.post", _boom)
    with caplog.at_level(logging.WARNING):
        insights = generate_insights(_report(), api_key="test-key")
    assert insights.used_fallback is True
    assert 3 <= len(insights.insights) <= 6
    assert any("heuristic fallback" in r.message for r in caplog.records)


def test_llm_invalid_json_falls_back(monkeypatch):
    def _bad_json(*args, **kwargs):
        return _FakeResponse(_llm_payload("this is not json"))

    monkeypatch.setattr("core.llm.httpx.post", _bad_json)
    insights = generate_insights(_report(), api_key="test-key")
    assert insights.used_fallback is True
    assert 3 <= len(insights.insights) <= 6


def test_llm_schema_mismatch_falls_back(monkeypatch):
    # Valid JSON but the wrong shape (e.g. promo_email is a string).
    def _bad_shape(*args, **kwargs):
        return _FakeResponse(
            _llm_payload(json.dumps({"promo_email": "oops", "insights": "nope"}))
        )

    monkeypatch.setattr("core.llm.httpx.post", _bad_shape)
    insights = generate_insights(_report(), api_key="test-key")
    assert insights.used_fallback is True


def test_llm_success_uses_llm_output(monkeypatch):
    captured = {}

    def _ok(*args, **kwargs):
        captured.update(kwargs)
        content = json.dumps(
            {
                "insights": ["Revenue grew 21% week over week."],
                "promo_email": {
                    "subject": "Notion Life Planner just hit $1,550",
                    "body": "Para one.\n\nPara two.\n\nPara three.",
                },
                "next_product": {
                    "name": "Resume Template",
                    "rationale": "A customer asked for it.",
                    "evidence": "A customer asked: 'Do you have a resume template pack?'",
                },
            }
        )
        return _FakeResponse(_llm_payload(content))

    monkeypatch.setattr("core.llm.httpx.post", _ok)
    insights = generate_insights(_report(), api_key="test-key")

    assert insights.used_fallback is False
    assert insights.insights == ["Revenue grew 21% week over week."]
    assert insights.promo_email.subject == "Notion Life Planner just hit $1,550"
    assert insights.next_product.name == "Resume Template"

    # Request shape per SPEC: right endpoint default model, json_object mode.
    assert captured["json"]["model"] == "google/gemini-2.0-flash-001"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 25.0
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_llm_model_from_env(monkeypatch):
    captured = {}

    def _ok(*args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            _llm_payload(
                json.dumps(
                    {
                        "insights": ["ok"],
                        "promo_email": {"subject": "s", "body": "b"},
                        "next_product": {"name": "n", "rationale": "r", "evidence": "e"},
                    }
                )
            )
        )

    monkeypatch.setattr("core.llm.httpx.post", _ok)
    monkeypatch.setenv("OPENROUTER_MODEL", "acme/test-model")
    generate_insights(_report(), api_key="test-key")
    assert captured["json"]["model"] == "acme/test-model"


def test_llm_missing_content_key_falls_back(monkeypatch):
    def _weird(*args, **kwargs):
        return _FakeResponse({"choices": [{"message": {}}]})

    monkeypatch.setattr("core.llm.httpx.post", _weird)
    insights = generate_insights(_report(), api_key="test-key")
    assert insights.used_fallback is True
