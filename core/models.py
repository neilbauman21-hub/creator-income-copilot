"""Shared data models for Creator Income Copilot.

FROZEN CONTRACT — do not modify. All modules import from here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SaleRecord(BaseModel):
    """One normalized sales row."""
    order_id: str = ""
    date: datetime
    product: str
    price: float
    currency: str = "USD"
    quantity: int = 1
    customer_email: Optional[str] = None
    question: Optional[str] = None
    refunded: bool = False
    source: str = "generic"  # "payhip" | "gumroad" | "generic"


class ProductStats(BaseModel):
    name: str
    units: int = 0
    revenue: float = 0.0
    share_pct: float = 0.0
    refunds: int = 0
    avg_price: float = 0.0
    momentum: str = "flat"  # "up" | "down" | "flat" (last 7d vs prior 7d)
    momentum_pct: float = 0.0


class DayPoint(BaseModel):
    date: str  # ISO yyyy-mm-dd
    revenue: float = 0.0
    orders: int = 0


class Trend(BaseModel):
    label: str
    direction: str = "flat"  # "up" | "down" | "flat"
    magnitude_pct: float = 0.0
    description: str = ""


class ChurnSignal(BaseModel):
    product: str
    signal_type: str  # "high_refund_rate" | "low_repeat_rate" | "slowing_sales" | "other"
    severity: str = "low"  # "low" | "medium" | "high"
    description: str = ""


class AnalyticsReport(BaseModel):
    period_start: str = ""  # ISO date
    period_end: str = ""
    total_revenue: float = 0.0
    total_orders: int = 0
    unique_customers: int = 0
    avg_order_value: float = 0.0
    repeat_purchase_rate: float = 0.0  # 0..100
    top_products: list[ProductStats] = Field(default_factory=list)
    revenue_by_day: list[DayPoint] = Field(default_factory=list)
    trends: list[Trend] = Field(default_factory=list)
    churn_signals: list[ChurnSignal] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class PromoEmail(BaseModel):
    subject: str = ""
    body: str = ""


class NextProduct(BaseModel):
    name: str = ""
    rationale: str = ""
    evidence: str = ""


class LLMInsights(BaseModel):
    insights: list[str] = Field(default_factory=list)
    promo_email: PromoEmail = Field(default_factory=PromoEmail)
    next_product: NextProduct = Field(default_factory=NextProduct)
    used_fallback: bool = False  # True when heuristic fallback served the response


class AnalyzeResponse(BaseModel):
    analytics: AnalyticsReport = Field(default_factory=AnalyticsReport)
    insights: LLMInsights = Field(default_factory=LLMInsights)
    warnings: list[str] = Field(default_factory=list)
