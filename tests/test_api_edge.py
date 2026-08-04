"""Edge-case API tests for main.py (EXPANSION.md Pass 3).

Covers the adversarial inputs the happy-path suite (test_api.py) doesn't:

1. empty CSV file upload            -> 400 (no parseable rows)
2. 6MB upload (over the 5MB cap)    -> 400 / 413
3. .exe filename upload             -> 400 (extension gate)
4. JSON body with garbage csv_text  -> 400
5. valid JSON csv_text              -> 200 + full AnalyzeResponse schema
6. 20 concurrent /api/sample/analyze -> all 200 (threads, shared TestClient)
7. mocked LLM (monkeypatched)       -> used_fallback propagates in response

Plus: GET /api/sample returns a CSV attachment with the right filename.

Never touches the network: the LLM is monkeypatched or forced into the
heuristic fallback path, and sample CSV text is read locally.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.models import LLMInsights, NextProduct, PromoEmail
from main import MAX_UPLOAD_BYTES, app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_network_llm(monkeypatch) -> None:
    """Force every real LLM call into the heuristic fallback path.

    main.py calls load_dotenv() at import, so a REAL OPENROUTER_API_KEY from
    .env lands in os.environ. Without this guard, every /api/analyze and
    /api/sample/analyze test would fire a live OpenRouter call — slow, flaky,
    token-burning, and a direct violation of EXPANSION.md's "No network calls
    in tests" rule. Patching core.llm.httpx.post to raise makes the REAL
    generate_insights() degrade via its own exception handler (the exact
    graceful path production uses), so used_fallback=True is exercised, not
    merely stubbed. Tests that install their own LLM stubs (the two below)
    are unaffected: they replace generate_insights/_call_openrouter entirely.
    """
    def _boom(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("network disabled in tests — LLM must fall back")

    monkeypatch.setattr("core.llm.httpx.post", _boom)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CSV = PROJECT_ROOT / "sample_data" / "payhip_sample.csv"

# Inline fallback fixture (Payhip-style) used only if sample_data is absent.
_INLINE_SAMPLE = (
    "Order ID,Order Date,Product,Price,Currency,Qty,Buyer email,Status,Buyer question\r\n"
    "ORD-001,2026-06-05 10:00:00,Notion Template,19.00,USD,1,buyer1@example.com,Completed,\r\n"
    "ORD-002,2026-06-06 11:00:00,Ebook PDF,9.00,USD,1,buyer2@example.com,Completed,"
    "\"Do you have a course version?\"\r\n"
)

_ANALYTICS_KEYS = (
    "period_start",
    "period_end",
    "total_revenue",
    "total_orders",
    "unique_customers",
    "avg_order_value",
    "repeat_purchase_rate",
    "top_products",
    "revenue_by_day",
    "trends",
    "churn_signals",
    "questions",
)

_INSIGHTS_KEYS = ("insights", "promo_email", "next_product", "used_fallback")


def _sample_csv_text() -> str:
    if SAMPLE_CSV.exists():
        return SAMPLE_CSV.read_text(encoding="utf-8")
    return _INLINE_SAMPLE


def _assert_analyze_schema(data: dict) -> None:
    """Assert the exact top-level and nested key sets of AnalyzeResponse."""
    assert set(data) == {"analytics", "insights", "warnings"}
    for key in _ANALYTICS_KEYS:
        assert key in data["analytics"], f"missing analytics.{key}"
    for key in _INSIGHTS_KEYS:
        assert key in data["insights"], f"missing insights.{key}"
    assert isinstance(data["warnings"], list)


# ---------------------------------------------------------------------------
# 1. Empty CSV file -> 400 (graceful rejection, no crash)
# ---------------------------------------------------------------------------

def test_empty_csv_file_returns_400() -> None:
    resp = client.post(
        "/api/analyze",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert resp.status_code == 400, resp.text
    assert "detail" in resp.json()


def test_whitespace_only_csv_file_returns_400() -> None:
    resp = client.post(
        "/api/analyze",
        files={"file": ("blank.csv", b" \r\n\r\n\t\n", "text/csv")},
    )
    assert resp.status_code == 400, resp.text


def test_empty_csv_text_json_returns_422() -> None:
    """An empty/blank csv_text is rejected at the body layer (422, not 400)."""
    resp = client.post("/api/analyze", json={"csv_text": "   "})
    assert resp.status_code == 422, resp.text
    assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# 2. 6MB file -> 400 (main.py returns 400; 413 tolerated per spec)
# ---------------------------------------------------------------------------

def test_6mb_upload_rejected() -> None:
    assert MAX_UPLOAD_BYTES == 5 * 1024 * 1024  # sanity: cap is 5MB
    big = b"x" * (6 * 1024 * 1024)  # 6MB > cap
    resp = client.post(
        "/api/analyze",
        files={"file": ("sales.csv", big, "text/csv")},
    )
    assert resp.status_code in (400, 413), resp.text
    assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# 3. Wrong content-type / .exe filename -> 400
# ---------------------------------------------------------------------------

def test_exe_filename_rejected_even_with_csv_content_type() -> None:
    """The extension gate fires regardless of the declared MIME type."""
    resp = client.post(
        "/api/analyze",
        files={"file": ("malware.exe", b"anything", "text/csv")},
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert ".exe" in detail or "exe" in detail.lower()


def test_octet_stream_csv_filename_rejected() -> None:
    resp = client.post(
        "/api/analyze",
        files={"file": ("sales.csv.exe", b"anything", "application/octet-stream")},
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# 4. JSON body with garbage csv_text -> 400
# ---------------------------------------------------------------------------

def test_json_garbage_csv_text_returns_400() -> None:
    resp = client.post("/api/analyze", json={"csv_text": "garbage"})
    assert resp.status_code == 400, resp.text
    assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# 5. Valid JSON csv_text -> 200 with correct schema
# ---------------------------------------------------------------------------

def test_json_valid_csv_text_returns_200_with_schema() -> None:
    resp = client.post("/api/analyze", json={"csv_text": _sample_csv_text()})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_analyze_schema(data)
    assert data["analytics"]["total_orders"] > 0
    assert isinstance(data["insights"]["insights"], list)
    assert isinstance(data["insights"]["used_fallback"], bool)


# ---------------------------------------------------------------------------
# 6. 20 concurrent requests to /api/sample/analyze -> all 200
# ---------------------------------------------------------------------------

def test_20_concurrent_sample_analyze_all_200() -> None:
    def _hit() -> tuple[int, dict]:
        resp = client.post("/api/sample/analyze")
        return resp.status_code, resp.json()

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: _hit(), range(20)))

    assert len(results) == 20
    for status, data in results:
        assert status == 200, f"non-200 status: {status}"
        _assert_analyze_schema(data)
        assert data["analytics"]["total_orders"] > 0


# ---------------------------------------------------------------------------
# 7. Mocked LLM -> used_fallback True propagates in the response
# ---------------------------------------------------------------------------

def test_monkeypatched_generate_insights_propagates_used_fallback(
    monkeypatch,
) -> None:
    """Stub the LLM layer entirely; its used_fallback flag must surface."""

    def _stub_generate_insights(report, api_key):  # noqa: ARG001
        return LLMInsights(
            insights=["stubbed insight from mocked LLM"],
            promo_email=PromoEmail(subject="Subj", body="Body"),
            next_product=NextProduct(name="Next", rationale="Why", evidence="How"),
            used_fallback=True,
        )

    monkeypatch.setattr("core.report.generate_insights", _stub_generate_insights)

    resp = client.post("/api/sample/analyze")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_analyze_schema(data)
    assert data["insights"]["used_fallback"] is True
    # Prove the stub (not the heuristic path) actually served the response:
    # report.py PREPENDS deep-dive insights, so the stub's string must still
    # be present among the (longer) final list.
    assert "stubbed insight from mocked LLM" in data["insights"]["insights"]


def test_llm_failure_forces_real_fallback_with_used_fallback(
    monkeypatch,
) -> None:
    """Patch the OpenRouter call to raise: generate_insights must degrade to
    the heuristic path and used_fallback=True must reach the response."""

    def _boom(report, api_key):  # noqa: ARG001
        raise RuntimeError("simulated OpenRouter outage")

    monkeypatch.setattr("core.llm._call_openrouter", _boom)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-fake-key")

    resp = client.post("/api/sample/analyze")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_analyze_schema(data)
    assert data["insights"]["used_fallback"] is True
    # Heuristic path guarantees 3-6 base insights; report.py then PREPENDS
    # deep-dive insights, so the final list is longer — assert the floor and
    # that a deterministic heuristic string actually made it through.
    assert len(data["insights"]["insights"]) >= 3
    assert any(i.startswith("Total revenue hit ") for i in data["insights"]["insights"])


# ---------------------------------------------------------------------------
# /api/sample -> CSV attachment with the correct filename
# ---------------------------------------------------------------------------

def test_sample_download_filename_and_body() -> None:
    resp = client.get("/api/sample")
    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers["content-type"]
    disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert 'filename="payhip_sample.csv"' in disposition
    body = resp.content
    assert body.startswith(b"Order ID,Order Date")
    if SAMPLE_CSV.exists():
        assert body == SAMPLE_CSV.read_bytes()  # byte-exact match
