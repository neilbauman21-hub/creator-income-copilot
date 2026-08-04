"""core/insights_extra.py — deep-dive heuristic insights from analytics2 output.

Pass 2 (EXPANSION.md). ``deep_dive_insights(report, extra)`` turns the output
of ``core.analytics2`` into extra heuristic insight strings — currency
concentration risk, cohort retention warnings, anomaly explanations and the
best-selling-day insight — that ``core/report.py`` prepends to
``insights.insights`` BEFORE the LLM call, so both the LLM path and the
heuristic fallback path surface them.

Contract / bridge with core/analytics2 (written in parallel):
    report.py computes ``extra`` by calling the five analytics2 functions and
    passes the dict through. ``deep_dive_insights`` is deliberately tolerant:
    it digs through plausible key shapes, skips whatever is missing, and NEVER
    raises. If ``extra`` contains raw ``records`` instead of (or in addition to)
    pre-computed outputs, the module lazily imports ``core.analytics2`` and
    recomputes the missing pieces — that lazy import is what lets this module
    ship before analytics2.py lands.

Canonical extra keys (report.py -> deep_dive_insights), matching core/analytics2:
    currency:      {"currencies": [{"currency": "USD", "revenue": 900.0,
                                    "share_pct": 90.0}, ...],   # or code -> amount
                    "fx_normalized_total_usd": 1008.0,
                    "non_usd_pct": 10.0}                        # optional
    cohorts:       [{"cohort": "2026-05", "customers": 20,
                     "repeat_rate_pct": 5.0, "repeat_customers": 1}]
    anomalies:     [{"date": "2026-07-04", "revenue": 480.0,
                     "expected": 120.0, "z_score": 3.4,
                     "direction": "spike", "magnitude": 300.0}]
    seasonality:   {"best_day": {"day": "Saturday", "avg_revenue": 310.0},
                    "worst_day": {"day": "Monday", "avg_revenue": 90.0},
                    "day_of_week": [{"day": "Saturday", "avg_revenue": 310.0}, ...]}
    price_metrics: {...}  # computed for completeness; not turned into strings

The extractors accept several plausible aliases for every field, so the exact
key names chosen by the analytics2 module don't matter as long as the values
are recognizable.
"""
from __future__ import annotations

from core.models import AnalyticsReport

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

_LOW_REPEAT_RATE = 15.0      # cohort repeat-rate warning threshold (%)
_MIN_COHORT_CUSTOMERS = 10   # ignore tinier cohorts (noise)
_CONCENTRATION_PCT = 90.0    # single-currency dominance threshold (%)
_LOPPOSIDED_PCT = 60.0       # lopsided mix threshold (%)
_NON_USD_FX_PCT = 30.0       # FX-exposure warning threshold (%)
_WEEKEND_EDGE = 1.2          # weekday vs weekend ratio that counts as a pattern
_MAX_ANOMALY_STRINGS = 3     # cap anomaly explanations to keep the list tight


def _num(value) -> float | None:
    """Coerce a numeric value to float; None for anything non-numeric."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _money(value: float) -> str:
    """Deterministic dollar formatting (whole dollars without decimals)."""
    if abs(value - round(value)) < 0.005:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def _first(d: dict, *names, default=None):
    """Return the first present key from a list of aliases."""
    for name in names:
        if name in d:
            return d[name]
    return default


# ---------------------------------------------------------------------------
# Per-category extractors (each never raises and skips missing data)
# ---------------------------------------------------------------------------

def _currency_shares(currency: dict) -> dict[str, float]:
    """Extract {currency_code: share_pct} from plausible currency shapes."""
    shares: dict[str, float] = {}
    amounts: dict[str, float] = {}
    raw = currency.get("currencies")
    if isinstance(raw, dict):
        for code, val in raw.items():
            if isinstance(val, dict):
                share = _num(_first(val, "share_pct", "pct", "share"))
                amount = _num(_first(val, "amount", "revenue", "total", "value"))
                if share is not None:
                    shares[code] = share
                elif amount is not None:
                    amounts[code] = amount
            elif _num(val) is not None:
                amounts[code] = float(val)
    elif isinstance(raw, list):
        # analytics2's real shape: [{"currency": "USD", "revenue": ...,
        #                            "share_pct": ...}, ...]
        for item in raw:
            if not isinstance(item, dict):
                continue
            code = _first(item, "currency", "code", "name")
            if code is None:
                continue
            share = _num(_first(item, "share_pct", "pct", "share"))
            amount = _num(
                _first(item, "revenue", "amount", "fx_normalized_usd", "total", "value")
            )
            if share is not None:
                shares[str(code)] = share
            elif amount is not None:
                amounts[str(code)] = amount
    else:
        meta = {
            "total", "orders", "count", "currency_count", "total_orders",
            "total_usd", "fx_normalized_total_usd", "non_usd_pct",
            "non_usd_share_pct", "base_currency", "base", "rates",
            "fx_rates_used",
        }
        for code, val in currency.items():
            if code in meta or _num(val) is None:
                continue
            amounts[code] = float(val)
    if not shares and amounts:
        total = sum(amounts.values())
        if total > 0:
            shares = {code: amt / total * 100.0 for code, amt in amounts.items()}
    return shares


def _currency_insights(currency) -> list[str]:
    """Currency concentration risk / FX-exposure strings."""
    if not isinstance(currency, dict):
        return []
    out: list[str] = []
    shares = _currency_shares(currency)
    if shares:
        top_code, top_share = max(shares.items(), key=lambda kv: kv[1])
        if len(shares) == 1:
            if top_code != "USD":
                out.append(
                    f"All revenue is in {top_code} — your income is fully exposed "
                    f"to {top_code}/USD rate moves; consider USD pricing."
                )
        elif top_share >= _CONCENTRATION_PCT:
            out.append(
                f"Currency concentration: {top_share:.0f}% of revenue is in "
                f"{top_code} — nearly all income rides on a single currency."
            )
        elif top_share >= _LOPPOSIDED_PCT:
            out.append(
                f"Currency mix is lopsided: {top_code} carries {top_share:.0f}% "
                f"of revenue; the remaining {100.0 - top_share:.0f}% is spread "
                f"across {len(shares) - 1} other "
                f"currency{'s' if len(shares) - 1 != 1 else ''}."
            )
    non_usd = _num(_first(currency, "non_usd_pct", "non_usd_share_pct"))
    if non_usd is not None and non_usd >= _NON_USD_FX_PCT:
        out.append(
            f"{non_usd:.0f}% of revenue is non-USD — FX swings can move your "
            f"reported earnings; pricing in USD would stabilize it."
        )
    return out


def _cohort_insights(cohorts) -> list[str]:
    """Cohort retention warnings from monthly first-purchase cohorts."""
    if not isinstance(cohorts, list) or not cohorts:
        return []
    out: list[str] = []
    for idx, cohort in enumerate(cohorts):
        if not isinstance(cohort, dict):
            continue
        label = _first(cohort, "month", "cohort", "cohort_month", "period", "name")
        customers = _num(_first(cohort, "customers", "cohort_size", "new_customers", "size"))
        repeat_rate = _num(
            _first(
                cohort,
                "repeat_rate",
                "repeat_purchase_rate",
                "repeat_pct",
                "repeat_rate_pct",
            )
        )
        if repeat_rate is None:
            repeat_customers = _num(
                _first(cohort, "repeat_customers", "returning_customers")
            )
            if repeat_customers is not None and customers:
                repeat_rate = repeat_customers / customers * 100.0
        if customers is None or customers < _MIN_COHORT_CUSTOMERS:
            continue
        if repeat_rate is None or repeat_rate >= _LOW_REPEAT_RATE:
            continue
        cohort_label = str(label) if label is not None else f"cohort {idx + 1}"
        if repeat_rate <= 0.0 and idx == len(cohorts) - 1:
            out.append(
                f"Cohort {cohort_label} ({customers:.0f} customers) shows no repeat "
                f"purchases yet — still early; watch whether they return in the "
                f"next few weeks."
            )
        else:
            out.append(
                f"Cohort retention warning: {cohort_label} ({customers:.0f} "
                f"customers) repeats at only {repeat_rate:.1f}% — below the "
                f"{_LOW_REPEAT_RATE:.0f}% threshold. Plan a post-purchase "
                f"follow-up sequence."
            )
    return out


def _anomaly_insights(anomalies) -> list[str]:
    """Explain revenue anomalies (launch spikes / drops) with date + magnitude."""
    if not isinstance(anomalies, list) or not anomalies:
        return []
    out: list[str] = []
    for anomaly in anomalies[:_MAX_ANOMALY_STRINGS]:
        if not isinstance(anomaly, dict):
            continue
        date = _first(anomaly, "date", "day")
        revenue = _num(_first(anomaly, "revenue", "actual", "amount", "value"))
        expected = _num(_first(anomaly, "expected", "baseline", "avg", "average"))
        z = _num(_first(anomaly, "z_score", "zscore", "z", "sigma"))
        mag = _num(
            _first(
                anomaly,
                "magnitude",
                "magnitude_pct",
                "pct_change",
                "delta_pct",
                "change_pct",
            )
        )
        direction = _first(anomaly, "direction", "type", "kind")
        if direction is None and z is not None:
            direction = "spike" if z > 0 else "drop"
        if direction is None and revenue is not None and expected not in (None, 0.0):
            direction = "spike" if revenue > expected else "drop"
        if direction is None:
            direction = "anomaly"

        when = f" on {date}" if date else ""
        z_txt = f" (z={z:+.1f})" if z is not None else ""
        rev_txt = f"{_money(revenue)} — " if revenue is not None else ""
        if direction == "drop":
            if revenue is not None and expected not in (None, 0.0):
                drop_pct = abs((revenue - expected) / expected * 100.0)
                out.append(
                    f"Revenue anomaly{when}: {_money(revenue)} vs ~{_money(expected)} "
                    f"expected ({drop_pct:.0f}% below baseline){z_txt} — a sharp "
                    f"drop. Check for checkout failures or a refund wave."
                )
            elif mag is not None:
                out.append(
                    f"Revenue anomaly{when}: {rev_txt}about {abs(mag):.0f}% below "
                    f"the daily norm{z_txt} — a sharp drop. Check for checkout "
                    f"failures or a refund wave."
                )
            else:
                out.append(
                    f"Revenue anomaly{when}: a sharp drop{z_txt}. Investigate what "
                    f"changed that day."
                )
        elif direction == "spike":
            if revenue is not None and expected not in (None, 0.0):
                up_pct = (revenue - expected) / expected * 100.0
                out.append(
                    f"Revenue anomaly{when}: {_money(revenue)} vs ~{_money(expected)} "
                    f"expected ({up_pct:+.0f}% above baseline){z_txt} — a launch "
                    f"spike. Double down on whatever drove it."
                )
            elif mag is not None:
                out.append(
                    f"Revenue anomaly{when}: {rev_txt}about {abs(mag):.0f}% above "
                    f"the daily norm{z_txt} — a launch spike. Double down on "
                    f"whatever drove it."
                )
            else:
                out.append(
                    f"Revenue anomaly{when}: an unusually strong day{z_txt}. "
                    f"Replicate the trigger."
                )
        else:
            out.append(
                f"Revenue anomaly{when}: outside the normal daily range{z_txt}. "
                f"Worth a closer look."
            )
    return out


def _unpack_day(value):
    """best_day/worst_day may be a plain name or {'day': ..., 'avg_revenue': ...}."""
    if isinstance(value, dict):
        name = _first(value, "day", "name", "label")
        avg = _num(_first(value, "avg_revenue", "avg", "average", "revenue"))
        return name, avg
    return value, None


def _dow_averages(seasonality: dict) -> tuple[float | None, float | None]:
    """Derive weekday/weekend averages from a day_of_week list if present."""
    dow = seasonality.get("day_of_week")
    if not isinstance(dow, list):
        return None, None
    weekday_vals: list[float] = []
    weekend_vals: list[float] = []
    for entry in dow:
        if not isinstance(entry, dict):
            continue
        day = _first(entry, "day", "name", "label")
        avg = _num(_first(entry, "avg_revenue", "avg", "average", "revenue"))
        if day is None or avg is None:
            continue
        if str(day).lower() in ("saturday", "sunday"):
            weekend_vals.append(avg)
        else:
            weekday_vals.append(avg)
    weekday_avg = sum(weekday_vals) / len(weekday_vals) if weekday_vals else None
    weekend_avg = sum(weekend_vals) / len(weekend_vals) if weekend_vals else None
    return weekday_avg, weekend_avg


def _seasonality_insights(seasonality) -> list[str]:
    """Best-selling day + weekday/weekend pattern insights."""
    if not isinstance(seasonality, dict):
        return []
    out: list[str] = []
    best, best_avg = _unpack_day(
        _first(seasonality, "best_day", "best_day_name", "top_day", "best")
    )
    worst, worst_avg = _unpack_day(
        _first(seasonality, "worst_day", "worst_day_name", "bottom_day", "worst")
    )
    if best_avg is None:
        best_avg = _num(_first(seasonality, "best_day_avg", "best_avg", "best_day_average"))
    if worst_avg is None:
        worst_avg = _num(_first(seasonality, "worst_day_avg", "worst_avg", "worst_day_average"))
    weekday_avg = _num(_first(seasonality, "weekday_avg", "avg_weekday", "weekday_average"))
    weekend_avg = _num(_first(seasonality, "weekend_avg", "avg_weekend", "weekend_average"))
    if weekday_avg is None or weekend_avg is None:
        wd_avg, we_avg = _dow_averages(seasonality)
        if weekday_avg is None:
            weekday_avg = wd_avg
        if weekend_avg is None:
            weekend_avg = we_avg

    if best:
        avg_txt = f" (avg {_money(best_avg)}/day)" if best_avg is not None else ""
        out.append(
            f"Best-selling day: {best}{avg_txt} — time launches and promos around it."
        )
    if worst and worst != best:
        avg_txt = f" (avg {_money(worst_avg)}/day)" if worst_avg is not None else ""
        out.append(
            f"Slowest day: {worst}{avg_txt} — use it for quiet maintenance or A/B tests."
        )
    if (
        weekday_avg is not None
        and weekend_avg is not None
        and min(weekday_avg, weekend_avg) > 0
    ):
        if weekend_avg >= weekday_avg * _WEEKEND_EDGE:
            out.append(
                f"Weekends outperform weekdays: {_money(weekend_avg)}/day vs "
                f"{_money(weekday_avg)}/day on weekdays — run launches and promos "
                f"on weekends."
            )
        elif weekday_avg >= weekend_avg * _WEEKEND_EDGE:
            out.append(
                f"Weekdays beat weekends: {_money(weekday_avg)}/day vs "
                f"{_money(weekend_avg)}/day on weekends — your buyers shop on "
                f"workdays; push midweek promos."
            )
    return out


# ---------------------------------------------------------------------------
# Lazy analytics2 bridge
# ---------------------------------------------------------------------------

def _normalize_extra(extra: dict) -> dict:
    """Fill missing canonical keys from raw records via a lazy analytics2 import.

    ``core.analytics2`` is being written in parallel — it may not exist yet.
    Importing it lazily here (inside the function) keeps this module importable
    (and report.py green) until it lands. If ``extra`` carries raw ``records``,
    any missing analytics2 output is recomputed from them.
    """
    data = dict(extra)
    records = data.pop("records", None)
    if records is None:
        return data
    try:
        from core import analytics2
    except Exception:  # noqa: BLE001 - module not written yet
        return data
    for key, func_name in (
        ("currency", "currency_report"),
        ("cohorts", "cohort_analysis"),
        ("anomalies", "anomaly_detection"),
        ("seasonality", "seasonality"),
        ("price_metrics", "price_metrics"),
    ):
        if key in data:
            continue
        try:
            data[key] = getattr(analytics2, func_name)(records)
        except Exception:  # noqa: BLE001 - degrade per-piece, never raise
            continue
    return data


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def deep_dive_insights(report: AnalyticsReport, extra: dict) -> list[str]:
    """Turn analytics2 outputs into extra heuristic insight strings.

    Produces up to four categories — currency concentration risk, cohort
    retention warnings, anomaly explanations and the best-selling-day insight —
    prepended by ``core/report.py`` to ``insights.insights`` before the LLM
    call (so both the LLM and heuristic paths surface them).

    ``report`` is kept in the signature for API symmetry with EXPANSION.md;
    all data comes from ``extra``. Never raises: missing or malformed inputs
    simply yield fewer (or zero) strings.
    """
    if not isinstance(extra, dict):
        extra = {}
    try:
        data = _normalize_extra(extra)
        insights: list[str] = []
        insights.extend(_currency_insights(data.get("currency")))
        insights.extend(_cohort_insights(data.get("cohorts")))
        insights.extend(_anomaly_insights(data.get("anomalies")))
        insights.extend(_seasonality_insights(data.get("seasonality")))
        return insights
    except Exception:  # noqa: BLE001 - the deep dive must never break the report
        return []
