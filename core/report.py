"""core/report.py — orchestration: analytics -> LLM insights -> AnalyzeResponse.

Wave 2 (agent F). ``build_analyze_response`` is the ONLY entry point main.py
calls: it runs ``analytics.build_report``, then ``llm.generate_insights``
(which reads OPENROUTER_API_KEY itself via ``os.getenv`` + ``load_dotenv`` and
degrades gracefully to heuristics), and assembles the final ``AnalyzeResponse``
with warnings passthrough.

Pass 2 (EXPANSION.md): after building the report, ``analytics2`` deeper
analytics are computed over the records, ``insights_extra.deep_dive_insights``
turns them into extra heuristic strings, and those strings are PREPENDED to
``insights.insights`` — they are computed before the LLM call and prepended
after it returns, so both the LLM path and the heuristic fallback path surface
them. ``analytics2`` is imported lazily: until that module lands (parallel
agent), the deep-dive stage degrades to nothing and behaviour is unchanged.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

from core.analytics import build_report
from core.insights_extra import deep_dive_insights
from core.llm import generate_insights, heuristic_insights
from core.models import AnalyzeResponse, SaleRecord

load_dotenv()

# analytics2 output name -> analytics2 function name (Pass 2).
_ANALYTICS2_FUNCS = (
    ("currency", "currency_report"),
    ("cohorts", "cohort_analysis"),
    ("anomalies", "anomaly_detection"),
    ("seasonality", "seasonality"),
    ("price_metrics", "price_metrics"),
)


def _compute_extra(records: list[SaleRecord]) -> dict:
    """Run analytics2 deeper analytics over records, guarded per piece.

    ``core.analytics2`` is written by a parallel agent and may not exist yet —
    import it lazily so the report pipeline keeps working (without deep-dive
    insights) until it lands. Each analytics2 call is also guarded so a single
    failing function can't break the report.
    """
    try:
        from core import analytics2
    except Exception:  # noqa: BLE001 - module not written yet -> degrade
        return {}
    extra: dict = {}
    for key, func_name in _ANALYTICS2_FUNCS:
        try:
            extra[key] = getattr(analytics2, func_name)(records)
        except Exception:  # noqa: BLE001 - degrade per-piece, never raise
            continue
    return extra


def build_analyze_response(
    records: list[SaleRecord],
    warnings: list[str],
) -> AnalyzeResponse:
    """Run the full pipeline over parsed records and assemble the response.

    analytics.build_report(records) -> analytics2 deep dive -> prepend extra
    heuristic insights -> llm.generate_insights(report, api_key). The api_key
    is read from the OPENROUTER_API_KEY env var (generate_insights never
    raises — it falls back to deterministic heuristics when the key is missing
    or the LLM call fails). ``warnings`` pass through untouched.
    """
    report = build_report(records)
    deep_dive = deep_dive_insights(report, _compute_extra(records))
    insights = generate_insights(report, os.getenv("OPENROUTER_API_KEY"))
    if deep_dive:
        insights.insights = [*deep_dive, *insights.insights]
    return AnalyzeResponse(analytics=report, insights=insights, warnings=warnings)


def build_fast_response(records: list[SaleRecord], warnings: list[str]) -> AnalyzeResponse:
    """Instant path: analytics + heuristic insights, NO LLM call.

    Returns the same AnalyzeResponse shape as ``build_analyze_response`` so
    the frontend renders identically, but in a few milliseconds instead of
    seconds. The frontend then calls ``POST /api/upgrade`` with the same CSV
    to swap the heuristic insights for full LLM insights in place.
    """
    report = build_report(records)
    deep_dive = deep_dive_insights(report, _compute_extra(records))
    insights = heuristic_insights(report)
    if deep_dive:
        insights.insights = [*deep_dive, *insights.insights]
    return AnalyzeResponse(analytics=report, insights=insights, warnings=warnings)
