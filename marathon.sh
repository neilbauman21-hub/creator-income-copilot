#!/bin/bash
# MARATHON ORCHESTRATOR — runs after foundation (orchestrator.sh) completes.
# Pass 2: data depth (6 parsers + analytics2 + insights_extra)
# Pass 3: test depth (fuzz, all-parsers, api edge)
# Pass 4: frontend depth (responsive, store switcher, sample store 2)
# Pass 5: docs + security + perf swarm
# Pass 6: deploy + github
cd ~/creator-income-copilot
HERMES=~/.hermes/hermes-agent/venv/bin/hermes
PROJ=~/creator-income-copilot
LOG=build_logs/marathon.log

log() { echo "[$(date +%H:%M:%S)] $1" | tee -a $LOG; }

wait_for_agents() {
  local label="$1"
  log "Waiting for $label..."
  while pgrep -f "hermes chat -q" > /dev/null 2>&1; do sleep 15; done
  log "$label done."
}

# ============ PASS 2: Data depth ============
log "=== PASS 2: data depth ==="
mkdir -p core/parsers
touch core/parsers/__init__.py

nohup $HERMES chat -q "You are a coding subagent for the 'Creator Income Copilot' project at $PROJ. FIRST read $PROJ/EXPANSION.md, $PROJ/SPEC.md, $PROJ/core/models.py, and $PROJ/core/parser.py (the existing Payhip/Gumroad/generic parser — match its style).
YOUR TASK: write $PROJ/core/parsers/shopify.py implementing parse(text) -> (list[SaleRecord], list[str]) for Shopify orders exports. Shopify columns: 'Name' (order id, e.g. #1001), 'Created at' (e.g. 2026-06-01 14:32:00 -0400), 'Total' (e.g. 29.00), 'Lineitem quantity', 'Lineitem name', 'Financial status' (paid/refunded/voided), 'Email' (customer). Refunded when status contains 'refund'. Price = Total/quantity when qty>1. Same synonym/whitespace handling style as core/parser.py. NEVER raise — warn+skip bad rows. Write $PROJ/tests/test_parsers_shopify.py with a realistic fixture and exact assertions.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_parsers_shopify.py -q — green.
Do NOT modify core/parser.py or core/models.py. Report: files + test output." -t terminal,file --source marathon-pass2 > build_logs/pass2_shopify.log 2>&1 &

nohup $HERMES chat -q "You are a coding subagent for the 'Creator Income Copilot' project at $PROJ. FIRST read $PROJ/EXPANSION.md, $PROJ/core/models.py, and $PROJ/core/parser.py (match its style).
YOUR TASK: write $PROJ/core/parsers/ko_fi.py implementing parse(text) -> (list[SaleRecord], list[str]) for Ko-fi payment exports. Ko-fi columns: 'Payment Date' (e.g. 2026-06-01), 'Gross' (e.g. 5.00), 'Item' (product name), 'Email' or 'Buyer'. Quantity defaults 1. Same style as core/parser.py. NEVER raise. Write $PROJ/tests/test_parsers_kofi.py with fixture + exact assertions.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_parsers_kofi.py -q — green.
Do NOT modify core/parser.py or core/models.py. Report: files + test output." -t terminal,file --source marathon-pass2 > build_logs/pass2_kofi.log 2>&1 &

nohup $HERMES chat -q "You are a coding subagent for the 'Creator Income Copilot' project at $PROJ. FIRST read $PROJ/EXPANSION.md, $PROJ/core/models.py, and $PROJ/core/parser.py (match its style).
YOUR TASK: write $PROJ/core/parsers/lemon.py implementing parse(text) -> (list[SaleRecord], list[str]) for Lemon Squeezy orders. Columns: 'Order' (id), 'Created' (date), 'Total' (e.g. 19.00), 'Product', 'Email', 'Status' (paid/refunded/pending — refunded when contains 'refund'). Same style as core/parser.py. NEVER raise. Write $PROJ/tests/test_parsers_lemon.py with fixture + exact assertions.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_parsers_lemon.py -q — green.
Do NOT modify core/parser.py or core/models.py. Report: files + test output." -t terminal,file --source marathon-pass2 > build_logs/pass2_lemon.log 2>&1 &

nohup $HERMES chat -q "You are a coding subagent for the 'Creator Income Copilot' project at $PROJ. FIRST read $PROJ/EXPANSION.md and $PROJ/core/parser.py (the existing facade).
YOUR TASK: UPDATE $PROJ/core/parser.py so parse_csv(text, source_hint=None) routes to the new parser modules: source_hint 'payhip'|'gumroad'|'shopify'|'kofi'|'lemon'|'generic' → dedicated parser if available (import core.parsers.shopify, core.parsers.ko_fi, core.parsers.lemon — they are being written by other agents, import them lazily inside the function with try/except ImportError so parser.py works even if one is missing). Auto-detect fallback: when hint is None, try each parser's header-detection (add a detect(headers) -> bool function to each parser module if missing — for shopify 'Lineitem name' in headers, kofi 'Payment Date' in headers, lemon 'Order' + 'Created' in headers) and route to the first match, else generic. Keep ALL existing behavior/tests passing.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_parser.py -q — must stay green (this is the CRITICAL constraint).
Do NOT modify core/models.py. Report: files changed + test output." -t terminal,file --source marathon-pass2 > build_logs/pass2_router.log 2>&1 &

wait_for_agents "pass2 parsers"

# analytics2 + insights_extra (depend on parser updates being done, independent of each other)
nohup $HERMES chat -q "You are a coding subagent for the 'Creator Income Copilot' project at $PROJ. FIRST read $PROJ/EXPANSION.md, $PROJ/core/models.py, and $PROJ/core/analytics.py (match style; import its helpers if useful).
YOUR TASK: write $PROJ/core/analytics2.py per EXPANSION.md 'core/analytics2.py' section: currency_report (currency mix + FX-normalized total with hardcoded rates USD base: EUR 1.08, GBP 1.27, CAD 0.73, AUD 0.65), cohort_analysis (monthly first-purchase cohorts, repeat rate per cohort, avg orders per customer), anomaly_detection (day-over-day revenue z-scores, flag >2σ with date+magnitude), seasonality (weekday vs weekend split, day-of-week averages, best/worst day), price_metrics (AOV trend first-half vs second-half, discount-heavy products flagged when price <60% of product's own median, price clusters). All pure computation, deterministic, NO LLM. Write $PROJ/tests/test_analytics2.py with hand-computed fixtures (e.g. 2 currencies → correct mix; known cohort dates → exact repeat rate; obvious spike day → flagged).
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_analytics2.py -q — green.
Do NOT modify core/models.py or core/analytics.py. Report: files + test output." -t terminal,file --source marathon-pass2 > build_logs/pass2_analytics2.log 2>&1 &

nohup $HERMES chat -q "You are a coding subagent for the 'Creator Income Copilot' project at $PROJ. FIRST read $PROJ/EXPANSION.md, $PROJ/core/models.py, $PROJ/core/analytics2.py (being written in parallel — if missing, wait: write your module to import it lazily inside functions and VERIFY only after it exists; poll with sleep 20 up to 5 min until $PROJ/core/analytics2.py exists before final verification).
YOUR TASK: write $PROJ/core/insights_extra.py per EXPANSION.md: deep_dive_insights(report: AnalyticsReport, extra: dict) -> list[str] turning analytics2 outputs into heuristic insight strings (currency concentration risk, cohort retention warning, anomaly explanations, best-selling day insight). Also modify $PROJ/core/report.py MINIMALLY: after building analytics report, compute analytics2 outputs, call deep_dive_insights, and PREPEND those strings to insights.insights (before LLM) and include in heuristic path. Keep build_analyze_response signature identical. Do NOT break existing tests.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_analytics2.py tests/test_llm.py -q — green (poll until analytics2.py exists first).
Do NOT modify core/models.py. Report: files + test output." -t terminal,file --source marathon-pass2 > build_logs/pass2_insights.log 2>&1 &

wait_for_agents "pass2 analytics"

# ============ PASS 3: Test depth ============
log "=== PASS 3: test depth ==="
nohup $HERMES chat -q "You are a testing subagent for 'Creator Income Copilot' at $PROJ. FIRST read $PROJ/EXPANSION.md and $PROJ/core/parser.py + all core/parsers/*.py.
YOUR TASK: write $PROJ/tests/test_parsers_all.py — fixtures for ALL 6 source formats (payhip, gumroad, shopify, kofi, lemon, generic) using each parser module directly, with exact expected numbers. Then $PROJ/tests/test_fuzz.py — 50 randomized CSV generators (use python random with fixed seed): random column permutations, missing columns, BOM prefix, CRLF vs LF, quoted commas, unicode product names, negative/zero prices (warn+skip), duplicate order IDs (keep first, warn), huge qty (cap), date formats (ISO, US m/d/Y, EU d/m/Y, epoch seconds). The parser must NEVER raise and build_report must NEVER raise. Assert: for each fuzz CSV, parse_csv returns (records, warnings) and build_report(records) returns AnalyticsReport without exception.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_parsers_all.py tests/test_fuzz.py -q — green.
Do NOT modify core/*. Report: files + test output." -t terminal,file --source marathon-pass3 > build_logs/pass3_fuzz.log 2>&1 &

nohup $HERMES chat -q "You are a testing subagent for 'Creator Income Copilot' at $PROJ. FIRST read $PROJ/EXPANSION.md, $PROJ/main.py, $PROJ/core/report.py.
YOUR TASK: write $PROJ/tests/test_api_edge.py using fastapi TestClient: (1) empty CSV file → 400 or graceful; (2) 6MB file → 413 or 400; (3) wrong content-type .exe filename → 400; (4) JSON body {'csv_text': 'garbage'} → 400; (5) valid JSON body csv_text → 200 with correct schema; (6) 20 concurrent requests to /api/sample/analyze (threads) → all 200; (7) monkeypatch core.report's LLM call to force fallback, assert used_fallback True propagates in response. Also verify /api/sample returns CSV attachment with correct filename.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_api_edge.py -q — green.
Do NOT modify main.py or core/*. Report: files + test output." -t terminal,file --source marathon-pass3 > build_logs/pass3_edge.log 2>&1 &

wait_for_agents "pass3 tests"

# ============ PASS 4: Frontend depth ============
log "=== PASS 4: frontend depth ==="
nohup $HERMES chat -q "You are a frontend subagent for 'Creator Income Copilot' at $PROJ. FIRST read $PROJ/EXPANSION.md and $PROJ/static/index.html, $PROJ/static/app.js, $PROJ/static/style.css (existing dashboard — extend, don't rewrite).
YOUR TASK:
1. style.css: add responsive breakpoints (max-width 480px mobile, 768px tablet), prefers-reduced-motion support, visible focus-visible rings, print-friendly styles (@media print hides upload zone/buttons, shows report cleanly).
2. app.js: add per-panel error states (each section shows 'Failed to load' + retry), empty states (no data → friendly message), Intl.NumberFormat USD currency formatting everywhere, keyboard shortcuts (u = trigger file input, s = load sample data), a 'Download report (CSV)' button that builds a CSV client-side from the JSON analytics (top products + revenue by day).
3. index.html: add footer ('Built for the NativeBuilder AI Factory Hackathon' + year), <noscript> message, section IDs for anchor nav.
VERIFY: node --check static/app.js passes (node at /opt/homebrew/bin/node or which node).
Do NOT modify any Python. Report: files changed + syntax check." -t terminal,file --source marathon-pass4 > build_logs/pass4_frontend.log 2>&1 &

nohup $HERMES chat -q "You are a backend subagent for 'Creator Income Copilot' at $PROJ. FIRST read $PROJ/EXPANSION.md and $PROJ/main.py.
YOUR TASK: add sample store #2 for the frontend store-switcher. Write $PROJ/sample_data/store2_gumroad.csv — a Gumroad-style export for a different fictional store ('PixelPerch — Lightroom presets & brushes', ~80 orders over 45 days, 5 products, some refunds, USD, Gumroad headers: 'Product','Order Number','Created At','Price','Quantity','Email','Refunded' where Refunded is 'true'/'false'). Then modify main.py: GET /api/sample?store=2 serves store2_gumroad.csv; POST /api/sample/analyze?store=2 runs it through the pipeline; GET /api/sample (no param) keeps default payhip_sample.csv. Keep existing behavior intact.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_api.py -q — green.
Do NOT modify core/*. Report: files + test output." -t terminal,file --source marathon-pass4 > build_logs/pass4_store2.log 2>&1 &

wait_for_agents "pass4 frontend"

# ============ PASS 5: docs + security + perf ============
log "=== PASS 5: docs + security + perf ==="
nohup $HERMES chat -q "You are a docs subagent for 'Creator Income Copilot' at $PROJ. FIRST read $PROJ/EXPANSION.md, $PROJ/SPEC.md and skim the code (core/, main.py, static/).
YOUR TASK: write $PROJ/docs/ARCHITECTURE.md (module map, ASCII data-flow diagram from CSV upload → parser → analytics → LLM/heuristic → JSON → frontend, key decisions: why stateless, why heuristic fallback) and $PROJ/docs/DEMO_SCRIPT.md (90-second demo walkthrough for the hackathon video: exact clicks, what to say, what to point at, including the 'Try sample data' path and the AI panel).
Do NOT modify code. Report: files written." -t terminal,file --source marathon-pass5 > build_logs/pass5_docs.log 2>&1 &

nohup $HERMES chat -q "You are a security reviewer for 'Creator Income Copilot' at $PROJ. FIRST read all code: core/*.py, main.py, static/app.js, static/index.html.
YOUR TASK: find injection/XSS/data-leak risks (frontend innerHTML with unescaped data from API — check app.js carefully; CSV parser formula injection — product names starting with =,+,-,@ that could be CSV formula injection; SSRF — none expected; secrets — .env exposure via /static or /api; file upload abuse — path traversal in filename). For each issue: severity, location, fix. Fix the trivial ones directly in the files (XSS escaping in app.js, CSV formula sanitization in parser if needed). Write $PROJ/docs/SECURITY.md with findings + fixes.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/ -q — still green after your fixes.
Report: findings + fixes + test output." -t terminal,file --source marathon-pass5 > build_logs/pass5_security.log 2>&1 &

nohup $HERMES chat -q "You are a performance engineer for 'Creator Income Copilot' at $PROJ. FIRST read core/parser.py, core/analytics.py, core/analytics2.py, main.py.
YOUR TASK: write $PROJ/tests/test_perf.py that generates a 10,000-row CSV (payhip-style, realistic), times parse_csv + build_report + build_analyze_response (with api_key=None to force heuristic), asserts: parse < 5s, analytics < 3s, full pipeline < 10s on this machine. If timings exceed, profile (cProfile or time.perf_counter around sections) and OPTIMIZE the hot paths in core/parser.py and core/analytics.py (avoid O(n^2) patterns, use dict aggregation) WITHOUT changing public signatures. 
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_perf.py -q — green (adjust thresholds to be realistic but strict enough to catch O(n^2)).
Do NOT modify core/models.py or main.py. Report: optimizations + test output." -t terminal,file --source marathon-pass5 > build_logs/pass5_perf.log 2>&1 &

wait_for_agents "pass5 docs/security/perf"

# ============ PASS 6: deploy + github ============
log "=== PASS 6: deploy + github ==="
cd $PROJ
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5 | tee -a $LOG

# Try gh
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  log "gh available — creating repo"
  gh repo create creator-income-copilot --public --source . --push --description "Creator Income Copilot — hackathon submission" 2>&1 | tee -a $LOG || log "repo create failed (may already exist)"
else
  log "gh not available — skipping github (will try later)"
fi

log "MARATHON PASSES 2-6 COMPLETE"
