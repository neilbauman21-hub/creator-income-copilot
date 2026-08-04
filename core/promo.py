"""Promo email generation for Creator Income Copilot.

Deterministic, template-based promo copy for the top-performing product,
built from REAL numbers in the analytics report (revenue, units, momentum).
Used by core/llm.py as the heuristic fallback when no LLM key is available.

Imports ONLY from core.models + stdlib, per the build spec.
"""
from __future__ import annotations

import json

from core.models import AnalyticsReport, ProductStats, PromoEmail


def _fmt_money(value: float) -> str:
    """Format a dollar amount for display (deterministic, no trailing junk)."""
    if abs(value - round(value)) < 0.005:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def _momentum_line(product: ProductStats) -> str:
    """One compelling sentence describing the product's momentum from real data."""
    direction = product.momentum or "flat"
    pct = abs(product.momentum_pct)
    if direction == "up":
        return (
            f"It's not slowing down either — sales are up {pct:.0f}% in the last "
            f"7 days compared to the week before."
        )
    if direction == "down":
        return (
            f"After a hot run, this week took a breather ({pct:.0f}% swing) — "
            f"which means the people who already bought are the ones who know "
            f"its value, and a fresh push is exactly what it needs."
        )
    return (
        f"It's been holding steady all week — a proven, consistent seller that "
        f"keeps showing up in customer carts."
    )


def build_promo_email(report: AnalyticsReport) -> PromoEmail:
    """Build a deterministic promo email for the report's TOP product.

    Uses real revenue, units, and momentum numbers from ``report.top_products[0]``.
    Falls back to a generic store-level email when the report has no products.

    Args:
        report: The analytics report to draw numbers from.

    Returns:
        A PromoEmail with a subject line and a 3-paragraph body.
    """
    if not report.top_products:
        revenue = _fmt_money(report.total_revenue)
        orders = report.total_orders
        subject = (
            f"Your store just did {revenue} — here's what's working"
            if orders > 0
            else "Your store is warming up — let's get those first sales"
        )
        body = (
            f"Hey creator,\n\n"
            f"Your store pulled in {revenue} across {orders} order"
            f"{'s' if orders != 1 else ''} this period. That's real traction — "
            f"proof your audience wants what you're making.\n\n"
            f"The numbers are telling a story, and the smartest next step is to "
            f"double down on what's already selling. Pick your best-performing "
            f"product and give it the spotlight: a fresh promo, a bundle, or a "
            f"limited-time offer.\n\n"
            f"Your buyers are already here and already paying. Point them at your "
            f"best work today and watch the period close even stronger."
        )
        return PromoEmail(subject=subject, body=body)

    product = report.top_products[0]
    name = product.name
    revenue = _fmt_money(product.revenue)
    units = product.units
    momentum = _momentum_line(product)

    subject = (
        f"{name} just hit {revenue} — and it's still climbing"
        if product.momentum == "up"
        else f"{name} is your {revenue} best-seller — see why"
    )

    body = (
        f"Hey creator,\n\n"
        f"{name} is quietly becoming the star of your store — {revenue} in sales "
        f"across {units} purchase{'s' if units != 1 else ''} this period. That's "
        f"not luck, that's demand: people keep choosing it, and they keep paying "
        f"for it.\n\n"
        f"{momentum} The people who bought it aren't just buyers — they're your "
        f"proof. Every new customer is another voice telling the next one "
        f"\"this is worth it.\"\n\n"
        f"So here's the play: shine the spotlight on {name} this week. Feature it "
        f"front and center, pair it with a bundle, or offer it at a launch price. "
        f"When a product has this kind of pull, your job is simple — get it in "
        f"front of more eyes and let the momentum do the rest."
    )
    return PromoEmail(subject=subject, body=body)


def build_promo_prompt(report: AnalyticsReport) -> str:
    """Build the LLM prompt for generating a promo email from the report.

    Embeds the full report as JSON so the model works from real numbers, and
    constrains the output to the PromoEmail schema (subject + 3-paragraph body).

    Args:
        report: The analytics report to embed.

    Returns:
        A system+user prompt string for the OpenRouter call.
    """
    report_json = report.model_dump_json(indent=2)
    return (
        "You are an expert email copywriter for digital-product creators. "
        "Write a short, compelling promo email for the creator's TOP-performing "
        "product, using ONLY the real numbers from the analytics report below.\n"
        "\n"
        "Rules:\n"
        "1. Output STRICT JSON matching exactly: {\"subject\": string, \"body\": string}.\n"
        "2. Subject: under 60 characters, punchy, creator-voice, no clickbait lies.\n"
        "3. Body: EXACTLY 3 short paragraphs separated by blank lines. Use real "
        "revenue, units sold, and momentum numbers from the report — never invent "
        "figures.\n"
        "4. If top_products is empty, write a generic store-level email using "
        "total_revenue and total_orders.\n"
        "5. Casual but confident creator tone. No emoji spam, no ALL CAPS, no "
        "urgency tricks that overpromise.\n"
        "\n"
        "Analytics report JSON:\n"
        f"{report_json}"
    )
