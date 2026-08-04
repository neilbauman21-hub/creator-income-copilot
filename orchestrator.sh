#!/bin/bash
# Master orchestrator: waits for wave 1/1.5 to finish, then runs wave 2a (llm),
# then wave 2b (report + main in parallel), then wave 3 (polish/docs/deploy).
cd ~/creator-income-copilot
HERMES=~/.hermes/hermes-agent/venv/bin/hermes
PROJ=~/creator-income-copilot
LOG=build_logs/orchestrator.log

log() { echo "[$(date +%H:%M:%S)] $1" | tee -a $LOG; }

# Find hermes agent processes (chat -q with --source hackathon-*)
wait_for_agents() {
  local label="$1"
  log "Waiting for $label to finish..."
  while pgrep -f "hermes chat -q" > /dev/null 2>&1; do
    sleep 15
  done
  log "$label done."
}

wait_for_agents "wave1 + wave15"

# Verify wave 1 outputs exist
log "Verifying wave 1 artifacts..."
ls -la core/ | tee -a $LOG
if [ ! -f core/promo.py ] || [ ! -f core/recommender.py ] || [ ! -f core/analytics.py ] || [ ! -f core/parser.py ]; then
  log "ERROR: missing wave 1 artifacts!"; exit 1
fi

# Wave 2a: llm.py alone (report.py depends on it)
log "Launching Wave 2a: llm.py"
nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md, $PROJ/core/models.py, $PROJ/core/promo.py and $PROJ/core/recommender.py (they ALREADY exist — read them, do NOT modify).
YOUR TASK: write $PROJ/core/llm.py exactly per the SPEC 'core/llm.py' section. Implement generate_insights(report: AnalyticsReport, api_key: str | None) -> LLMInsights and heuristic_insights(report) -> LLMInsights (exported). No api_key → immediately return heuristic fallback (3-6 insights from report numbers, promo via core.promo.build_promo_email, next product via core.recommender.recommend_next_product, used_fallback=True), NEVER raise. With key → POST https://openrouter.ai/api/v1/chat/completions, model from env OPENROUTER_MODEL (default google/gemini-2.0-flash-001), response_format json_object, instruct EXACTLY LLMInsights schema, 25s timeout (httpx), any exception/invalid JSON → heuristic fallback. Use python-dotenv load_dotenv(). Also write $PROJ/tests/test_llm.py: no-key fallback valid with used_fallback=True; heuristic on constructed report with real numbers; empty report no raise. NEVER call network in tests.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_llm.py -q — iterate until green.
Do NOT modify core/models.py, core/promo.py, core/recommender.py. Report: files written + final pytest output." -t terminal,file --source hackathon-wave2 > build_logs/wave2_llm.log 2>&1 &

wait_for_agents "wave2a llm"
log "Wave 2a complete."

# Wave 2b: report.py + main.py in parallel (both need llm.py)
log "Launching Wave 2b: report.py + main.py"
nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md, $PROJ/core/models.py, $PROJ/core/analytics.py and $PROJ/core/llm.py (they ALREADY exist — read them, do NOT modify).
YOUR TASK: write $PROJ/core/report.py exactly per the SPEC 'core/report.py' section. Implement build_analyze_response(records: list[SaleRecord], warnings: list[str]) -> AnalyzeResponse — orchestration: analytics.build_report(records) → llm.generate_insights(report, os.getenv('OPENROUTER_API_KEY')) → assemble AnalyzeResponse with warnings passthrough. load_dotenv() at import. Import ONLY core.models, core.analytics, core.llm, os.
VERIFY: cd $PROJ && .venv/bin/python -c \"from core.report import build_analyze_response; from core.models import SaleRecord; from datetime import datetime; recs=[SaleRecord(order_id='1', date=datetime(2026,6,1), product='A', price=10.0, quantity=2), SaleRecord(order_id='2', date=datetime(2026,6,2), product='B', price=5.0)]; r=build_analyze_response(recs, ['ok']); print('revenue:', r.analytics.total_revenue); print('insights:', len(r.insights.insights)); print('warnings:', r.warnings)\" — should print revenue 25.0, insights >= 3, warnings ['ok'].
Do NOT modify core/models.py, core/analytics.py, core/llm.py. Report: files written + sanity check output." -t terminal,file --source hackathon-wave2b > build_logs/wave2b_report.log 2>&1 &

nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md, $PROJ/core/models.py, $PROJ/core/report.py (exists — read it, do NOT modify).
YOUR TASK: write $PROJ/main.py exactly per the SPEC 'main.py' section. FastAPI app: GET / serves static/index.html; POST /api/analyze accepts multipart 'file' (CSV) OR JSON body {'csv_text': '...'}, 5MB cap, only .csv/.txt; returns AnalyzeResponse (200) or {'detail': ...} (400 unparseable); GET /api/sample returns sample_data/payhip_sample.csv as attachment; POST /api/sample/analyze runs built-in sample through full pipeline (read sample_data/payhip_sample.csv, parse via core.parser.parse_csv, then core.report.build_analyze_response); mount /static; CORS open; load_dotenv(). Also write $PROJ/tests/test_api.py: sample analyze 200 + schema check, bad CSV 400, missing file 422 (TestClient). IMPORTANT: if sample_data/payhip_sample.csv doesn't exist yet, create a tiny inline CSV fixture in the test — do NOT depend on sample_data being present.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_api.py -q — iterate until green.
Do NOT modify core/*. Report: files written + final pytest output." -t terminal,file --source hackathon-wave2b > build_logs/wave2b_main.log 2>&1 &

wait_for_agents "wave2b report+main"
log "Wave 2b complete."

# Wave 3: docs, deploy, README, submission — run with remaining agents in parallel
log "Launching Wave 3: docs + deploy"
nohup $HERMES chat -q "You are a coding subagent for the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md and skim the existing code (core/, main.py).
YOUR TASK: write $PROJ/requirements.txt (fastapi, uvicorn[standard], python-dotenv, pydantic, pytest, httpx) and $PROJ/deploy/Dockerfile + $PROJ/deploy/render.yaml for a FastAPI app (python 3.11-slim, pip install -r requirements.txt, uvicorn main:app --host 0.0.0.0 --port \$PORT). Also write $PROJ/README.md (what it is, quickstart: venv setup, uvicorn main:app --port 8000, demo flow with sample data, API endpoints, LLM fallback note, .env setup with OPENROUTER_API_KEY).
Do NOT modify any existing .py files. Report: files written." -t terminal,file --source hackathon-wave3 > build_logs/wave3_docs.log 2>&1 &

nohup $HERMES chat -q "You are a coding subagent for the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md and the code (core/, main.py, static/).
YOUR TASK: write $PROJ/HACKATHON_SUBMISSION.md — the lablab.ai submission pitch. Include: (1) Product name + one-liner; (2) Problem + clearly defined target user (digital product sellers on Payhip/Gumroad); (3) How it works (upload sales CSV → analytics + AI insights + promo email + next-product recommendation) with the demo flow step-by-step; (4) Differentiation vs generic BI tools (agentic recommendations, promo copy, next-product idea from customer questions); (5) Tech stack + why it's AI-native (OpenRouter LLM + graceful heuristic fallback); (6) Post-hackathon viability (pricing, who pays, why). Make it persuasive and specific. ~600-800 words.
Do NOT modify any code. Report: file written." -t terminal,file --source hackathon-wave3 > build_logs/wave3_submission.log 2>&1 &

wait_for_agents "wave3 docs+submission"
log "Wave 3 complete."

# Final verification
log "=== FINAL VERIFICATION ==="
cd $PROJ && .venv/bin/python -m pytest tests/ -q 2>&1 | tee -a $LOG
log "All waves complete. See build_logs/ for details."
