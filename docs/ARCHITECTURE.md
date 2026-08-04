# Creator Income Copilot — Architecture

Version: matches the current repo state (SPEC.md v1 + EXPANSION.md Pass 2–4 landed).
Audience: contributors, reviewers, hackathon judges who want to understand the system in ~5 minutes.

---

## 1. Overview

Creator Income Copilot is a **stateless, single-process web app**: a creator uploads a
sales CSV (Payhip / Gumroad / Shopify / Ko-fi / Lemon Squeezy / generic) and receives, as
one JSON response, an analytics dashboard payload, AI-style insights, a drafted promo
email, and a "what to build next" product recommendation.

Everything is **per-request and in-memory**: no database, no login, no sessions, no
persisted state. The only optional outbound call is an LLM inference request to
OpenRouter — and the system is explicitly designed to work *without* it via a
deterministic heuristic engine (see "Key decisions", §5).

### Stack (fixed by SPEC)

| Layer      | Choice                                                      |
|------------|-------------------------------------------------------------|
| Runtime    | Python 3.11                                                  |
| API        | FastAPI + uvicorn, Pydantic v2 models                        |
| Storage    | None (stateless, per-request)                                |
| Frontend   | Vanilla HTML/CSS/JS + Chart.js 4.4.1 (CDN), served by FastAPI |
| LLM        | OpenRouter chat completions (optional), graceful fallback    |
| Tests      | pytest + fastapi TestClient                                  |

---

## 2. Module map

```
creator-income-copilot/
├── main.py                  FastAPI app: 4 routes, input validation, CORS, static mount
├── core/
│   ├── models.py            FROZEN contract — all cross-module Pydantic models
│   ├── parser.py            FACADE: schema auto-detect, synonym header engine,
│   │                        routes to dedicated parsers (lazy), never raises
│   ├── parsers/
│   │   ├── __init__.py      empty
│   │   ├── shopify.py       Shopify orders export parser (per-unit price = Total/qty)
│   │   ├── ko_fi.py         Ko-fi payments export parser
│   │   └── lemon.py         Lemon Squeezy orders export parser
│   ├── analytics.py         build_report(): deterministic core analytics (pure)
│   ├── analytics2.py        Pass 2 deep analytics: currency, cohorts, anomalies,
│   │                        seasonality, price metrics (pure, lazy-imported)
│   ├── insights_extra.py    deep_dive_insights(): analytics2 output -> insight strings
│   ├── llm.py               generate_insights(): OpenRouter call OR heuristic fallback
│   ├── promo.py             build_promo_email(): deterministic template email
│   └── recommender.py       recommend_next_product(): deterministic product rec
├── static/
│   ├── index.html           Single-page dashboard (dark theme, 6 sections)
│   ├── app.js               Fetch + render + per-panel error isolation + shortcuts
│   └── style.css            Theme, responsive breakpoints, print view
├── sample_data/
│   ├── payhip_sample.csv    Store 1 "StudioNova" — 120 Payhip-style orders
│   └── store2_gumroad.csv   Store 2 "PixelPerch" — 80 Gumroad-style orders
├── tests/                   Per-module tests + fuzz + API edge cases
├── deploy/                  Dockerfile + render.yaml
└── docs/                    This file, DEMO_SCRIPT.md, SECURITY.md
```

### Import rules (engineering constraint)

Modules import **only** from `core.models` plus their own declared dependencies —
`analytics2` and the `parsers/*` package are imported **lazily** so that modules
written by parallel agents can land in any order without breaking the pipeline.
`core/models.py` is frozen and never modified.

---

## 3. Data model (core/models.py, frozen)

All data flows through these Pydantic models:

- `SaleRecord` — one normalized sale: order_id, date, product, price, currency,
  quantity, customer_email, question (buyer note), refunded, source.
- `ProductStats` — per-product: units, revenue, share_pct, refunds, avg_price,
  momentum (`up`/`down`/`flat`) + momentum_pct (last 7d vs prior 7d).
- `DayPoint` — one day of the zero-filled revenue/orders series.
- `Trend` — label + direction + magnitude_pct + human description.
- `ChurnSignal` — product + signal_type (high_refund_rate / low_repeat_rate /
  slowing_sales / other) + severity (low/medium/high) + description.
- `AnalyticsReport` — the full analytics payload (KPIs, top_products, revenue_by_day,
  trends, churn_signals, questions).
- `PromoEmail`, `NextProduct` — nested AI outputs.
- `LLMInsights` — insights[] + promo_email + next_product + **used_fallback** flag
  (True when heuristics served the response).
- `AnalyzeResponse` = `{ analytics, insights, warnings }` — the exact body of
  `POST /api/analyze`.

---

## 4. Data flow

```
                        BROWSER  (static/index.html + app.js + Chart.js CDN)
   ┌───────────────────────────────────────────────────────────────────────┐
   │  drop zone / Upload CSV button / keyboard "U"        "Try sample data" │
   │  (multipart file, .csv/.txt ≤5MB)                     or keyboard "S"  │
   └───────────────┬───────────────────────────────────────────┬───────────┘
                   │ POST /api/analyze                          │ POST /api/sample/analyze
                   │ (or JSON {"csv_text": ...})                │ (?store=1|2)
                   ▼                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  main.py  (FastAPI)                                                    │
   │  1. _extract_csv: content-type dispatch, 422/400 validation            │
   │     (missing field, bad extension, >5MB, empty csv_text)               │
   │  2. _analyze_csv_text: parse -> 400 if zero records, else orchestrate  │
   └───────────────────────────────┬───────────────────────────────────────┘
                                   │ 2. csv text + optional source_hint
                                   ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  core/parser.py  (facade — never raises)                               │
   │   header row scan                                                      │
   │     ├─ dedicated?  shopify|kofi|lemon  ->  lazy import core/parsers/X  │
   │     │                                    -> detect()/markers match      │
   │     │                                    -> parse(text)                 │
   │     │                                    (failure -> warn, fall through)│
   │     └─ built-in synonym engine: _map_headers -> payhip|gumroad|generic  │
   │   per row: date (24 formats) / product / price (cents-aware) / qty /    │
   │   currency / email / question / refund (status|flag|negative price)     │
   │   bad rows  ->  warnings[]  (never raise, never drop the file)          │
   └───────────────────────────────┬───────────────────────────────────────┘
                                   │ 3. (list[SaleRecord], warnings)
                                   ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  core/report.py  build_analyze_response(records, warnings)             │
   │                                                                        │
   │   core/analytics.build_report(records)   ──► AnalyticsReport           │
   │        (pure, deterministic, net-sales view)                            │
   │          + _compute_extra(records)                                      │
   │              └─ lazy import core.analytics2 (per-piece guarded):       │
   │                 currency / cohorts / anomalies / seasonality /         │
   │                 price_metrics                                          │
   │          + core.insights_extra.deep_dive_insights(report, extra)       │
   │              └─ extra heuristic strings (cohort/currency/day/anomaly)  │
   │                                                                        │
   │   core.llm.generate_insights(report, OPENROUTER_API_KEY)               │
   │        ├─ key missing  ────────────────► heuristic_insights()          │
   │        ├─ key present ──► OpenRouter POST (25s timeout, json_object)   │
   │        │      success ──► LLMInsights.model_validate(json)             │
   │        │      ANY failure (timeout/HTTP/JSON/schema) ──► heuristic     │
   │        └─ used_fallback flag set on the heuristic path                 │
   │                                                                        │
   │   deep-dive strings PREPENDED to insights.insights (both paths)        │
   └───────────────────────────────┬───────────────────────────────────────┘
                                   │ 4. AnalyzeResponse JSON (Pydantic-serialized)
                                   ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  BROWSER render (app.js)                                               │
   │   KPI cards  -> revenue line + orders bars (Chart.js) -> top products  │
   │   -> trends + churn signals -> AI panel (insights, promo email + Copy, │
   │   next product) -> warnings card. "heuristic mode" chip when           │
   │   insights.used_fallback. Download report (CSV) built client-side.     │
   └───────────────────────────────────────────────────────────────────────┘
```

### Request lifecycle (numbers from a real run on the sample)

1. Browser POSTs the CSV (or hits sample/analyze).
2. `parse_csv` normalizes 120 rows -> 116 `SaleRecord`s (4 refunded flagged).
3. `build_report` computes the analytics in a single pass.
4. `analytics2` computes deep-dive pieces; `insights_extra` renders ~3 extra strings.
5. `generate_insights` — with no usable key, returns heuristics instantly
   (used_fallback=True); with a key, OpenRouter has a 25s ceiling.
6. Response round-trips as `AnalyzeResponse`; dashboard renders in milliseconds.

---

## 5. Key decisions

### 5.1 Why stateless (no database, no login)

- **Demo-first.** A judge should go from empty browser tab to full dashboard in
  seconds with zero friction: no signup, no schema, no seed data.
- **It is genuinely more private.** "Processed in memory, nothing stored" is a real
  property of the architecture, not a marketing line — the data lives in a request
  handler and dies with the response. The frontend footer and upload zone say exactly
  this, and it is true.
- **The domain is a pure function.** Analyze a CSV once -> get a report. There is no
  cross-request state to maintain, so a database would be pure overhead. The one thing
  given up — comparing against last month's upload without re-uploading — is out of
  scope for a demo tool and cheap to add later (store hashes, not data).
- **Ops simplicity + scaling.** One uvicorn process runs anywhere (see deploy/). Need
  more capacity? Add workers — there is no shared state to coordinate.

### 5.2 Why the heuristic fallback is a first-class path, not an afterthought

- **The demo must work keyless** (SPEC requirement). The app is judged in a live room:
  network, rate limits, and API keys are all failure modes. `generate_insights` returns
  deterministic heuristics when `OPENROUTER_API_KEY` is missing and on *any* exception —
  timeout, non-2xx, invalid JSON, schema mismatch. It never raises, so `POST /api/analyze`
  can never 500 because of the LLM.
- **Determinism is testable.** The heuristic path is pure: same CSV -> same insights,
  promo email, and recommendation. Tests assert exact strings and numbers with no
  network. The LLM path is non-deterministic by nature and can only be integration-tested.
- **The UI is honest about the mode.** `used_fallback` propagates through
  `LLMInsights` to a "heuristic mode" chip in the AI panel — the product tells the user
  which engine produced the text instead of pretending.
- **Both paths get the deep-dive strings.** `report.py` prepends the analytics2-derived
  heuristic insights (cohort retention, best-selling day, currency concentration) to
  `insights.insights` *before* the LLM call, so even a perfect LLM answer is grounded in
  the deterministic analytics, and the fallback path is never thin.
- **The heuristic engine is real intelligence.** `promo.py` writes a 3-paragraph email
  from actual revenue/units/momentum numbers; `recommender.py` mines buyer questions for
  demand signals and cites them verbatim as evidence. The fallback is a product, not a
  placeholder.

### 5.3 Parser robustness: never raise, warn instead

- The parser contract (fuzz-tested in tests/test_fuzz.py): 50 randomized CSVs with
  column permutations, missing columns, BOM, CRLF/LF, quoted commas, unicode names,
  negative prices, duplicate IDs, weird dates — the parser must never raise and the
  report must never raise. Bad rows become `warnings[]` surfaced in the UI.
- Dedicated parsers are **lazy-imported** with a broad exception catch: modules written
  by parallel agents may be half-written at any moment, and a broken module must degrade
  to the built-in engine with a warning, not crash the app.
- Shopify's `Total` is a whole-order total, so the parser stores `price = Total / qty`
  for multi-quantity rows, preserving the `price * quantity == Total` invariant.

### 5.4 Net-sales semantics (analytics.py)

Refunded orders never contribute to revenue, order counts, units, customers, the daily
series, or momentum. They surface only as `ProductStats.refunds` and the
`high_refund_rate` churn signal. A refund is not a sale; this keeps the dashboard
honest and the numbers easy to reason about.

### 5.5 Momentum anchors to the data, not to "now"

The "last 7 days" window is `[period_end - 6d, period_end]`, not `[today - 6d, today]`.
An uploaded export is rarely current, and anchoring to wall-clock time would make the
flagship trend empty for any dataset that ends last week. Anchoring to the data's own
end keeps every upload meaningful.

### 5.6 Auto-detect with an explicit escape hatch

`parse_csv(text, source_hint)` accepts payhip/gumroad/generic/shopify/kofi/lemon or
`None`. With `None`, the header row is scanned: dedicated parsers first (shopify ->
kofi -> lemon, via module `detect()` or marker fallback), then the built-in synonym
engine. This is why the sample store-2 route pins `source_hint="gumroad"` — PixelPerch's
`Order Number` + `Created At` headers would false-match the Lemon Squeezy signature.

### 5.7 Frontend defensive design (static/)

- Every CSV-derived string passes through `esc()` before HTML injection (XSS is
  designed out, not patched in — full risk list lives in docs/SECURITY.md, produced
  by the Pass 5 security review).
- Panels render independently: a failure in one section shows an inline "Failed to
  load" + Retry state instead of killing the dashboard.
- The staged loading overlay ("Parsing CSV... / Crunching numbers... / Generating AI
  insights...") masks LLM latency (up to 25s) and sets the expectation that the demo
  lands in under 10 seconds.
- Keyboard shortcuts (U = upload, S = sample), drag-and-drop, client-side report CSV
  download, and a clipboard fallback (`execCommand`) for the Copy-email button keep the
  demo fast to operate on camera.
- The only hard external dependency is Chart.js from a CDN; if it fails, the chart
  panel shows a graceful message and the rest of the dashboard still works.

### 5.8 LLM boundary and privacy

`AnalyticsReport` contains aggregated numbers and buyer *questions* — never customer
emails (those stay in `SaleRecord`, which is not serialized to the LLM). The prompt
demands strict JSON matching the `LLMInsights` schema (`response_format: json_object`),
and the response is validated back through Pydantic, so a malformed LLM reply is a
fallback trigger, not a crash.
