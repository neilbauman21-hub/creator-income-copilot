# SECURITY REVIEW — Creator Income Copilot

Date: 2026-08-04
Scope: main.py, core/*.py (parser, models, report, analytics, analytics2,
insights_extra, llm, promo, recommender), core/parsers/*.py (shopify, ko_fi,
lemon), static/app.js, static/index.html.
Verification baseline: 223/223 tests green before and after fixes.

---

## 1. Findings

### 1.1 CSV formula injection in report download — HIGH (FIXED)

Location: static/app.js — `csvEscape()` / `buildReportCsv()` (report CSV
download feature).

Product names come straight from the uploaded CSV (untrusted input). They are
written verbatim into the downloaded report CSV. A product name beginning with
`=`, `+`, `-`, `@`, tab or CR is interpreted by Excel / LibreOffice / Google
Sheets as a formula or DDE link when the file is opened:

  =HYPERLINK("http://attacker/x","click")     -> hyperlink spawn
  +cmd|'/C calc'!A0                            -> DDE command execution (legacy)
  @SUM(A1)                                     -> formula execution
  -2+3                                         -> formula execution

`csvEscape` only quoted fields containing commas/quotes/newlines; it did not
neutralize formula prefixes.

Fix applied: `csvEscape` now prefixes a single quote `'` to any field whose
first character is `=`, `+`, `-`, `@`, tab or CR (applied before quoting, so
the apostrophe lands inside the quoted field). Benign values are untouched.

Decision note — the CSV *parsers* (core/parser.py, core/parsers/*) were NOT
modified: they never emit CSV, they produce JSON. Product names are HTML-
escaped client-side for display, and the only CSV output point is the
client-side report download, which is where the guard belongs. Sanitizing at
parse time would corrupt displayed product names and break data fidelity.

### 1.2 XSS via innerHTML in app.js — NOT VULNERABLE (verified, hardening added)

Location: static/app.js — all render* functions.

Every API-data injection point was audited. An `esc()` helper (OWASP set
`& < > " '`) exists and is applied at all 10 sinks:

  renderKpis      -> esc() on label/value/sub          (safe)
  renderTopProducts -> esc(p.name) in text AND title attr; all numbers via
                       num()/fmtMoney/fmtNum           (safe)
  renderTrends    -> esc(t.label), esc(t.description)  (safe)
  renderChurn     -> esc(s.product/sev/desc); severity class from fixed set
                                                       (safe)
  renderInsights  -> esc(t), esc(np.name/rationale/evidence) (safe)
  renderWarnings  -> esc(w)                             (safe)
  emptyItem       -> esc(msg)                           (safe)
  dirBadge        -> direction mapped through fixed ternaries, never raw (safe)
  renderChart     -> labels go to Chart.js canvas, not HTML (safe)

No `eval`, no `new Function`, no raw `innerHTML` with unescaped API data.

Hardening applied anyway (defense-in-depth):
  - Content-Security-Policy on every response (strict script-src 'self' +
    chart.js CDN; no unsafe-inline/unsafe-eval for scripts; style-src allows
    'unsafe-inline' only because app.js sets inline style attributes).
  - X-Content-Type-Options: nosniff, X-Frame-Options: DENY,
    Referrer-Policy: no-referrer.

### 1.3 Secrets exposure (.env) — NOT VULNERABLE (verified)

Location: project root `.env` (OPENROUTER_API_KEY, OPENROUTER_MODEL).

Verified not reachable through the app:
  - GET /.env                     -> 404
  - GET /static/* only serves the static/ directory (app.mount is pinned).
  - GET /api/sample only serves two hardcoded sample paths.
  - `/` serves index.html only.
`.gitignore` excludes `.env` (verified). The API key is consumed server-side
by core/llm.py and never appears in responses. Keep the rule: never mount the
project root statically, never commit .env.

### 1.4 File upload abuse / path traversal — NOT VULNERABLE (verified)

Location: main.py `_extract_csv`.

The upload filename is used ONLY for an extension allowlist check
(`Path(filename).suffix in {".csv",".txt"}`). Content is read into memory and
decoded; it is never written to disk and the filename never touches the
filesystem. No path traversal, no arbitrary file write, no zip/decompression
bombs (no archive support). 5MB cap enforced.

### 1.5 SSRF — NONE (verified)

The only outbound network call in the entire codebase is
`core/llm.py` -> `httpx.post` to the hardcoded OpenRouter endpoint
(https://openrouter.ai/api/v1/chat/completions). No user-controlled URL is
ever fetched. Sample data is read from local files only.

### 1.6 Upload-size cap bypass via JSON body — MEDIUM (FIXED)

Location: main.py `_extract_csv`.

The 5MB cap was enforced only on the multipart path. The JSON `csv_text` path
had no size limit, so a client could POST an arbitrarily large body straight
into the CSV parser (memory/CPU exhaustion).

Fix applied: `csv_text` is now capped at MAX_UPLOAD_BYTES (5MB, UTF-8 byte
length, mirroring the multipart path). Oversized -> HTTP 400.

### 1.7 CORS wildcard — LOW (informational)

Location: main.py `app.add_middleware(CORSMiddleware, allow_origins=["*"])`.

For this stateless, auth-less demo the practical impact is nil: there are no
cookies/sessions to abuse, and a cross-origin POST only analyzes data the
attacker supplied themselves. It becomes dangerous the moment auth, state or
stored data are added. Recommendation: pin `allow_origins` to the real
deployment origin and keep `allow_credentials=False` (it already is).

### 1.8 PII / data-handling notes — LOW (informational)

  - Customer emails are used only internally for counts (unique_customers,
    repeat rate, cohorts); they NEVER appear in the API response. Verified.
  - Buyer questions DO flow into the response (analytics.questions), are
    quoted verbatim in next_product.evidence, and are sent to the LLM
    provider (OpenRouter) when an API key is configured. That is the
    product's stated design (questions as demand signals), but operators
    should treat buyer messages as potentially personal data.
  - Parser warnings echo raw cell values (dates/prices); they reach the UI
    through esc(), so no injection, but they can leak odd input formats.

### 1.9 Frontend-only validations — LOW (informational)

static/app.js `handleFile` checks extension/size client-side. These are UX
checks only — the server re-validates both (extension allowlist, 5MB cap),
so a crafted client cannot bypass them.

---

## 2. Fixes applied (this review)

| # | File | Change |
|---|------|--------|
| 1 | static/app.js | `csvEscape` neutralizes CSV formula injection (`= + - @ tab CR` prefix -> `'`) |
| 2 | main.py | JSON `csv_text` capped at 5MB (was unbounded) |
| 3 | main.py | Security headers middleware: CSP, nosniff, X-Frame-Options DENY, Referrer-Policy |

## 3. Verification

    .venv/bin/python -m pytest tests/ -q   -> 223 passed (before and after)

Runtime smoke checks (TestClient):
  - GET /                        -> 200, CSP + nosniff + frame headers present
  - POST /api/sample/analyze     -> 200, CSP header present
  - POST /api/analyze 6MB JSON   -> 400 (cap enforced)
  - GET /.env                    -> 404 (not exposed)
  - GET /static/app.js           -> 200, contains the formula guard
  - csvEscape unit checks        -> formula vectors prefixed with ', benign
                                     values byte-identical, quoting intact

## 4. Residual recommendations (not blocking)

  1. Pin CORS origins to the production host before deploying publicly.
  2. Add rate limiting / auth if the app is exposed beyond a trusted demo.
  3. If buyer questions are sensitive, add a toggle to redact them from the
     LLM payload.
  4. Serve over HTTPS with HSTS once behind a real domain.
  5. Re-run `pytest tests/ -q` in CI and add a test asserting `/.env` 404s
     and the JSON body cap, to keep these properties from regressing.
