"""Pytest fixtures: keep the test suite offline and deterministic.

The live app calls real LLM providers (OpenRouter → ZEN fallback). Tests must
never hit the network: this fixture patches ``core.report``'s insight
generation to a deterministic stand-in so every API-level test runs in
milliseconds and is unaffected by provider availability or credits.
"""
import pytest


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    """Replace LLM insight generation with a fast deterministic stand-in."""
    from core.models import LLMInsights, NextProduct, PromoEmail

    def fake_generate(report, api_key):
        top = report.top_products[0].name if report.top_products else "Top Product"
        return LLMInsights(
            insights=[
                f"{top} is your top seller at ${report.total_revenue:,.2f}.",
                f"Repeat purchase rate is {report.repeat_purchase_rate:.1f}%.",
                "Test insight three — deterministic stand-in.",
            ],
            promo_email=PromoEmail(
                subject=f"{top} — limited offer",
                body=f"Para one about {top}.\n\nPara two.\n\nPara three.",
            ),
            next_product=NextProduct(
                name="Next Product Idea",
                rationale="Deterministic test stand-in.",
                evidence="Based on customer questions in the test fixture.",
            ),
            used_fallback=True,
        )

    monkeypatch.setattr("core.report.generate_insights", fake_generate)
