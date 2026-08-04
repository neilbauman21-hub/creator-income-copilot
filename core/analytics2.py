"""Deeper analytics for Creator Income Copilot (EXPANSION spec, Pass 2).

Pure computation — no I/O, no LLM, no randomness. Every function is
deterministic given the same input list of ``SaleRecord``s, so tests can
assert exact hand-computed numbers.

Shared semantics (net-sales view, inherited from core/analytics.py):
* Refunded orders never contribute to revenue, order counts, customer
  identity, daily series, or AOV. They are dropped up front.
* Monetary values, percentages and z-scores are rounded to 2 decimals.
* Every function accepts an empty list and returns its zero/empty shape.

FX note: rates are hardcoded rough mid-2026 levels with USD as base
(EUR 1.08, GBP 1.27, CAD 0.73, AUD 0.65). Unknown currencies are
assumed at parity (1.0) and surfaced in ``fx_rates_used`` so callers can
see the assumption instead of being silently misquoted.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median as _median
from statistics import pstdev

from core.analytics import _change_pct  # reuse prior-zero / flat handling
from core.models import SaleRecord

# Hardcoded rough FX rates, USD base (EXPANSION spec Pass 2).
_FX_RATES: dict[str, float] = {"EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "AUD": 0.65}
_DISCOUNT_THRESHOLD = 0.60  # price < 60% of the product's own median = discount
_ANOMALY_SIGMA = 2.0        # |z| > 2 flags a day as anomalous
_CLUSTER_GAP = 0.25         # price >25% above previous price starts a new cluster

_WEEKDAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]


def _active(records: list[SaleRecord]) -> list[SaleRecord]:
    """Net-sales view: drop refunded orders up front."""
    return [r for r in records if not r.refunded]


def currency_report(records: list[SaleRecord]) -> dict:
    """Currency mix plus an FX-normalized USD total.

    Returns::

        {
          "base_currency": "USD",
          "total_orders": int,                  # refunded orders excluded
          "fx_normalized_total_usd": float,     # sum of per-currency FX values
          "currencies": [                       # sorted by revenue desc, name asc
            {"currency", "orders", "revenue", "share_pct",
             "fx_normalized_usd"}, ...
          ],
          "fx_rates_used": {currency: rate},    # incl. USD 1.0 + unknowns at 1.0
        }
    """
    active = _active(records)
    rev_by_cur: dict[str, float] = defaultdict(float)
    orders_by_cur: dict[str, int] = defaultdict(int)
    for r in active:
        rev_by_cur[r.currency] += r.price * r.quantity
        orders_by_cur[r.currency] += 1

    raw_total = sum(rev_by_cur.values())
    rates: dict[str, float] = {"USD": 1.0}
    for cur in rev_by_cur:
        rates[cur] = _FX_RATES.get(cur, 1.0)

    rows: list[dict] = []
    fx_total = 0.0
    for cur in sorted(rev_by_cur, key=lambda c: (-rev_by_cur[c], c)):
        rev = round(rev_by_cur[cur], 2)
        fx = round(rev * rates[cur], 2)
        fx_total += fx
        rows.append(
            {
                "currency": cur,
                "orders": orders_by_cur[cur],
                "revenue": rev,
                "share_pct": round(rev / raw_total * 100.0, 2) if raw_total else 0.0,
                "fx_normalized_usd": fx,
            }
        )

    return {
        "base_currency": "USD",
        "total_orders": len(active),
        "fx_normalized_total_usd": round(fx_total, 2),
        "currencies": rows,
        "fx_rates_used": rates,
    }


def cohort_analysis(records: list[SaleRecord]) -> list[dict]:
    """Monthly first-purchase cohorts (identity via customer_email).

    Only active (non-refunded) orders count; records without a
    customer_email are ignored (no identity to track). A cohort is the
    calendar month (``YYYY-MM``) of a customer's first active order.

    Returns one dict per cohort, sorted by month ascending::

        {"cohort": "2026-07", "customers": int, "repeat_customers": int,
         "repeat_rate_pct": float, "avg_orders_per_customer": float}
    """
    active = _active(records)
    orders_by_email: dict[str, list[datetime]] = defaultdict(list)
    for r in active:
        email = (r.customer_email or "").strip()
        if email:
            orders_by_email[email].append(r.date)

    cohort_orders: dict[str, int] = defaultdict(int)
    cohort_customers: dict[str, int] = defaultdict(int)
    cohort_repeat: dict[str, int] = defaultdict(int)
    for email, dates in orders_by_email.items():
        month = min(dates).strftime("%Y-%m")
        cohort_orders[month] += len(dates)
        cohort_customers[month] += 1
        if len(dates) > 1:
            cohort_repeat[month] += 1

    cohorts: list[dict] = []
    for month in sorted(cohort_customers):  # YYYY-MM sorts chronologically
        n = cohort_customers[month]
        rp = cohort_repeat[month]
        cohorts.append(
            {
                "cohort": month,
                "customers": n,
                "repeat_customers": rp,
                "repeat_rate_pct": round(rp / n * 100.0, 2) if n else 0.0,
                "avg_orders_per_customer": round(cohort_orders[month] / n, 2)
                if n
                else 0.0,
            }
        )
    return cohorts


def anomaly_detection(records: list[SaleRecord]) -> list[dict]:
    """Day-over-day revenue z-scores; flag days with |z| > 2.

    The daily revenue series spans min..max order date with zero-filled
    gaps (same convention as core/analytics.build_report). Z-scores use
    the population standard deviation (ddof=0); a perfectly flat series
    has std 0 and yields no flags.

    Returns one dict per flagged day (chronological)::

        {"date": "2026-07-10", "revenue": float, "z_score": float,
         "direction": "spike"|"drop", "magnitude": float}   # revenue - mean
    """
    active = _active(records)
    if not active:
        return []

    dates = [r.date for r in active]
    start = min(dates).date()
    end = max(dates).date()
    day_rev: dict[str, float] = defaultdict(float)
    for r in active:
        day_rev[r.date.date().isoformat()] += r.price * r.quantity

    series: list[float] = []
    days: list[datetime] = []
    cur = start
    while cur <= end:
        series.append(day_rev[cur.isoformat()])
        days.append(cur)
        cur += timedelta(days=1)

    mean = sum(series) / len(series)
    std = pstdev(series)
    if std == 0.0:
        return []

    anomalies: list[dict] = []
    for day, rev in zip(days, series):
        z = (rev - mean) / std
        if abs(z) > _ANOMALY_SIGMA:
            anomalies.append(
                {
                    "date": day.isoformat(),
                    "revenue": round(rev, 2),
                    "z_score": round(z, 2),
                    "direction": "spike" if z > 0 else "drop",
                    "magnitude": round(rev - mean, 2),
                }
            )
    return anomalies


def seasonality(records: list[SaleRecord]) -> dict:
    """Weekday vs weekend split, day-of-week averages, best/worst day.

    Day-of-week averages are ``revenue / distinct days present`` for that
    weekday (a weekday absent from the period does not drag the average
    down). Best/worst day compare ``avg_revenue``; ties resolve to the
    earlier weekday (Monday first). Returns::

        {"weekday_revenue": float, "weekend_revenue": float,
         "weekday_share_pct": float, "weekend_share_pct": float,
         "day_of_week": [{"day", "revenue", "days", "avg_revenue"}, ... x7],
         "best_day": {"day", "avg_revenue"} | None,
         "worst_day": {"day", "avg_revenue"} | None}
    """
    active = _active(records)
    rev_by_dow: dict[int, float] = defaultdict(float)
    days_by_dow: dict[int, set[str]] = defaultdict(set)
    for r in active:
        d = r.date.date()
        rev_by_dow[d.weekday()] += r.price * r.quantity
        days_by_dow[d.weekday()].add(d.isoformat())

    rows: list[dict] = []
    for dow in range(7):
        rev = round(rev_by_dow[dow], 2)
        n_days = len(days_by_dow[dow])
        rows.append(
            {
                "day": _WEEKDAY_NAMES[dow],
                "revenue": rev,
                "days": n_days,
                "avg_revenue": round(rev / n_days, 2) if n_days else 0.0,
            }
        )

    weekday_rev = sum(rev_by_dow[i] for i in range(5))  # Mon..Fri
    weekend_rev = sum(rev_by_dow[i] for i in (5, 6))    # Sat..Sun
    total = weekday_rev + weekend_rev

    best_day = worst_day = None
    if sum(len(v) for v in days_by_dow.values()):
        best = worst = rows[0]
        for row in rows[1:]:
            if row["avg_revenue"] > best["avg_revenue"]:
                best = row
            if row["avg_revenue"] < worst["avg_revenue"]:
                worst = row
        best_day = {"day": best["day"], "avg_revenue": best["avg_revenue"]}
        worst_day = {"day": worst["day"], "avg_revenue": worst["avg_revenue"]}

    return {
        "weekday_revenue": round(weekday_rev, 2),
        "weekend_revenue": round(weekend_rev, 2),
        "weekday_share_pct": round(weekday_rev / total * 100.0, 2) if total else 0.0,
        "weekend_share_pct": round(weekend_rev / total * 100.0, 2) if total else 0.0,
        "day_of_week": rows,
        "best_day": best_day,
        "worst_day": worst_day,
    }


def price_metrics(records: list[SaleRecord]) -> dict:
    """AOV trend, discount-heavy products, and price point clusters.

    * AOV halves: active orders sorted by (date, order_id) are split by
      count — the first half gets the extra order when counts are odd.
    * Discount-heavy: a product is flagged when at least one of its unit
      prices is below 60% of the product's own median unit price (a deep
      discount / coupon sale against an otherwise consistent price).
      Single-order products can never be flagged (median == own price).
    * Clusters: unique unit prices sorted ascending; a new cluster starts
      when a price is more than 25% above the previous (smaller) price.

    Returns::

        {"orders_first_half": int, "orders_second_half": int,
         "aov_first_half": float, "aov_second_half": float,
         "aov_change_pct": float,
         "discount_heavy_products": [{"product", "median_price",
           "threshold_price", "discounted_orders", "total_orders",
           "discount_share_pct", "lowest_price"}, ...],
         "price_clusters": [{"min", "max", "orders"}, ...]}  # sorted by min
    """
    active = _active(records)
    ordered = sorted(active, key=lambda r: (r.date, r.order_id))
    n = len(ordered)

    if n:
        mid = (n + 1) // 2
        first, second = ordered[:mid], ordered[mid:]
        first_aov = sum(r.price * r.quantity for r in first) / len(first)
        second_aov = sum(r.price * r.quantity for r in second) / len(second)
        aov_change = _change_pct(second_aov, first_aov)
    else:
        mid = 0
        first_aov = second_aov = aov_change = 0.0

    # --- discount-heavy products: price < 60% of the product's median ---
    prices_by_product: dict[str, list[float]] = defaultdict(list)
    for r in active:
        prices_by_product[r.product].append(r.price)
    discounted: list[dict] = []
    for product in sorted(prices_by_product):
        prices = sorted(prices_by_product[product])
        median = _median(prices)
        threshold = median * _DISCOUNT_THRESHOLD
        below = [p for p in prices if p < threshold]
        if below:
            discounted.append(
                {
                    "product": product,
                    "median_price": round(median, 2),
                    "threshold_price": round(threshold, 2),
                    "discounted_orders": len(below),
                    "total_orders": len(prices),
                    "discount_share_pct": round(len(below) / len(prices) * 100.0, 2),
                    "lowest_price": round(below[0], 2),
                }
            )

    # --- price point clusters: >25% jump above previous price splits ---
    clusters: list[dict] = []
    for price in sorted({r.price for r in active}):
        if clusters and price <= clusters[-1]["max"] * (1.0 + _CLUSTER_GAP):
            clusters[-1]["max"] = price
            clusters[-1]["orders"] += 1
        else:
            clusters.append({"min": price, "max": price, "orders": 1})

    return {
        "orders_first_half": mid,
        "orders_second_half": n - mid,
        "aov_first_half": round(first_aov, 2),
        "aov_second_half": round(second_aov, 2),
        "aov_change_pct": round(aov_change, 2),
        "discount_heavy_products": discounted,
        "price_clusters": clusters,
    }
