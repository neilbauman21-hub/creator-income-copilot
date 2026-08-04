#!/bin/bash
# Wave 1.5: frontend + sample data (independent of wave 1 python modules)
cd ~/creator-income-copilot
HERMES=~/.hermes/hermes-agent/venv/bin/hermes
PROJ=~/creator-income-copilot

# Agent G: sample data CSV
nohup $HERMES chat -q "You are a coding subagent building part of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md (especially the 'sample_data/payhip_sample.csv' section) and $PROJ/core/models.py to understand the SaleRecord fields the parser will map onto.
YOUR TASK: write $PROJ/sample_data/payhip_sample.csv — a realistic Payhip-style orders export for a fictional digital products store ('StudioNova — Notion templates & ebook shop'). Requirements from SPEC: ~120 orders over the last 60 days; 6 products (mix of Notion templates, an ebook/PDF, a preset/bundle pack); some refunds (ONE product with >10% refund rate — use 'Refunded' column or status); USD currency; Payhip-style headers (Order ID, Order Date, Product, Price, Currency, Qty, Buyer email, Status, Buyer question — adapt names to what Payhip actually uses); ~15 rows with buyer questions in a question/notes column, a few of which hint at a MISSING product (demand signal, e.g. 'Do you make templates for wedding planners?', 'Would you consider a course?', 'Can you do a bundle with all the templates?'). Dates must be spread realistically across the last 60 days with some growth trend. Prices realistic ($9-$49). Make it parse cleanly — no weird quoting, UTF-8, commas inside quoted fields OK.
VERIFY: cd $PROJ && .venv/bin/python -c \"import csv; rows=list(csv.DictReader(open('sample_data/payhip_sample.csv'))); print('rows:', len(rows)); print('headers:', list(rows[0].keys())); print('sample:', rows[0])\"
Do NOT create files outside sample_data/. Report: file written + verification output." -t terminal,file --source hackathon-wave15 > build_logs/wave15_sample.log 2>&1 &

# Agent F: frontend dashboard
nohup $HERMES chat -q "You are a coding subagent building the FRONTEND of the 'Creator Income Copilot' hackathon project at $PROJ.
FIRST: read $PROJ/SPEC.md (especially the 'static/' section) and $PROJ/core/models.py to learn the EXACT JSON API contract (AnalyzeResponse shape: analytics{total_revenue, total_orders, avg_order_value, repeat_purchase_rate, top_products[{name,units,revenue,share_pct,refunds,avg_price,momentum,momentum_pct}], revenue_by_day[{date,revenue,orders}], trends[{label,direction,magnitude_pct,description}], churn_signals[{product,signal_type,severity,description}], questions[]}, insights{insights[], promo_email{subject,body}, next_product{name,rationale,evidence}, used_fallback}, warnings[]).
YOUR TASK: write $PROJ/static/index.html, $PROJ/static/app.js, $PROJ/static/style.css — a polished dark-theme single-page dashboard, no build step, Chart.js 4.x via CDN. Sections per SPEC: header with product name 'Creator Income Copilot' + tagline; upload zone (drag-drop + file picker + 'Try sample data' button); KPI cards (revenue, orders, avg order value, repeat purchase rate); revenue line chart from revenue_by_day + top-products ranked list with share bars; trends + churn signals with badges (up=green, down=red, flat=gray; severity chips low/medium/high); AI panel: insights list, promo email (subject + body + Copy button), next-product card (name, rationale, evidence); warnings list if non-empty; loading overlay with staged status text ('Parsing CSV...', 'Crunching numbers...', 'Generating AI insights...'). app.js: fetch('/api/analyze', FormData with file) or POST /api/sample/analyze, render everything, graceful error toast. Must look modern and professional — this is the hackathon demo surface.
VERIFY: node --check static/app.js (find node: which node || ls /opt/homebrew/bin/node) after writing.
Do NOT create files outside static/. Report: files written + JS syntax check result." -t terminal,file --source hackathon-wave15 > build_logs/wave15_frontend.log 2>&1 &

echo "Wave 1.5 spawned: sample data + frontend"
