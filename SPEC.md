# Creator Income Copilot — Build Spec (v1)

Hackathon: lablab.ai NativeBuilder "Build Without Limits" (Aug 3–10, 2026).
Product: **Creator Income Copilot** — a digital-product seller's income intelligence tool.
User uploads a sales CSV (Payhip/Gumroad/generic) → gets: analytics report, AI insights,
a drafted promo email, and a "what to build next" recommendation. Demo-friendly, no login.

## Stack (fixed — do not change)

- Python 3.11, FastAPI + uvicorn, Pydantic v2, no database (stateless per-request)
- Frontend: vanilla HTML/CSS/JS + Chart.js via CDN, served by FastAPI from `static/`
- LLM: OpenRouter API (`OPENROUTER_API_KEY` from `.env`) — MUST degrade gracefully to
  heuristic fallback when key missing / timeout / parse error. The demo must work keyless.
- Tests: pytest + fastapi TestClient. Run: `python3 -m pytest tests/ -q`

## Project layout

```
creator-income-copilot/
  core/
    __init__.py        (empty)
    models.py          (FROZEN — already written, read it, do NOT modify)
    parser.py          (Wave 1, agent A)
    analytics.py       (Wave 1, agent B)
    llm.py             (Wave 1, agent C)
    report.py          (Wave 2, agent D)
    promo.py           (Wave 2, agent E)
    recommender.py     (Wave 2, agent F)
  main.py              (Wave 3, agent G — FastAPI app)
  static/
    index.html         (Wave 3, agent H)
    app.js
    style.css
  sample_data/
    payhip_sample.csv  (Wave 3, agent I)
  tests/
    test_parser.py     (Wave 1, agent A)
    test_analytics.py  (Wave 1, agent B)
    test_llm.py        (Wave 2, agent E)
    test_api.py        (Wave 3, agent G)
  deploy/
    Dockerfile         (Wave 4)
    render.yaml        (Wave 4)
  requirements.txt     (Wave 4)
  README.md            (Wave 4)
  HACKATHON_SUBMISSION.md (Wave 4)
  .env                 (contains OPENROUTER_API_KEY — never commit)
```

## Data model (in core/models.py — READ IT FIRST)

All cross-module data flows through these Pydantic models (already written):
`SaleRecord`, `ProductStats`, `DayPoint`, `Trend`, `ChurnSignal`, `AnalyticsReport`,
`LLMInsights` (with nested `PromoEmail`, `NextProduct`), `AnalyzeResponse`.

`AnalyzeResponse` = `{ "analytics": AnalyticsReport, "insights": LLMInsights, "warnings": list[str] }`
This exact shape is what `POST /api/analyze` returns.

## Module contracts

### core/parser.py
- `parse_csv(text: str, source_hint: str | None = None) -> tuple[list[SaleRecord], list[str]]`
  - Accepts CSV text (not file paths). Returns (records, warnings).
  - Auto-detect schema: Payhip orders export, Gumroad sales export, or generic
    (date | product/title | price/amount | qty/quantity | email | status/refunded | question).
  - Column matching is case-insensitive, whitespace-normalized, synonym-based
    (e.g. "Order Date" / "Created At" / "Date" → date). Detect via header scan.
  - `source_hint` may be "payhip" | "gumroad" | None (auto).
  - Skip/flag invalid rows as warnings, never crash on a bad row.
  - `SaleRecord`: order_id (str, may be empty), date (datetime), product (str),
    price (float), currency (str, default "USD"), quantity (int, default 1),
    customer_email (str | None), question (str | None — buyer question/notes if present),
    refunded (bool, default False), source (str: "payhip"|"gumroad"|"generic").
  - Write `tests/test_parser.py` covering: payhip fixture, gumroad fixture, generic
    fixture, missing-column fallback, bad-date row (warn, skip), refund detection.

### core/analytics.py
- `build_report(records: list[SaleRecord]) -> AnalyticsReport`
  - Pure computation, NO LLM calls. All fields in models.py must be filled.
  - Top products by revenue; revenue_by_day (chronological, ISO dates); trends
    (e.g. last-7 vs prior-7 revenue, per-top-product momentum — direction up/down/flat
    with magnitude_pct); churn_signals (refund-rate >10% per product, repeat-purchase
    rate <15%, slowing sales on a former top product); unique_customers,
    avg_order_value, repeat_purchase_rate (customers with >1 order).
  - Write `tests/test_analytics.py` with a small hand-computed fixture asserting
    exact numbers.

### core/llm.py (Wave 1, agent C)
- `generate_insights(report: AnalyticsReport, api_key: str | None) -> LLMInsights`
  - If no api_key → immediately return heuristic fallback (rule-based insights from
    report numbers, promo email via `core.promo.build_promo_email`, next-product via
    `core.recommender.recommend_next_product`). NEVER raise.
  - Else call OpenRouter `POST https://openrouter.ai/api/v1/chat/completions`,
    model from env `OPENROUTER_MODEL` (default `google/gemini-2.0-flash-001`),
    request JSON with `response_format: {"type": "json_object"}`, instruct the model
    to output EXACTLY the LLMInsights schema (insights[], promo_email{subject, body},
    next_product{name, rationale, evidence}).
  - Timeout 25s. Any exception OR invalid JSON → heuristic fallback. Log a warning.
- `heuristic_insights(report: AnalyticsReport) -> LLMInsights` — export it for tests.
  Imports `core.promo.build_promo_email` and `core.recommender.recommend_next_product`
  for the email + recommendation (DO NOT write template logic inline — call them).

### core/report.py
- `build_analyze_response(records) -> AnalyzeResponse` — orchestration: parse → analytics →
  insights (reads OPENROUTER_API_KEY from env itself via `os.getenv`), assembles
  `AnalyzeResponse` with warnings passthrough. `main.py` calls ONLY this.

### core/promo.py (Wave 2, agent D)
- `build_promo_email(report: AnalyticsReport) -> PromoEmail` — deterministic
  template-based promo email for the top product using REAL numbers from the report
  (revenue, units, momentum). Subject line + 3 short paragraphs. Import ONLY from
  core.models + stdlib. Used by llm.py's heuristic fallback.
- `build_promo_prompt(report: AnalyticsReport) -> str` — system/user prompt text for
  the LLM path (tells the model exactly what to generate, with the report JSON).

### core/recommender.py (Wave 2, agent E)
- `recommend_next_product(report: AnalyticsReport) -> NextProduct` — deterministic
  recommendation: dominant product category + signals from `report.questions`
  (keyword matching: "template" → new template product, "pdf" → pdf, "pack" → bundle,
  "course"/"tutorial" → course, else category extension). Name + rationale + evidence
  (cite a real customer question if one matches). Import ONLY from core.models + stdlib.
- `build_recommender_prompt(report: AnalyticsReport) -> str` — LLM prompt text.

### core/report.py (Wave 2, agent F)
- `build_analyze_response(records: list[SaleRecord], warnings: list[str]) -> AnalyzeResponse`
  — orchestration: analytics.build_report → llm.generate_insights (reads
  OPENROUTER_API_KEY itself via os.getenv + load_dotenv). Assemblies AnalyzeResponse.
  `main.py` calls ONLY this.

### main.py (FastAPI app)
- `GET /` → serve `static/index.html`
- `POST /api/analyze` — multipart form field `file` (CSV) OR JSON body `{"csv_text": "..."}`.
  Returns `AnalyzeResponse` (200) or `{"detail": "..."}` (400 for unparseable CSV).
  Accepts only .csv/.txt uploads, 5MB cap.
- `GET /api/sample` → returns `sample_data/payhip_sample.csv` as attachment.
- `POST /api/sample/analyze` → runs the built-in sample through the full pipeline.
- Mount `/static` for assets. CORS open (demo). Run with `uvicorn main:app --port 8000`.
- Write `tests/test_api.py`: sample analyze 200 + schema check, bad CSV 400,
  missing file 422.

### static/ (single-page dashboard, dark theme, no build step)
- `index.html` + `app.js` + `style.css`. Chart.js 4.x from CDN.
- Sections:
  1. Header: product name, tagline, "upload CSV" button + drag-drop zone + "Try sample data".
  2. KPI cards: total revenue, orders, avg order value, repeat-purchase rate.
  3. Revenue line chart (revenue_by_day) + top-products ranked list (share bars).
  4. Trends + churn signals (badge colors: up=green, down=red, flat=gray; severity chips).
  5. AI panel: insights list, promo email (subject + body, "Copy" button),
     next-product card (name, rationale, evidence).
  6. Warnings list if non-empty. Loading overlay with staged status text.
- app.js: `fetch('/api/analyze', FormData)`, render everything, graceful error toast.
- Must look polished — this is the hackathon demo surface. Modern, clean, professional.

### sample_data/payhip_sample.csv
- Realistic Payhip-style orders export for a fictional store ("StudioNova — Notion
  templates & ebook shop"): ~120 orders over the last 60 days, 6 products, some
  refunds (one product >10%), one column with buyer questions on ~15 rows,
  currency USD, headers matching Payhip naming (Order ID, Order Date, Product, etc.).
  Include a few rows with questions that hint at a missing product (demand signal).

## Engineering rules
- Every module: type hints, docstrings, no unused imports. Python stdlib + listed deps only.
- Files are written by DIFFERENT agents in parallel — import ONLY from `core.models`
  and the module's own dependencies listed above. Never invent new cross-module imports.
- Keep each module self-contained and testable in isolation.
- `.env` already exists with OPENROUTER_API_KEY — use `python-dotenv`'s `load_dotenv()`
  in `main.py` and `core/llm.py` before reading env vars.
- requirements.txt (Wave 4): fastapi, uvicorn, python-dotenv, pydantic, pytest, httpx.
- Do NOT modify `core/models.py`. Do NOT create files outside your assignment.

## Done criteria
`python3 -m pytest tests/ -q` all green; `uvicorn main:app` boots; browser demo works
(upload sample CSV → full dashboard + AI insights within ~10s).
