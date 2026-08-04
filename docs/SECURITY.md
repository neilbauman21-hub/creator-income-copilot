# SECURITY REVIEW — Creator Income Copilot

Date: 2026-08-04 (review pass 2)
Scope: main.py, core/*.py (parser, models, report, analytics, analytics2,
insights_extra, llm, promo, recommender), core/parsers/*.py (shopify, ko_fi,
lemon), static/app.js, static/index.html.
Verification baseline: 226/226 tests green before and after this pass.

---

## Summary

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1 | CSV formula injection in report download | HIGH | FIXED (pass 1) + hardened (pass 2) |
| 2 | XSS via frontend innerHTML | HIGH | NOT VULNERABLE (verified, esc() at all sinks) |
| 3 | Secrets exposure (.env) | HIGH | NOT VULNERABLE (verified) |
| 4 | File upload abuse / path traversal | MEDIUM | NOT VULNERABLE (verified) |
| 5 | SSRF | HIGH | NONE (verified) |
| 6 | Unbounded request body read before size cap | MEDIUM | FIXED (pass 2 — new) |
| 7 | JSON body size cap bypass | MEDIUM | FIXED (pass 1) |
| 8 | CORS wildcard | LOW | Informational |
| 9 | PII / data-handling notes | LOW | Informational |
| 10 | Frontend-only validations | LOW | Informational |

---

## 1. Findings

### 1.1 CSV formula injection in report download — HIGH (FIXED + hardened)

Location: static/app.js — `csvEscape()` / `buildReportCsv()` (report CSV
download feature).

Product names come straight from the uploaded CSV (untrusted input) and are
written verbatim into the downloaded report CSV. A product name beginning with
`=`, `+`, `-`, `@`, tab or CR is interpreted by Excel / LibreOffice / Google
Sheets as a formula or DDE link when the file is opened:

  =HYPERLINK("http://attacker/x","click")     -> hyperlink spawn
  +cmd|'/C calc'!A0                            -> DDE command execution (legacy)
  @SUM(A1)                                     -> formula execution
  -2+3                                         -> formula execution

Fix (pass 1): `csvEscape` prefixes a single quote `'` to any field whose
first character is `=`, `+`, `-`, `@`, tab or CR (applied before quoting, so
the apostrophe lands inside the quoted field).

Hardening (pass 2, this review): the guard regex was widened from
`/^[=+\-@\t\r]/` to `/^\s*[=+\-@]/` so fields with LEADING WHITESPACE before
the formula character are also neutralized (e.g. `" =cmd|..."`, `"\t=x"`).
Some spreadsheet apps trim leading whitespace before re-parsing a cell, which
would otherwise resurrect the formula. Benign values remain byte-identical.

Verified with node against 16 vectors: all formula variants (incl. space/tab/
CR/newline-prefixed) get the apostrophe; benign fields are unchanged; CSV
quoting for commas/quotes/newlines is intact.

Decision note — the CSV *parsers* (core/parser.py, core/parsers/*) were NOT
modified: they never emit CSV, they produce JSON. Product names are HTML-
escaped client-side for display, and the only CSV output point is the
client-side report download, where the guard lives. Sanitizing at parse time
would corrupt displayed product names and break data fidelity (tests assert
product names round-trip exactly).

### 1.2 XSS via innerHTML in app.js — NOT VULNERABLE (verified)

Location: static/app.js — all render* functions.

Every API-data injection point was audited. An `esc()` helper (OWASP set
`& < > " '`) exists and is applied at all 10 sinks:

  renderKpis        -> esc() on label/value/sub          (safe)
  renderTopProducts -> esc(p.name) in text AND title attr; all numbers via
                       num()/fmtMoney/fmtNum; share width clamped 0-100 (safe)
  renderTrends      -> esc(t.label), esc(t.description)  (safe)
  renderChurn       -> esc(s.product/sev/desc); severity class from a fixed
                       set; signal_type via SIGNAL_LABEL lookup (safe)
  renderInsights    -> esc(t), esc(np.name/rationale/evidence) (safe)
  renderWarnings    -> esc(w)                             (safe)
  emptyItem         -> esc(msg)                           (safe)
  dirBadge          -> direction mapped through fixed ternaries, never raw (safe)
  renderChart       -> labels go to Chart.js canvas, not HTML (safe)

Promo email subject/body, toast, stage titles and period range use
textContent. No `eval`, no `new Function`, no `document.write`, no
`insertAdjacentHTML` anywhere in the codebase. An XSS payload product name
(`<img src=x onerror=alert(1)>`) round-trips through the API as data and is
neutralized at render time.

Defense-in-depth (pass 1, verified still present): Content-Security-Policy on
every response (strict script-src 'self' + chart.js CDN; no
unsafe-inline/unsafe-eval for scripts; style-src 'unsafe-inline' only because
app.js sets inline style attributes), X-Content-Type-Options: nosniff,
X-Frame-Options: DENY, Referrer-Policy: no-referrer.

### 1.3 Secrets exposure (.env) — NOT VULNERABLE (verified)

Location: project root `.env` (OPENROUTER_API_KEY, OPENROUTER_MODEL).

Verified not reachable through the app (smoke-tested with TestClient):
  - GET /.env                      -> 404
  - GET /static/../.env            -> 404 (encoded traversal too)
  - /static/* only serves the static/ directory (mount is pinned; .env is
    not inside it)
  - /api/sample only serves two hardcoded sample paths via int-keyed lookup
  - `/` serves index.html only.
`.gitignore` excludes `.env` (verified: `.env` is untracked in git). The API
key is consumed server-side by core/llm.py and never appears in any response
or in the OpenAPI schema. Rule to keep: never mount the project root
statically, never commit .env.

### 1.4 File upload abuse / path traversal — NOT VULNERABLE (verified)

Location: main.py `_extract_csv`.

The upload filename is used ONLY for an extension allowlist check
(`Path(filename).suffix in {".csv", ".txt"}`). Content is read into memory and
decoded; it is never written to disk and the filename never touches the
filesystem. No path traversal, no arbitrary file write, no archive/decompression
bombs (no archive support). 5MB cap enforced on both upload and JSON paths.
Smoke-tested: store=999/-1/0/abc -> 404/422; store=2 still 200.

### 1.5 SSRF — NONE (verified)

The only outbound network call in the entire codebase is core/llm.py ->
`httpx.post` to the hardcoded OpenRouter endpoint
(https://openrouter.ai/api/v1/chat/completions). No user-controlled URL is
ever fetched; the model name comes from an env var, not from request data.
Sample data is read from local files only.

### 1.6 Unbounded request body read before size cap — MEDIUM (FIXED, pass 2)

Location: main.py `_extract_csv`.

The 5MB cap existed, but both input paths read the ENTIRE body into memory
BEFORE checking it:
  - multipart: `data = await upload.read()` buffered the whole file, then the
    cap was checked;
  - JSON: `await request.json()` buffered + parsed the whole body, then the
    cap was checked.
A client sending a 10GB upload/body would have forced a ~10GB RAM allocation
(memory-exhaustion DoS) before being rejected.

Fix applied (this review):
  1. Early Content-Length gate at the top of `_extract_csv` — a declared body
     larger than MAX_UPLOAD_BYTES + 64KB slack (slack absorbs multipart
     boundary overhead so a legitimately ~5MB file isn't rejected) is refused
     with 400 before any parsing buffers it. A malformed Content-Length is
     ignored and left to the chunked reads.
  2. Multipart file is now read in 64KB chunks with a running cap — rejection
     fires the moment the cap is crossed, so an oversized file is never fully
     buffered.
  3. The JSON body is now streamed through `_read_stream_capped()` (64KB
     chunks, bail at cap+1) and only then `json.loads`-ed — covers clients
     that omit Content-Length (chunked transfer-encoding). 422 semantics for
     non-JSON bodies are preserved.

Residual: a chunked-transfer-encoding multipart request without
Content-Length is still buffered by `request.form()` before the file part can
be capped (Starlette parses the whole multipart body). The file part itself is
then capped, but the envelope is not. Full streaming multipart parsing is out
of scope for this app; the Content-Length gate covers all real clients.

Smoke-tested: 6MB JSON -> 400, 6MB multipart -> 400, lying huge
Content-Length -> 400, valid JSON/multipart/sample flows -> 200.

### 1.7 JSON body size cap bypass — MEDIUM (FIXED, pass 1)

Location: main.py `_extract_csv`.

The 5MB cap was originally enforced only on the multipart path; the JSON
`csv_text` path had no limit. Fixed in pass 1 by capping `csv_text` at
MAX_UPLOAD_BYTES (UTF-8 byte length). The pass-2 chunked body read now makes
this check redundant-but-harmless (the raw body is capped first), and it is
kept as belt-and-braces.

### 1.8 CORS wildcard — LOW (informational)

Location: main.py `app.add_middleware(CORSMiddleware, allow_origins=["*"])`.

For this stateless, auth-less demo the practical impact is nil: there are no
cookies/sessions to abuse, and a cross-origin POST only analyzes data the
attacker supplied themselves. It becomes dangerous the moment auth, state or
stored data are added. Recommendation: pin `allow_origins` to the real
deployment origin and keep `allow_credentials=False` (it already is).

### 1.9 PII / data-handling notes — LOW (informational)

  - Customer emails are used only internally for counts (unique_customers,
    repeat rate, cohorts); they NEVER appear in the API response. Verified.
  - Buyer questions DO flow into the response (analytics.questions), are
    quoted verbatim in next_product.evidence, and are sent to the LLM provider
    (OpenRouter) when an API key is configured. That is the product's stated
    design (questions as demand signals), but operators should treat buyer
    messages as potentially personal data.
  - Parser warnings echo raw cell values (dates/prices); they reach the UI
    through esc(), so no injection, but they can leak odd input formats.
  - FastAPI's auto-generated /docs and /openapi.json are exposed (default).
    They reveal the API shape but no secrets; disable in production if
    desired.

### 1.10 Frontend-only validations — LOW (informational)

static/app.js `handleFile` checks extension/size client-side. These are UX
checks only — the server re-validates both (extension allowlist, 5MB cap), so
a crafted client cannot bypass them.

---

## 2. Fixes applied (this review, pass 2)

| # | File | Change |
|---|------|--------|
| 1 | main.py | Early Content-Length gate (cap + 64KB multipart slack) before any body parsing |
| 2 | main.py | Multipart file read in 64KB chunks with running cap (was: full buffered read then check) |
| 3 | main.py | JSON body streamed + capped before json.loads (was: request.json() unbounded) |
| 4 | static/app.js | csvEscape formula guard widened: `/^\s*[=+\-@]/` covers leading-whitespace variants |

Verified already in tree from pass 1: csvEscape apostrophe guard, JSON
csv_text cap, security-headers middleware (CSP/nosniff/XFO/Referrer-Policy).

## 3. Verification

    .venv/bin/python -m pytest tests/ -q   -> 226 passed (before and after)

Runtime smoke checks (TestClient, 23/23 passed):
  - GET /.env, /static/../.env, encoded traversal  -> 404
  - CSP (script-src 'self', no unsafe-eval/inline), nosniff, XFO DENY present
  - POST /api/analyze 6MB JSON / 6MB multipart      -> 400
  - POST /api/analyze lying huge Content-Length     -> 400 (early gate)
  - valid JSON + multipart + sample flows           -> 200
  - store=999/-1/0/abc                              -> 404/422 (no traversal)
  - XSS product name `<img src=x onerror=alert(1)>` -> API 200, payload intact
    in JSON (neutralized only at render time by esc())

csvEscape unit checks (node, 16+ vectors):
  - =cmd / +cmd / -2+3 / @SUM  -> prefixed with '
  - " =cmd", tab/CR/newline-prefixed variants -> prefixed (pass-2 hardening)
  - benign values byte-identical; comma/quote/newline quoting intact

## 4. Residual recommendations (not blocking)

  1. Pin CORS origins to the production host before deploying publicly.
  2. Add rate limiting / auth if the app is exposed beyond a trusted demo
     (each /api/analyze can trigger an LLM call -> cost-amplification).
  3. If buyer questions are sensitive, add a toggle to redact them from the
     LLM payload.
  4. Serve over HTTPS with HSTS once behind a real domain; consider disabling
     /docs and /openapi.json in production.
  5. Add SRI hashes for the Chart.js CDN script (script-src currently trusts
     cdn.jsdelivr.net wholesale).
  6. Add regression tests asserting: `/.env` 404s, the body-cap 400s, and the
     csvEscape formula vectors — so these properties don't regress.
