#!/bin/bash
# Wave 1b: recommender agent (llm.py in Wave 2 depends on it)
cd ~/creator-income-copilot
HERMES=~/.hermes/hermes-agent/venv/bin/hermes
PROJ=~/creator-income-copilot

nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md and $PROJ/core/models.py (the frozen data contract).
YOUR TASK: write $PROJ/core/recommender.py exactly per the SPEC 'core/recommender.py' section. Implement recommend_next_product(report: AnalyticsReport) -> NextProduct (deterministic: dominant product category + signals from report.questions via keyword matching — 'template' → new template product, 'pdf' → pdf, 'pack'/'bundle' → bundle, 'course'/'tutorial' → course, else category extension. Name + rationale + evidence citing a real customer question if one matches. Handle empty questions and empty top_products gracefully) and build_recommender_prompt(report) -> str (LLM prompt text embedding report JSON). Import ONLY from core.models + stdlib.
VERIFY: cd $PROJ && .venv/bin/python -c \"from core.recommender import recommend_next_product; from core.models import AnalyticsReport, ProductStats; r=AnalyticsReport(total_revenue=1200.0, questions=['Do you have a template for wedding planners?'], top_products=[ProductStats(name='Notion Template Pack', revenue=500.0, units=25)]); p=recommend_next_product(r); print(p.name); print(p.evidence[:150])\"
Do NOT modify core/models.py. Do NOT create files outside your assignment. Report: files written + sanity check output." -t terminal,file --source hackathon-wave1 > build_logs/wave1_recommender.log 2>&1 &

echo "Recommender agent spawned (Wave 1b)"
