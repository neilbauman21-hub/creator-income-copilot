# Creator Income Copilot — EXPANSION SPEC (Pass 2+)

Foundation (Pass 1) is being built by the running pipeline. This spec defines
deepening passes. Each pass = new agent swarm, layered on top of existing code.
Do NOT rewrite existing working modules — extend them. All new code imports ONLY
from core.models + its own deps + existing core modules.

## Pass 2 — Data depth (more sources, more analytics)

### core/parsers/ package (replaces single parser.py's scope, keep parser.py as facade)
- `core/parsers/shopify.py` — `parse(text) -> (list[SaleRecord], list[str])` for
  Shopify orders export. Columns: Name/Order, Created at, Total, Lineitem quantity,
  Lineitem name, Financial status, Email. Map to SaleRecord. Same synonym matching
  style as core/parser.py. Export `SUPPORTED_SOURCES` dict.
- `core/parsers/ko_fi.py` — Ko-fi payments export (Payment Date, Gross, Item, Email).
- `core/parsers/lemon.py` — Lemon Squeezy (Order, Created, Total, Product, Email, Status).
- Update `core/parser.py` `parse_csv` to accept source_hint values
  "payhip"|"gumroad"|"shopify"|"kofi"|"lemon"|"generic" and route to the right
  parser module (fallback: auto-detect by header scan across all).

### core/analytics2.py — deeper analytics (new module, imports core.analytics)
- `currency_report(records) -> dict` — currency mix, FX-normalized total (assume
  USD base, hardcode rough rates EUR 1.08, GBP 1.27, CAD 0.73, AUD 0.65).
- `cohort_analysis(records) -> list[dict]` — monthly first-purchase cohorts,
  repeat rate per cohort, avg orders per customer.
- `anomaly_detection(records) -> list[dict]` — day-over-day revenue z-scores,
  flag days > 2σ (launch spikes / drops) with date + magnitude.
- `seasonality(records) -> dict` — weekday vs weekend revenue split, day-of-week
  averages, best/worst day.
- `price_metrics(records) -> dict` — avg order value trend (first half vs second
  half), discount-heavy product flag (products with price < 60% of their own
  median price), price point clusters.
- `write tests/test_analytics2.py` with hand-computed fixtures.

### core/insights_extra.py — additional heuristic insights (imports analytics2)
- `deep_dive_insights(report, extra) -> list[str]` — turn analytics2 outputs into
  more heuristic insight strings (currency concentration risk, cohort retention
  warning, anomaly explanations, best-selling day insight).
- Extended by llm.py? NO — keep llm.py untouched. `core/report.py` calls this and
  appends its strings to `insights.insights` BEFORE LLM call, and heuristic path
  uses them too. Modify report.py minimally.

## Pass 3 — Test depth (make the thing unbreakable)

- `tests/test_parsers_all.py` — fixtures for ALL 6 source formats, exact numbers.
- `tests/test_fuzz.py` — 50 randomized CSVs (property-based with `random`): random
  column permutations, missing columns, weird whitespace, BOM prefix, CRLF vs LF,
  quoted commas, unicode product names, negative/zero prices (warn+skip),
  duplicate order IDs (keep first, warn), huge qty (cap warn), date formats
  (ISO, US m/d/Y, EU d/m/Y, epoch). parser must never raise; report must never raise.
- `tests/test_api_edge.py` — empty file, 6MB file (413/400), wrong content type,
  .exe filename, JSON body with bad csv_text, concurrent 20 requests (TestClient),
  sample/analyze with mocked LLM (monkeypatch generate_insights) asserting
  used_fallback flag propagation.
- Add `hypothesis` to requirements-dev (optional; skip if install is painful —
  plain random-based fuzz is fine).

## Pass 4 — Frontend depth

- `static/style.css` — add: responsive breakpoints (mobile 480, tablet 768),
  prefers-reduced-motion, focus-visible rings, print-friendly report view.
- `static/app.js` — add: error state UI per panel (not just toast), empty states,
  sample-store switcher (2 fictional stores → different CSVs served by new
  endpoint GET /api/sample?store=2), CSV download of current report
  (GET /api/report.csv? not needed — generate client-side from JSON),
  number formatting (Intl.NumberFormat USD), keyboard shortcuts (u=upload, s=sample).
- `static/index.html` — add: footer with 'Built with native.builder spirit'
  + hackathon badge; section anchors; <noscript> message.
- New endpoint in main.py: `GET /api/sample?store=2` → second sample CSV
  (add sample_data/store2_payhip.csv, different product mix, ~80 orders, Gumroad-style).

## Pass 5 — Polish & hardening (Claude Code pass, then agent swarm)

1. Claude Code (`claude -p`) reviews the whole repo: bugs, edge cases, style,
   FastAPI correctness, XSS in frontend (escapes!), chart rendering.
2. Agent swarm: 
   - `docs/ARCHITECTURE.md` — module map, data flow diagram (ASCII), decisions.
   - `docs/DEMO_SCRIPT.md` — 90-second demo walkthrough for the hackathon video
     (exact clicks, what to say, what to point at).
   - security review agent: read all code, list injection/XSS/data-leak risks,
     fix trivial ones, file `docs/SECURITY.md`.
   - perf agent: profile `/api/analyze` on 10k-row CSV, report timing breakdown,
     optimize hot paths (parser loops, analytics dicts).

## Pass 6 — Deploy & verify

- `deploy/render.yaml` + `Dockerfile` (already Pass 1, verify they work).
- Actually deploy: check for `render`/`fly`/`railway`/`vercel` CLIs, or use
  Cloudflare Pages/PythonAnywhere fallback. MUST end with a public URL that
  returns the dashboard HTML. Verify with curl + browser screenshot.
- GitHub repo: `gh repo create creator-income-copilot --public --source . --push`
  (check gh auth). Add CI workflow `.github/workflows/test.yml` (pytest on push).

## Engineering rules (same as SPEC.md)
- Import ONLY from core.models and listed deps. Type hints everywhere.
- Extend, don't rewrite. If a file must change, keep its public functions intact.
- Every module ships with its own tests. `python3 -m pytest tests/ -q` must be green.
- No network calls in tests (mock or construct data directly).
- Report back: files written + test output.
