# Creator Income Copilot

Income intelligence for digital-product creators. Upload your sales CSV
(Payhip / Gumroad / generic) and get back, in seconds:

- **Analytics report** — revenue, orders, avg order value, repeat-purchase
  rate, revenue-by-day chart data, top products with share and momentum,
  trend detection, and churn signals (refund spikes, low repeat rates,
  slowing sales).
- **AI insights** — a plain-language summary of what's working and what's not.
- **A drafted promo email** — ready to copy into your newsletter, built around
  your real numbers (revenue, units, momentum).
- **A "what to build next" recommendation** — grounded in your sales mix and
  the actual questions buyers left on orders.

Built for the lablab.ai NativeBuilder hackathon (Aug 3–10, 2026). No login,
no database — every request is stateless. Python 3.11 + FastAPI, vanilla
JS dashboard with Chart.js, OpenRouter for LLM insights with a deterministic
heuristic fallback so the demo works even with no API key.

## Quickstart

Requires Python 3.11+.

```bash
cd creator-income-copilot

# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) configure the LLM — see ".env setup" below.
#    The app works without this; it just uses heuristic fallback.

# 4. Run the server
uvicorn main:app --port 8000
```

Open http://localhost:8000 — you'll see the dashboard.

Run the test suite (no server needed):

```bash
python3 -m pytest tests/ -q
```

## Demo flow (sample data)

1. Start the server (`uvicorn main:app --port 8000`).
2. Open http://localhost:8000.
3. Click **"Try sample data"** on the dashboard — this runs the built-in
   sample (`sample_data/payhip_sample.csv`, ~120 orders over 60 days for a
   fictional "StudioNova" Notion-template & ebook shop) through the full
   pipeline: parse → analytics → insights → promo email → next-product rec.
4. Watch the dashboard populate: KPI cards, revenue line chart, top-product
   share bars, trend/churn badges, and the AI panel (insights, promo email
   with a Copy button, next-product card).
5. To try your own file, drag a Payhip/Gumroad sales export CSV onto the
   upload zone (or use the file picker). Max 5 MB, `.csv`/`.txt` only.

You can also trigger the sample pipeline from the API directly:

```bash
curl -X POST http://localhost:8000/api/sample/analyze
```

## API endpoints

| Method | Path                 | Description                                                              |
|--------|----------------------|--------------------------------------------------------------------------|
| GET    | `/`                  | Serves the dashboard (`static/index.html`).                              |
| GET    | `/static/*`          | Static assets (CSS/JS).                                                  |
| POST   | `/api/analyze`       | Analyze a sales CSV. Accepts multipart `file` upload OR JSON body `{"csv_text": "..."}`. Returns `AnalyzeResponse`. 400 on unparseable CSV, 422 on missing/invalid input. |
| GET    | `/api/sample`        | Downloads `sample_data/payhip_sample.csv` as an attachment.              |
| POST   | `/api/sample/analyze`| Runs the built-in sample through the full pipeline.                      |

`AnalyzeResponse` shape:

```json
{
  "analytics": { "...AnalyticsReport..." },
  "insights":  { "insights": ["..."], "promo_email": {"subject": "...", "body": "..."}, "next_product": {"name": "...", "rationale": "...", "evidence": "..."}, "used_fallback": false },
  "warnings":  ["...parser warnings, if any..."]
}
```

Example: analyze a CSV file directly:

```bash
curl -F "file=@sample_data/payhip_sample.csv" http://localhost:8000/api/analyze
```

## LLM fallback note

AI insights are generated via the OpenRouter API. When `OPENROUTER_API_KEY`
is missing, empty, or the LLM call times out / returns invalid JSON, the app
**never fails** — it transparently falls back to deterministic heuristics
(rule-based insights, a template promo email, and a rule-based next-product
recommendation built from your report numbers and buyer questions). The
response's `insights.used_fallback` field tells you which path served it.

So: the demo is fully functional with zero configuration, and gets smarter
(open-ended insights) once you add a key.

## .env setup

The app reads `OPENROUTER_API_KEY` from the environment, via a `.env` file
(`python-dotenv`). Create `.env` in the project root:

```bash
cp .env.example .env    # if you have one, otherwise create it manually:
```

```bash
# .env  (never commit this file)
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxx
```

Optional: choose a different model via `OPENROUTER_MODEL` (default
`google/gemini-2.0-flash-001`):

```bash
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
```

Get a key at https://openrouter.ai/keys. The key is only used at request
time — it is read from the environment, never sent to the browser, and
never logged.

## Deployment

- **Live demo** — https://creator-income-copilot-98165680580.us-central1.run.app
  (Google Cloud Run, free tier, always-on URL). AI insights use the provider
  chain: OpenRouter → Vertex AI (Gemini) → ZEN fallback → heuristic, so the
  demo works even with zero LLM credits.
- **Docker** — `docker build -f deploy/Dockerfile -t creator-income-copilot .`
  then `docker run -p 8000:8000 --env-file .env creator-income-copilot`.
  The container listens on `$PORT` (default 8000), so it works on Render,
  Fly.io, Railway, etc. as-is.
- **Render** — push to GitHub, then use the blueprint at `deploy/render.yaml`
  ("New > Blueprint"). It builds with `pip install -r requirements.txt` and
  starts with `uvicorn main:app --host 0.0.0.0 --port $PORT`. Set
  `OPENROUTER_API_KEY` in the service environment when prompted (optional).

### Cloud Run (this project)

```bash
# One-time: enable APIs
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com aiplatform.googleapis.com

# Grant the runtime service account Vertex AI access (for real AI insights)
SA=$(gcloud run services describe creator-income-copilot --region us-central1 \
  --format='value(spec.template.spec.serviceAccountName)')
gcloud projects add-iam-policy-binding $GCP_PROJECT \
  --member="serviceAccount:$SA" --role="roles/aiplatform.user" --quiet

# Deploy (builds from source, sets env vars)
gcloud run deploy creator-income-copilot --source . --region us-central1 \
  --allow-unauthenticated --memory 512Mi --max-instances 1 \
  --set-env-vars "OPENROUTER_API_KEY=$OPENROUTER_API_KEY,OPENROUTER_MODEL=$OPENROUTER_MODEL"
```

Vertex AI env overrides: `VERTEX_MODEL` (default `gemini-2.5-flash`),
`VERTEX_REGION` (default `us-central1`). The project is auto-detected from
`GOOGLE_CLOUD_PROJECT` (set by Cloud Run).

## Project layout

```
creator-income-copilot/
  core/            # parser, analytics, llm, report, promo, recommender, models
  static/          # dashboard (index.html, app.js, style.css)
  sample_data/     # payhip_sample.csv (built-in demo data)
  tests/           # pytest suite (parser, analytics, llm, api)
  deploy/          # Dockerfile + render.yaml
  main.py          # FastAPI app
  requirements.txt
  README.md
```

## Tests

```bash
python3 -m pytest tests/ -q
```

Covers: Payhip/Gumroad/generic CSV parsing + bad-row handling, hand-computed
analytics numbers, LLM fallback behavior, and the API contract (sample
analyze 200 + schema, bad CSV 400, missing file 422).
