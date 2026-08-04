"""LLM insight generation for Creator Income Copilot.

Wave 1 (agent C). Two paths:

- ``generate_insights(report, api_key)`` — the public entry point. With no
  API key it returns the deterministic heuristic fallback immediately. With
  a key it calls the OpenRouter chat completions API and falls back to the
  heuristic on ANY failure (exception, bad status, invalid JSON).
- ``heuristic_insights(report)`` — rule-based insights built from the report
  numbers, the promo email from ``core.promo.build_promo_email`` and the
  next-product recommendation from ``core.recommender.recommend_next_product``.

The demo MUST work keyless, so the heuristic path is the safety net and is
exercised by ``tests/test_llm.py`` (which never touches the network).
"""
from __future__ import annotations

import json
import logging
import os

import httpx
from dotenv import load_dotenv

from core.models import AnalyticsReport, LLMInsights
from core.promo import build_promo_email
from core.recommender import recommend_next_product

logger = logging.getLogger(__name__)

# OpenRouter API endpoint and config (per SPEC).
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = "google/gemini-2.0-flash-001"
_TIMEOUT_SECONDS = 25.0

# Min/max number of heuristic insights per the SPEC ("3-6 insights").
_MIN_INSIGHTS = 3
_MAX_INSIGHTS = 6

# System prompt telling the model to emit EXACTLY the LLMInsights schema.
_LLM_SYSTEM_PROMPT = (
    "You are the revenue intelligence copilot for a digital-product creator. "
    "Analyze the analytics report JSON provided by the user and respond with "
    "STRICT JSON matching EXACTLY this schema (no markdown, no commentary):\n"
    '{"insights": [string, ...], '
    '"promo_email": {"subject": string, "body": string}, '
    '"next_product": {"name": string, "rationale": string, "evidence": string}}\n'
    "Rules:\n"
    "1. insights: 3-6 short, specific, data-grounded insights (revenue, orders, "
    "avg order value, repeat-purchase rate, top products, momentum, churn "
    "signals, customer questions). Never invent numbers.\n"
    "2. promo_email: a compelling promo email for the TOP product using REAL "
    "report numbers — subject (under 60 chars) and a 3-paragraph body. If "
    "top_products is empty, write a store-level email from total_revenue and "
    "total_orders.\n"
    "3. next_product: one concrete next product to build, grounded in the "
    "report (dominant category + customer questions as demand signals). "
    "Quote a real customer question in evidence when one matches.\n"
    "4. Casual, confident creator tone. No emoji spam, no ALL CAPS."
)


def _money(value: float) -> str:
    """Deterministic dollar formatting for insight strings."""
    if abs(value - round(value)) < 0.005:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def _heuristic_insight_list(report: AnalyticsReport) -> list[str]:
    """Rule-based insights (3-6) drawn from the report numbers.

    Purely deterministic: candidates are added in a fixed order from the
    report's own fields, trimmed to ``_MAX_INSIGHTS`` and padded with a
    generic observation to reach ``_MIN_INSIGHTS``.
    """
    candidates: list[str] = []

    if report.total_orders > 0:
        customers = (
            f" from {report.unique_customers} unique customer"
            f"{'s' if report.unique_customers != 1 else ''}"
        )
        candidates.append(
            f"Total revenue hit {_money(report.total_revenue)} across "
            f"{report.total_orders} order{'s' if report.total_orders != 1 else ''}"
            f"{customers} in this period."
        )
    elif report.total_revenue > 0:
        candidates.append(
            f"Total revenue reached {_money(report.total_revenue)} this period."
        )

    if report.top_products:
        top = report.top_products[0]
        candidates.append(
            f"'{top.name}' leads with {_money(top.revenue)} — "
            f"{top.share_pct:.0f}% of revenue across {top.units} "
            f"unit{'s' if top.units != 1 else ''}."
        )

    if report.avg_order_value > 0:
        candidates.append(
            f"Average order value is {_money(report.avg_order_value)}."
        )

    if report.repeat_purchase_rate > 0:
        candidates.append(
            f"{report.repeat_purchase_rate:.1f}% of customers bought more "
            f"than once — repeat buyers are a real asset to nurture."
        )

    for trend in report.trends:
        text = (trend.description or "").strip()
        if not text:
            text = (
                f"{trend.label}: trending {trend.direction} "
                f"({trend.magnitude_pct:.0f}%)."
            )
        candidates.append(text)

    for signal in report.churn_signals:
        text = (signal.description or "").strip()
        if not text:
            text = (
                f"Churn signal on '{signal.product}': {signal.signal_type} "
                f"({signal.severity} severity)."
            )
        candidates.append(text)

    if report.questions:
        candidates.append(
            f"{len(report.questions)} customer question"
            f"{'s' if len(report.questions) != 1 else ''} on record — "
            f"a direct source of what to build next."
        )

    # Trim to the spec'd maximum, then pad to the minimum if needed.
    insights = candidates[:_MAX_INSIGHTS]
    while len(insights) < _MIN_INSIGHTS:
        insights.append(
            "No sales data yet — set a baseline and check back after the "
            "first orders come in."
        )
    return insights


def heuristic_insights(report: AnalyticsReport) -> LLMInsights:
    """Deterministic rule-based insights (no LLM, no network).

    Builds 3-6 insights from the report numbers, the promo email via
    ``core.promo.build_promo_email`` and the next-product recommendation via
    ``core.recommender.recommend_next_product``. Always marks
    ``used_fallback=True``. Never raises.
    """
    return LLMInsights(
        insights=_heuristic_insight_list(report),
        promo_email=build_promo_email(report),
        next_product=recommend_next_product(report),
        used_fallback=True,
    )


def _call_openrouter(report: AnalyticsReport, api_key: str) -> LLMInsights:
    """Call OpenRouter chat completions and parse an LLMInsights response.

    Raises on any transport/status/parse problem; the caller converts every
    failure into the heuristic fallback.
    """
    payload = {
        "model": os.getenv("OPENROUTER_MODEL", _DEFAULT_MODEL),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Analytics report JSON:\n"
                    f"{report.model_dump_json(indent=2)}"
                ),
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = httpx.post(
        _OPENROUTER_URL,
        json=payload,
        headers=headers,
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    data = json.loads(content)  # raises json.JSONDecodeError on bad output
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    return LLMInsights.model_validate(data)


def generate_insights(
    report: AnalyticsReport, api_key: str | None
) -> LLMInsights:
    """Generate insights for a report, degrading gracefully to heuristics.

    With no ``api_key`` the heuristic fallback is returned immediately
    (``used_fallback=True``). With a key, OpenRouter is called; ANY failure —
    network error, non-2xx status, timeout, malformed JSON, schema mismatch —
    logs a warning and returns the heuristic fallback. Never raises.
    """
    if not api_key:
        return heuristic_insights(report)

    load_dotenv()
    try:
        return _call_openrouter(report, api_key)
    except Exception as exc:  # noqa: BLE001 - every failure degrades gracefully
        logger.warning(
            "OpenRouter insight call failed (%s: %s) — using heuristic "
            "fallback",
            type(exc).__name__,
            exc,
        )
        return heuristic_insights(report)
