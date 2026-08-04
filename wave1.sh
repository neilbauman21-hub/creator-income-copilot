#!/bin/bash
# Wave 1: spawn 3 independent hermes agents in parallel
cd ~/creator-income-copilot
mkdir -p build_logs
HERMES=~/.hermes/hermes-agent/venv/bin/hermes
PROJ=~/creator-income-copilot

# Agent A: CSV parser
nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md and $PROJ/core/models.py (the frozen data contract).
YOUR TASK: write $PROJ/core/parser.py and $PROJ/tests/test_parser.py exactly per the SPEC 'core/parser.py' section. Implement parse_csv(text, source_hint=None) -> (list[SaleRecord], list[str]) with auto-detection of Payhip/Gumroad/generic CSV schemas, synonym-based case-insensitive header matching, warning (never crash) on bad rows, refund detection, question capture.
THEN: write thorough pytest tests (payhip fixture, gumroad fixture, generic fixture, missing-column fallback, bad-date row warned+skipped, refund detection).
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_parser.py -q — iterate until green.
Do NOT modify core/models.py. Do NOT create files outside your assignment. Report: files written + final pytest output." -t terminal,file --source hackathon-wave1 > build_logs/wave1_parser.log 2>&1 &

# Agent B: analytics engine
nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md and $PROJ/core/models.py (the frozen data contract).
YOUR TASK: write $PROJ/core/analytics.py and $PROJ/tests/test_analytics.py exactly per the SPEC 'core/analytics.py' section. Implement build_report(records) -> AnalyticsReport as PURE computation (NO LLM calls): total_revenue, total_orders, unique_customers, avg_order_value, repeat_purchase_rate (0..100), period_start/end, top_products ranked by revenue (units, share_pct, refunds, avg_price, momentum up/down/flat + momentum_pct comparing last 7 days vs prior 7 days), revenue_by_day chronological ISO dates, trends (overall revenue last-7 vs prior-7, per-product momentum, label/direction/magnitude_pct/description), churn_signals (high_refund_rate >10%, low_repeat_rate <15%, slowing_sales on formerly top product), questions list.
THEN: write pytest tests with a small hand-computed fixture asserting EXACT numbers.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_analytics.py -q — iterate until green.
Do NOT modify core/models.py. Do NOT create files outside your assignment. Report: files written + final pytest output." -t terminal,file --source hackathon-wave1 > build_logs/wave1_analytics.log 2>&1 &

# Agent C: promo email templates
nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md and $PROJ/core/models.py (the frozen data contract).
YOUR TASK: write $PROJ/core/promo.py exactly per the SPEC 'core/promo.py' section. Implement build_promo_email(report: AnalyticsReport) -> PromoEmail (deterministic template-based promo email for the TOP product using REAL numbers from the report: revenue, units, momentum. Subject line + 3 short paragraphs, compelling creator-style copy) and build_promo_prompt(report) -> str (prompt text for the LLM path telling the model exactly what to generate, embedding the report JSON). Import ONLY from core.models + stdlib. Handle empty top_products gracefully (generic email).
VERIFY: write a quick inline sanity check with .venv/bin/python -c importing core.promo, constructing a small AnalyticsReport with top_products, and printing the email — confirm it works. Example: cd $PROJ && .venv/bin/python -c \"from core.promo import build_promo_email; from core.models import AnalyticsReport, ProductStats; r=AnalyticsReport(total_revenue=1200.0, total_orders=60, top_products=[ProductStats(name='Notion Template Pack', revenue=500.0, units=25, share_pct=41.7, avg_price=20.0, momentum='up', momentum_pct=18.5)]); e=build_promo_email(r); print(e.subject); print(e.body[:200])\"
Do NOT modify core/models.py. Do NOT create files outside your assignment. Report: files written + sanity check output." -t terminal,file --source hackathon-wave1 > build_logs/wave1_promo.log 2>&1 &

echo "Wave 1 spawned: 3 agents (parser, analytics, promo)"
