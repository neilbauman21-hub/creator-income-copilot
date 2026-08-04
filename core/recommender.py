"""Deterministic next-product recommendations for Creator Income Copilot.

Wave 2 (agent F). Pure heuristics — no LLM calls. Serves as the heuristic
fallback for ``core.llm.generate_insights`` and as the guardrail/seed for the
LLM path.

Strategy (per SPEC): dominant product category (top product by revenue) plus
demand signals from ``report.questions`` via keyword matching:

- "template"            -> new template product
- "pdf"                 -> pdf product
- "pack" / "bundle"     -> bundle product
- "course" / "tutorial" -> course product
- no keyword match      -> extend the dominant product's category

If a customer question matches, it is cited verbatim as evidence. Empty
``questions`` and empty ``top_products`` are handled gracefully.

Imports ONLY from ``core.models`` and the stdlib (engineering rules).
"""
from __future__ import annotations

import json
import re

from core.models import AnalyticsReport, NextProduct, ProductStats

# Keyword -> category mapping, in SPEC priority order. The first category
# whose keyword appears in the text wins (so "template" beats "pack").
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("template", ("template",)),
    ("pdf", ("pdf",)),
    ("bundle", ("pack", "bundle")),
    ("course", ("course", "tutorial")),
]

_CATEGORY_LABELS: dict[str, str] = {
    "template": "Template",
    "pdf": "PDF Guide",
    "bundle": "Bundle",
    "course": "Course",
    "other": "Product",
}

# Suffix appended to the dominant product's base name when extending its
# category (no matching customer question).
_EXTENSION_SUFFIX: dict[str, str] = {
    "template": "Template Pack 2",
    "pdf": "PDF Guide 2",
    "bundle": "Bundle 2",
    "course": "Course 2",
    "other": "2",
}

# Phrases stripped from a product name to recover the "base" line name
# (longest-first ordering matters: "template pack" before "template").
_BASE_NOISE: tuple[str, ...] = (
    "template pack",
    "template bundle",
    "templates",
    "template",
    "pdf",
    "ebook",
    "e-book",
    "bundle",
    "pack",
    "course",
    "tutorial",
    "guide",
    "kit",
    "set",
    "collection",
)

# Question prefixes/suffixes stripped when extracting a topic from a question.
_QUESTION_PREFIXES: tuple[str, ...] = (
    "do you have",
    "do you sell",
    "do you offer",
    "do you make",
    "can you make",
    "can you create",
    "can you do",
    "could you make",
    "will you make",
    "would you make",
    "is there",
    "are there",
    "any chance of",
    "looking for",
    "what about",
    "how about",
    "i'd love",
    "id love",
    "would love",
    "i need",
    "i want",
    "have you",
    "please",
    "any",
    "need",
    "want",
)

_QUESTION_SUFFIXES: tuple[str, ...] = (
    "please",
    "thank you",
    "thanks",
    "thx",
    "for sale",
    "available",
)

_MAX_QUESTION_CITE = 140


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _detect_category(text: str) -> str:
    """Return the product category for ``text`` (SPEC keyword priority order)."""
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return category
    return "other"


def _dominant_product(report: AnalyticsReport) -> ProductStats | None:
    """Top product by revenue; ``None`` when the report has no products."""
    if not report.top_products:
        return None
    # ``max`` returns the first maximal element on ties -> deterministic.
    return max(report.top_products, key=lambda p: p.revenue)


def _base_name(product_name: str) -> str:
    """Strip category/noise words from a product name to get its base line."""
    base = product_name
    lowered = base.lower()
    for noise in sorted(_BASE_NOISE, key=len, reverse=True):
        idx = lowered.find(noise)
        if idx != -1:
            base = (base[:idx] + base[idx + len(noise):]).strip()
            lowered = base.lower()
    base = re.sub(r"\bs\b", " ", base)  # drop stray plural leftovers
    base = re.sub(r"\s+", " ", base).strip(" -–—,;:.!?()")
    return base


def _question_topic(question: str) -> str:
    """Extract a short title-case topic from a customer question.

    Returns "" when nothing usable can be extracted (caller then falls back
    to a generic product name).
    """
    topic = question.strip()
    topic = re.sub(
        r"^(hi|hello|hey|good\s+(morning|afternoon|evening))[\s,!.]*",
        "",
        topic,
        flags=re.IGNORECASE,
    )
    # Strip stacked prefixes ("do you have any ...").
    for _ in range(5):
        lowered = topic.lower()
        for prefix in _QUESTION_PREFIXES:
            if lowered.startswith(prefix):
                topic = topic[len(prefix):].strip()
                break
        else:
            break
    lowered = topic.lower()
    for article in ("a ", "an ", "the "):
        if lowered.startswith(article):
            topic = topic[len(article):].strip()
            break
    # Remove any category keyword mention (word-boundary aware, plural-safe).
    for _category, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            topic = re.sub(rf"\b{re.escape(kw)}s?\b", " ", topic, flags=re.IGNORECASE)
    topic = topic.strip()
    lowered = topic.lower()
    for connector in ("for ", "about ", "of ", "with ", "on ", "in "):
        if lowered.startswith(connector):
            topic = topic[len(connector):].strip()
            break
    lowered = topic.lower()
    for suffix in _QUESTION_SUFFIXES:
        if lowered.endswith(suffix):
            topic = topic[: len(topic) - len(suffix)].strip()
            lowered = topic.lower()
    topic = re.sub(r"\s+", " ", topic).strip(" \t-–—,;:.!?'\"()")
    return topic.title() if topic else ""


def _first_question_match(questions: list[str]) -> tuple[str, str] | None:
    """First question carrying a category keyword -> (question, category)."""
    for question in questions:
        category = _detect_category(question)
        if category != "other":
            return question, category
    return None


def _units(count: int) -> str:
    return f"{count} unit" if count == 1 else f"{count} units"


def _share(product: ProductStats, report: AnalyticsReport) -> float:
    if report.total_revenue > 0:
        return product.revenue / report.total_revenue * 100.0
    return product.share_pct


def _cite(question: str) -> str:
    """Normalize + truncate a customer question for citation."""
    question = " ".join(question.split())
    if len(question) > _MAX_QUESTION_CITE:
        return question[:_MAX_QUESTION_CITE - 1].rstrip() + "…"
    return question


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend_next_product(report: AnalyticsReport) -> NextProduct:
    """Recommend the next product to build, deterministically.

    Signals, in priority order:
    1. A customer question mentioning a category keyword (template / pdf /
       pack / bundle / course / tutorial) -> build that format, citing the
       question as evidence.
    2. Otherwise extend the dominant product's category (top product by
       revenue).
    3. Empty report (no products, no questions) -> neutral first-product
       suggestion.
    """
    dominant = _dominant_product(report)
    dominant_category = _detect_category(dominant.name) if dominant else "other"
    matched = _first_question_match(report.questions)

    # --- Signal 1: a customer question names the format to build -----------
    if matched is not None:
        question, category = matched
        topic = _question_topic(question)
        label = _CATEGORY_LABELS[category]
        name = f"{topic} {label}" if topic else f"New {label} Product"
        citation = _cite(question)
        evidence = f"A customer asked: '{citation}'"
        if dominant is not None:
            rationale = (
                f"Your best-selling category is {label.lower()} — top product "
                f"'{dominant.name}' brought in ${dominant.revenue:,.2f} across "
                f"{_units(dominant.units)} ({_share(dominant, report):.0f}% of "
                f"revenue). A customer asked: '{citation}'. That is a direct "
                f"demand signal — build '{name}' to capture it in your proven "
                f"category."
            )
        else:
            rationale = (
                f"No sales history yet, but a customer asked: '{citation}'. "
                f"That is a direct demand signal — build '{name}' to meet it."
            )
        return NextProduct(name=name, rationale=rationale, evidence=evidence)

    # --- Signal 2: extend the dominant product's category ------------------
    if dominant is not None:
        base = _base_name(dominant.name) or dominant.name
        name = f"{base} {_EXTENSION_SUFFIX[dominant_category]}".strip()
        label = _CATEGORY_LABELS[dominant_category]
        share = _share(dominant, report)
        rationale = (
            f"Your top product '{dominant.name}' drove ${dominant.revenue:,.2f} "
            f"({share:.0f}% of revenue, {_units(dominant.units)}) — "
            f"{label.lower()} is your strongest category. No customer questions "
            f"point to a new format, so extend this winning line with '{name}'."
        )
        evidence = (
            f"'{dominant.name}' generated ${dominant.revenue:,.2f} across "
            f"{_units(dominant.units)} — {share:.0f}% of total revenue. "
            f"Extend the winning category."
        )
        return NextProduct(name=name, rationale=rationale, evidence=evidence)

    # --- Signal 3: nothing to go on ---------------------------------------
    return NextProduct(
        name="New Digital Product",
        rationale=(
            "No sales history or customer questions on record yet. Start with "
            "a flagship digital product, then let buyer questions guide your "
            "next release."
        ),
        evidence=(
            "No customer questions on record yet — start with a flagship "
            "product and collect demand signals."
        ),
    )


def build_recommender_prompt(report: AnalyticsReport) -> str:
    """System/user prompt text for the LLM next-product path.

    Embeds the full report as JSON and demands a strict ``NextProduct``-shaped
    JSON answer so the LLM output can be parsed back into the model.
    """
    report_json = json.dumps(report.model_dump(), indent=2, ensure_ascii=False)
    return (
        "You are the product strategist for a digital-product seller. Based "
        "ONLY on the analytics report below, recommend the single next product "
        "the seller should build.\n\n"
        "Rules:\n"
        "- Output ONLY valid JSON matching exactly: "
        '{"name": string, "rationale": string, "evidence": string}.\n'
        "- name: a concrete, specific product name.\n"
        "- rationale: 2-3 sentences grounded in the report's numbers "
        "(revenue, units, share, momentum, churn signals).\n"
        "- evidence: quote a real customer question verbatim when one matches "
        "the recommendation; otherwise cite the top product's numbers.\n"
        "- If there are no sales or customer questions, still recommend a "
        "sensible first product for a new store.\n\n"
        f"Analytics report (JSON):\n{report_json}"
    )
