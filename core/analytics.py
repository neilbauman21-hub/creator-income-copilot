"""Pure analytics computation for Creator Income Copilot.

`build_report` turns normalized `SaleRecord`s into an `AnalyticsReport`
with NO LLM / network calls — every field is derived deterministically.

Semantics (net-sales view):
* Refunded orders never contribute to revenue, order counts, units,
  customers, daily series or momentum. They only surface as
  `ProductStats.refunds` and in the `high_refund_rate` churn signal.
* Momentum windows anchor to the last date in the data: "last 7 days" is
  [period_end - 6d, period_end], "prior 7 days" is
  [period_end - 13d, period_end - 7d].
* Monetary values and percentages are rounded to 2 decimals so the
  numbers are stable and easy to assert.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from core.models import (
    AnalyticsReport,
    ChurnSignal,
    DayPoint,
    ProductStats,
    SaleRecord,
    Trend,
)

_MOMENTUM_DAYS = 7
_REFUND_RATE_THRESHOLD = 10.0
_REPEAT_RATE_THRESHOLD = 15.0
_HIGH_REFUND_RATE_PCT = 25.0
_SLOWING_HIGH_DROP_PCT = 50.0
_SLOWING_MEDIUM_DROP_PCT = 20.0


def _direction(pct: float) -> str:
    """Map a signed percentage to an up/down/flat direction string."""
    if pct > 0:
        return "up"
    if pct < 0:
        return "down"
    return "flat"


def _change_pct(last: float, prior: float) -> float:
    """Percent change of `last` vs `prior`, with defined zero handling.

    Both zero -> 0.0 (flat). Prior zero with positive last -> +100.0 so a
    product that only sold recently reads as strong "up" instead of a
    divide-by-zero.
    """
    if prior == 0.0:
        return 100.0 if last > 0.0 else 0.0
    return (last - prior) / prior * 100.0


def build_report(records: list[SaleRecord]) -> AnalyticsReport:
    """Compute the full AnalyticsReport for a list of sale records.

    Pure computation: no I/O, no LLM, no randomness. Deterministic given
    the same input list.
    """
    if not records:
        return AnalyticsReport()

    active = [r for r in records if not r.refunded]
    refunded = [r for r in records if r.refunded]

    dates = [r.date for r in records]
    start = min(dates).date()
    end = max(dates).date()
    period_start = start.isoformat()
    period_end = end.isoformat()

    # --- per-product net aggregation ---
    revenue: dict[str, float] = defaultdict(float)
    units: dict[str, int] = defaultdict(int)
    order_count: dict[str, int] = defaultdict(int)
    refund_count: dict[str, int] = defaultdict(int)
    for r in active:
        revenue[r.product] += r.price * r.quantity
        units[r.product] += r.quantity
        order_count[r.product] += 1
    for r in refunded:
        refund_count[r.product] += 1

    total_revenue = round(sum(revenue.values()), 2)
    total_orders = len(active)

    # --- customers (net orders only) ---
    email_orders: dict[str, int] = defaultdict(int)
    for r in active:
        if r.customer_email and r.customer_email.strip():
            email_orders[r.customer_email] += 1
    unique_customers = len(email_orders)
    repeat_customers = sum(1 for c in email_orders.values() if c > 1)
    repeat_rate = (
        round(repeat_customers / unique_customers * 100.0, 2)
        if unique_customers
        else 0.0
    )

    avg_order_value = round(total_revenue / total_orders, 2) if total_orders else 0.0

    # --- momentum windows anchored at period end ---
    last_start = end - timedelta(days=_MOMENTUM_DAYS - 1)
    prior_start = end - timedelta(days=2 * _MOMENTUM_DAYS - 1)
    last_rev: dict[str, float] = defaultdict(float)
    prior_rev: dict[str, float] = defaultdict(float)
    for r in active:
        d = r.date.date()
        amt = r.price * r.quantity
        if last_start <= d <= end:
            last_rev[r.product] += amt
        elif prior_start <= d < last_start:
            prior_rev[r.product] += amt

    # --- top products ranked by revenue (name tiebreak for stability) ---
    ranked = sorted(revenue.keys(), key=lambda p: (-revenue[p], p))
    top_products: list[ProductStats] = []
    for p in ranked:
        rev = round(revenue[p], 2)
        pct = round(_change_pct(last_rev[p], prior_rev[p]), 2)
        top_products.append(
            ProductStats(
                name=p,
                units=units[p],
                revenue=rev,
                share_pct=round(rev / total_revenue * 100.0, 2) if total_revenue else 0.0,
                refunds=refund_count[p],
                avg_price=round(rev / units[p], 2) if units[p] else 0.0,
                momentum=_direction(pct),
                momentum_pct=pct,
            )
        )

    # --- revenue by day (full period, chronological, zero days included) ---
    day_revenue: dict[str, float] = defaultdict(float)
    day_orders: dict[str, int] = defaultdict(int)
    for r in active:
        iso = r.date.date().isoformat()
        day_revenue[iso] += r.price * r.quantity
        day_orders[iso] += 1
    revenue_by_day: list[DayPoint] = []
    cur = start
    while cur <= end:
        iso = cur.isoformat()
        revenue_by_day.append(
            DayPoint(
                date=iso,
                revenue=round(day_revenue[iso], 2),
                orders=day_orders[iso],
            )
        )
        cur += timedelta(days=1)

    # --- trends ---
    total_last = sum(last_rev.values())
    total_prior = sum(prior_rev.values())
    overall_pct = round(_change_pct(total_last, total_prior), 2)
    trends: list[Trend] = [
        Trend(
            label="Overall revenue",
            direction=_direction(overall_pct),
            magnitude_pct=overall_pct,
            description=(
                f"Revenue was ${total_last:.2f} in the last {_MOMENTUM_DAYS} days vs "
                f"${total_prior:.2f} in the prior {_MOMENTUM_DAYS} days "
                f"({overall_pct:+.2f}%)."
            ),
        )
    ]
    for p in ranked:
        lr, pr = last_rev[p], prior_rev[p]
        pct = round(_change_pct(lr, pr), 2)
        trends.append(
            Trend(
                label=p,
                direction=_direction(pct),
                magnitude_pct=pct,
                description=(
                    f"Revenue for '{p}' was ${lr:.2f} in the last {_MOMENTUM_DAYS} days vs "
                    f"${pr:.2f} in the prior {_MOMENTUM_DAYS} days ({pct:+.2f}%)."
                ),
            )
        )

    # --- churn signals ---
    churn_signals: list[ChurnSignal] = []
    # Refund-rate signals must cover fully-refunded products too, so iterate
    # the union of products seen in active *and* refunded records.
    signal_products = sorted(
        set(ranked) | set(refund_count.keys()),
        key=lambda p: (-revenue[p], p),
    )
    for p in signal_products:
        total_p = refund_count[p] + order_count[p]
        if total_p > 0:
            rate = refund_count[p] / total_p * 100.0
            if rate > _REFUND_RATE_THRESHOLD:
                rate = round(rate, 2)
                churn_signals.append(
                    ChurnSignal(
                        product=p,
                        signal_type="high_refund_rate",
                        severity="high" if rate > _HIGH_REFUND_RATE_PCT else "medium",
                        description=(
                            f"Refund rate {rate:.2f}% ({refund_count[p]} of {total_p} orders) "
                            f"exceeds the {_REFUND_RATE_THRESHOLD:.0f}% threshold."
                        ),
                    )
                )

    if unique_customers and repeat_rate < _REPEAT_RATE_THRESHOLD:
        if repeat_rate < 5.0:
            severity = "high"
        elif repeat_rate < 10.0:
            severity = "medium"
        else:
            severity = "low"
        churn_signals.append(
            ChurnSignal(
                product="All products",
                signal_type="low_repeat_rate",
                severity=severity,
                description=(
                    f"Only {repeat_rate:.2f}% of customers made a repeat purchase "
                    f"(below the {_REPEAT_RATE_THRESHOLD:.0f}% threshold)."
                ),
            )
        )

    # slowing sales: the prior-7-day top product losing ground recently
    if total_prior > 0 and prior_rev:
        former_top = max(prior_rev, key=lambda p: (prior_rev[p], revenue[p]))
        lr, pr = last_rev[former_top], prior_rev[former_top]
        if lr < pr:
            drop = (pr - lr) / pr * 100.0
            if drop >= _SLOWING_HIGH_DROP_PCT:
                severity = "high"
            elif drop >= _SLOWING_MEDIUM_DROP_PCT:
                severity = "medium"
            else:
                severity = "low"
            churn_signals.append(
                ChurnSignal(
                    product=former_top,
                    signal_type="slowing_sales",
                    severity=severity,
                    description=(
                        f"'{former_top}' was the top product but revenue dropped from "
                        f"${pr:.2f} (prior {_MOMENTUM_DAYS} days) to ${lr:.2f} "
                        f"(last {_MOMENTUM_DAYS} days)."
                    ),
                )
            )

    # --- buyer questions (deduped, first-occurrence order) ---
    questions: list[str] = []
    seen: set[str] = set()
    for r in records:
        q = (r.question or "").strip()
        if q and q not in seen:
            seen.add(q)
            questions.append(q)

    return AnalyticsReport(
        period_start=period_start,
        period_end=period_end,
        total_revenue=total_revenue,
        total_orders=total_orders,
        unique_customers=unique_customers,
        avg_order_value=avg_order_value,
        repeat_purchase_rate=repeat_rate,
        top_products=top_products,
        revenue_by_day=revenue_by_day,
        trends=trends,
        churn_signals=churn_signals,
        questions=questions,
    )
