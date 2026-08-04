#!/bin/bash
# Wave 2: llm.py, report.py, main.py — depend on Wave 1 modules. Run AFTER wave 1 completes.
cd ~/creator-income-copilot
HERMES=~/.hermes/hermes-agent/venv/bin/hermes
PROJ=~/creator-income-copilot

# Agent H: llm.py (imports core.promo + core.recommender — must exist)
nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md, $PROJ/core/models.py, $PROJ/core/promo.py and $PROJ/core/recommender.py (they ALREADY exist — read them, do NOT modify).
YOUR TASK: write $PROJ/core/llm.py exactly per the SPEC 'core/llm.py' section. Implement generate_insights(report: AnalyticsReport, api_key: str | None) -> LLMInsights and heuristic_insights(report) -> LLMInsights (exported). No api_key → immediately return heuristic fallback (insights + promo via core.promo.build_promo_email + next product via core.recommender.recommend_next_product), NEVER raise. With key → POST https://openrouter.ai/api/v1/chat/completions, model from env OPENROUTER_MODEL (default google/gemini-2.0-flash-001), response_format json_object, instruct EXACTLY LLMInsights schema, 25s timeout (httpx), any exception/invalid JSON → heuristic fallback with used_fallback=True. heuristic_insights: 3-6 concrete insights from report numbers, used_fallback=True. Use python-dotenv load_dotenv(). Also write $PROJ/tests/test_llm.py: no-key fallback valid LLMInsights with used_fallback=True; heuristic on constructed report with real numbers; empty report no raise. NEVER call network in tests.
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_llm.py -q — iterate until green.
Do NOT modify core/models.py, core/promo.py, core/recommender.py. Do NOT create files outside your assignment. Report: files written + final pytest output." -t terminal,file --source hackathon-wave2 > build_logs/wave2_llm.log 2>&1 &

# Agent I: report.py (imports core.analytics + core.llm — must exist)
nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md, $PROJ/core/models.py, $PROJ/core/analytics.py and $PROJ/core/llm.py (they ALREADY exist — read them, do NOT modify).
YOUR TASK: write $PROJ/core/report.py exactly per the SPEC 'core/report.py' section. Implement build_analyze_response(records: list[SaleRecord], warnings: list[str]) -> AnalyzeResponse — orchestration: analytics.build_report(records) → llm.generate_insights(report, os.getenv('OPENROUTER_API_KEY')) → assemble AnalyzeResponse with warnings passthrough. Use python-dotenv load_dotenv() at import. Import ONLY core.models, core.analytics, core.llm, os.
VERIFY: cd $PROJ && .venv/bin/python -c \"from core.report import build_analyze_response; from core.models import SaleRecord; from datetime import datetime; recs=[SaleRecord(order_id='1', date=datetime(2026,6,1), product='A', price=10.0, quantity=2), SaleRecord(order_id='2', date=datetime(2026,6,2), product='B', price=5.0)]; r=build_analyze_response(recs, ['ok']); print('revenue:', r.analytics.total_revenue); print('insights:', len(r.insights.insights)); print('warnings:', r.warnings)\" — should print revenue 25.0, insights >= 3, warnings ['ok'].
Do NOT modify core/models.py, core/analytics.py, core/llm.py. Do NOT create files outside your assignment. Report: files written + sanity check output." -t terminal,file --source hackathon-wave2 > build_logs/wave2_report.log 2>&1 &

# Agent J: main.py FastAPI app (imports core.report — must exist)
nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md, $PROJ/core/models.py, $PROJ/core/report.py (exists — read it, do NOT modify).
YOUR TASK: write $PROJ/main.py exactly per the SPEC 'main.py' section. FastAPI app: GET / serves static/index.html; POST /api/analyze accepts multipart 'file' (CSV) OR JSON body {'csv_text': '...'}, 5MB cap, only .csv/.txt; returns AnalyzeResponse (200) or {'detail': ...} (400 unparseable); GET /api/sample returns sample_data/payhip_sample.csv as attachment; POST /api/sample/analyze runs built-in sample through full pipeline (read sample_data/payhip_sample.csv, parse via core.parser.parse_csv, then core.report.build_analyze_response); mount /static; CORS open; load_dotenv(). Use core.parser.parse_csv for parsing. Also write $PROJ/tests/test_api.py: sample analyze 200 + schema check, bad CSV 400, missing file 422 (TestClient).
VERIFY: cd $PROJ && .venv/bin/python -m pytest tests/test_api.py -q — iterate until green. (If test_api needs the sample file and it's not ready, create a tiny inline CSV fixture in the test instead — do NOT depend on sample_data being present.)
Do NOT modify core/*. Do NOT create files outside your assignment (main.py + tests/test_api.py). Report: files written + final pytest output." -t terminal,file --source hackathon-wave2 > build_logs/wave2_main.log 2>&1 &

echo "Wave 2 spawned: llm, report, main"
