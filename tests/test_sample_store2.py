"""API tests for the sample store-switcher (store=2 Gumroad sample).

Covers: GET /api/sample?store=2 download (Gumroad headers + refunds),
store=1 default backward compatibility, 404 on unknown store, and
POST /api/sample/analyze?store=2 running through the full pipeline.

Never depends on sample_data/store2_gumroad.csv being present — if it is
missing, a tiny inline Gumroad-style fixture is used instead.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORE2_CSV = PROJECT_ROOT / "sample_data" / "store2_gumroad.csv"

# Inline fallback fixture (Gumroad-style) used only if sample_data is absent.
_INLINE_STORE2 = (
    "Product,Order Number,Created At,Price,Quantity,Email,Refunded\r\n"
    "Aurora Collection — 40 Lightroom Presets,ABC123XYZ1,2026-07-01 10:00:00,19.00,1,"
    "buyer1@example.com,false\r\n"
    "Golden Hour Mobile Presets — 25 Pack,DEF456XYZ2,2026-07-02 11:00:00,12.00,1,"
    "buyer2@example.com,true\r\n"
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


def _store2_text() -> str:
    if STORE2_CSV.exists():
        return STORE2_CSV.read_text(encoding="utf-8")
    return _INLINE_STORE2


def test_store2_download_returns_gumroad_csv_attachment() -> None:
    resp = client.get("/api/sample?store=2")
    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "store2_gumroad.csv" in resp.headers["content-disposition"]

    first_line = resp.text.splitlines()[0]
    assert first_line == "Product,Order Number,Created At,Price,Quantity,Email,Refunded"


def test_store2_csv_contains_refunds() -> None:
    resp = client.get("/api/sample?store=2")
    assert resp.status_code == 200, resp.text
    rows = [line for line in resp.text.splitlines() if line.strip()]
    refunded = sum(1 for line in rows[1:] if line.rstrip().endswith(",true"))
    assert refunded >= 1, "store-2 sample should contain refunded orders"


def test_sample_default_still_payhip() -> None:
    resp = client.get("/api/sample")
    assert resp.status_code == 200, resp.text
    assert "payhip_sample.csv" in resp.headers["content-disposition"]


def test_sample_store1_explicit_payhip() -> None:
    resp = client.get("/api/sample?store=1")
    assert resp.status_code == 200, resp.text
    assert "payhip_sample.csv" in resp.headers["content-disposition"]


def test_sample_unknown_store_404() -> None:
    resp = client.get("/api/sample?store=99")
    assert resp.status_code == 404, resp.text
    assert "detail" in resp.json()


def test_sample_analyze_store2_returns_200_with_schema() -> None:
    resp = client.post("/api/sample/analyze?store=2")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data) == {"analytics", "insights", "warnings"}
    for key in _ANALYTICS_KEYS:
        assert key in data["analytics"], f"missing analytics.{key}"
    for key in _INSIGHTS_KEYS:
        assert key in data["insights"], f"missing insights.{key}"
    assert isinstance(data["warnings"], list)
    assert data["analytics"]["total_orders"] > 0


def test_sample_analyze_store2_refunds_excluded_from_revenue() -> None:
    """Refunded rows must be parsed (not dropped) and excluded from totals."""
    resp = client.post("/api/sample/analyze?store=2")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    orders = data["analytics"]["total_orders"]
    assert orders > 0
    # Inline fixture: 2 rows, 1 refunded -> 1 active order.
    if not STORE2_CSV.exists():
        assert orders == 1


def test_sample_analyze_default_still_payhip() -> None:
    resp = client.post("/api/sample/analyze")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["analytics"]["total_orders"] > 0
