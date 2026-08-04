"""Performance regression tests for the Creator Income Copilot pipeline.

Generates a realistic 10,000-row Payhip-style sales CSV (deterministic seed)
and asserts wall-clock budgets on this machine:

    parse_csv               < 5.0s
    build_report            < 3.0s
    build_analyze_response  < 10.0s   (api_key forced to None -> heuristics)

Rationale for the bounds: the linear implementation runs in ~0.08s / ~0.01s /
~0.05s on the reference machine, so the limits leave generous headroom for
slower CI boxes while still failing hard on accidental O(n^2) regressions —
at 10,000 rows a quadratic pass is ~10^8 operations, i.e. 100x+ slower than
the linear baseline and comfortably above every bound here. A dict-aggregated,
single-pass implementation should never come close to these numbers.

Each stage is timed as the minimum of several runs (least noisy estimate);
a warmup run absorbs first-call import / regex-cache effects.
"""
from __future__ import annotations

import os
import random
import time
from datetime import datetime, timedelta

import pytest

try:  # pytest puts the project root on sys.path; standalone runs don't
    from core.analytics import build_report
    from core.parser import parse_csv
    from core.report import build_analyze_response
except ModuleNotFoundError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.analytics import build_report
    from core.parser import parse_csv
    from core.report import build_analyze_response

# ---------------------------------------------------------------------------
# Budgets (seconds). Tuned to catch O(n^2) at 10k rows, loose enough for CI.
# ---------------------------------------------------------------------------
PARSE_BUDGET_S = 5.0
REPORT_BUDGET_S = 3.0
PIPELINE_BUDGET_S = 10.0

ROWS = 10_000
SEED = 42
REPEATS = 3  # timed runs per stage; the minimum wins

# ---------------------------------------------------------------------------
# Realistic Payhip-style catalogue + buyer pool (mirrors sample_data).
# ---------------------------------------------------------------------------
_PRODUCTS = [
    ("Content Planner Pro — Notion Template", 19.00),
    ("Minimal Finance Tracker — Notion Template", 9.00),
    ("The Creator Launch Playbook — Ebook (PDF)", 9.00),
    ("Lightroom Mobile Preset Pack — 50 Presets", 14.99),
    ("Freelance Client Hub — Notion Template", 29.00),
    ("StudioNova Mega Bundle — All Templates + Ebook", 49.00),
    ("Instagram Carousel Kit — 100 Templates", 12.00),
    ("Email Newsletter Starter — 30 Swipe Files", 15.00),
    ("YouTube Thumbnail Pack — 25 Designs", 8.00),
    ("Digital Product Launch Checklist", 5.00),
]
_DOMAINS = ["gmail.com", "icloud.com", "hotmail.com", "proton.me", "hey.com", "yahoo.com", "outlook.com"]
_FIRST = ["alex", "mia", "theo", "claire", "lucas", "isla", "oscar", "zoe", "noah", "ruby", "liam", "ella", "miles", "nora", "leo"]
_LAST = ["smith", "castillo", "moreau", "hughes", "keller", "romero", "tanaka", "bennett", "rossi", "dorsey", "walsh", "patel", "silva", "graham", "foster"]
_QUESTIONS = [
    "Any discount code for buying two products at once?",
    "How do I duplicate this template in Notion? Total beginner here, sorry!",
    "Do you have a version in Spanish?",
    "Can I use this commercially for client work?",
    "Will this work with the free plan of Notion?",
    "",
    "",
    "",
]
_OID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _gen_payhip_csv(n: int = ROWS, seed: int = SEED) -> str:
    """Deterministic Payhip-style export: 10k realistic sales rows."""
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, 8, 0, 0)
    lines = ["Order ID,Order Date,Product,Price,Currency,Qty,Buyer email,Status,Buyer question"]
    for _ in range(n):
        oid = "".join(rng.choices(_OID_ALPHABET, k=10))
        day = start + timedelta(
            days=rng.randrange(0, 183),
            hours=rng.randrange(0, 24),
            minutes=rng.randrange(0, 60),
        )
        product, price = _PRODUCTS[rng.randrange(len(_PRODUCTS))]
        email = (
            f"{rng.choice(_FIRST)}.{rng.choice(_LAST)}"
            f"{rng.randrange(0, 99) or ''}@{rng.choice(_DOMAINS)}"
        )
        status = "Refunded" if rng.random() < 0.05 else "Completed"
        question = rng.choice(_QUESTIONS)
        lines.append(
            f"{oid},{day.strftime('%Y-%m-%d %H:%M:%S')},{product},{price:.2f},"
            f"USD,1,{email},{status},{question}"
        )
    return "\r\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _best_of(fn, repeats: int = REPEATS) -> tuple[float, list[float]]:
    """Run fn repeatedly, return (best time, all times) via perf_counter."""
    times: list[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times), times


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def payhip_csv() -> str:
    return _gen_payhip_csv()


@pytest.fixture(scope="module")
def parsed(payhip_csv: str) -> tuple[list, list]:
    """One reference parse shared by the report/pipeline tests."""
    records, warnings = parse_csv(payhip_csv, source_hint="payhip")
    assert len(records) == ROWS, f"expected {ROWS} records, got {len(records)}"
    assert not warnings, f"unexpected parse warnings: {warnings[:5]}"
    return records, warnings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_parse_csv_10k_rows_under_budget(payhip_csv: str) -> None:
    """parse_csv must stay linear-ish: < PARSE_BUDGET_S for 10k rows."""
    parse_csv(payhip_csv, source_hint="payhip")  # warmup (import/regex caches)

    best, all_times = _best_of(
        lambda: parse_csv(payhip_csv, source_hint="payhip")
    )
    assert best < PARSE_BUDGET_S, (
        f"parse_csv took {best:.3f}s (runs: {[f'{t:.3f}' for t in all_times]}) "
        f"— budget {PARSE_BUDGET_S}s. Likely O(n^2) row handling."
    )


def test_build_report_10k_rows_under_budget(parsed: tuple[list, list]) -> None:
    """build_report must aggregate with dicts, not quadratic scans."""
    records, _ = parsed
    build_report(records)  # warmup

    best, all_times = _best_of(lambda: build_report(records))
    assert best < REPORT_BUDGET_S, (
        f"build_report took {best:.3f}s (runs: {[f'{t:.3f}' for t in all_times]}) "
        f"— budget {REPORT_BUDGET_S}s. Likely O(n^2) aggregation."
    )

    # Sanity: report derived numbers line up with the raw input.
    report = build_report(records)
    active = [r for r in records if not r.refunded]
    assert report.total_orders == len(active)
    assert report.total_revenue > 0
    assert report.revenue_by_day  # non-empty daily series


def test_full_pipeline_10k_rows_under_budget(
    parsed: tuple[list, list], monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_analyze_response end-to-end with api_key=None (heuristics)."""
    # Force the heuristic insight path exactly as if api_key=None had been
    # passed to generate_insights (report.py reads the key from the env).
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "")

    records, warnings = parsed
    build_analyze_response(records, warnings)  # warmup

    best, all_times = _best_of(lambda: build_analyze_response(records, warnings))
    assert best < PIPELINE_BUDGET_S, (
        f"build_analyze_response took {best:.3f}s "
        f"(runs: {[f'{t:.3f}' for t in all_times]}) — budget {PIPELINE_BUDGET_S}s."
    )

    response = build_analyze_response(records, warnings)
    assert response.insights.used_fallback is True, "expected heuristic path"
    assert response.insights.insights, "expected non-empty heuristic insights"
    assert response.analytics.total_orders == sum(1 for r in records if not r.refunded)


if __name__ == "__main__":
    # Quick standalone run: python tests/test_perf.py
    csv_text = _gen_payhip_csv()
    t0 = time.perf_counter()
    records, warnings = parse_csv(csv_text, source_hint="payhip")
    print(f"parse_csv:        {time.perf_counter() - t0:.3f}s ({len(records)} records)")
    t0 = time.perf_counter()
    build_report(records)
    print(f"build_report:     {time.perf_counter() - t0:.3f}s")
    os.environ["OPENROUTER_API_KEY"] = ""
    t0 = time.perf_counter()
    build_analyze_response(records, warnings)
    print(f"build_analyze:    {time.perf_counter() - t0:.3f}s")
