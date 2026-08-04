"""API tests for main.py (Wave 3, agent G).

Covers: sample analyze 200 + schema check, bad CSV 400, missing file 422,
plus multipart/JSON happy paths and the sample download route.

Never depends on sample_data/payhip_sample.csv being present — if it is
missing, a tiny inline fixture is used instead.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

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
    assert set(data) == {"analytics", "insights", "warnings"}
    for key in _ANALYTICS_KEYS:
        assert key in data["analytics"], f"missing analytics.{key}"
    for key in _INSIGHTS_KEYS:
        assert key in data["insights"], f"missing insights.{key}"
    assert isinstance(data["warnings"], list)


def test_sample_analyze_returns_200_with_schema() -> None:
    resp = client.post("/api/sample/analyze")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_analyze_schema(data)
    assert data["analytics"]["total_orders"] > 0


def test_upload_csv_multipart_returns_200() -> None:
    resp = client.post(
        "/api/analyze",
        files={"file": ("sales.csv", _sample_csv_text().encode("utf-8"), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_analyze_schema(data)
    assert data["analytics"]["total_orders"] > 0


def test_json_csv_text_returns_200() -> None:
    resp = client.post("/api/analyze", json={"csv_text": _sample_csv_text()})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_analyze_schema(data)
    assert data["analytics"]["total_orders"] > 0


def test_bad_csv_returns_400() -> None:
    resp = client.post(
        "/api/analyze",
        json={"csv_text": "this is not a csv at all\nstill not a csv\n"},
    )
    assert resp.status_code == 400, resp.text
    assert "detail" in resp.json()


def test_wrong_extension_returns_400() -> None:
    resp = client.post(
        "/api/analyze",
        files={"file": ("sales.exe", b"anything", "application/octet-stream")},
    )
    assert resp.status_code == 400, resp.text
    assert "detail" in resp.json()


def test_oversized_upload_returns_400() -> None:
    big = b"x" * (5 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/analyze",
        files={"file": ("sales.csv", big, "text/csv")},
    )
    assert resp.status_code == 400, resp.text
    assert "detail" in resp.json()


def test_missing_file_returns_422() -> None:
    resp = client.post("/api/analyze")
    assert resp.status_code == 422, resp.text
    assert "detail" in resp.json()


def test_missing_csv_text_returns_422() -> None:
    resp = client.post("/api/analyze", json={})
    assert resp.status_code == 422, resp.text
    assert "detail" in resp.json()


def test_sample_download_returns_csv_attachment() -> None:
    resp = client.get("/api/sample")
    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_index_serves_dashboard() -> None:
    resp = client.get("/")
    assert resp.status_code == 200, resp.text
    assert "text/html" in resp.headers["content-type"]
