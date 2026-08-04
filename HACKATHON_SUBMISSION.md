# Creator Income Copilot

**One-liner:** Upload your sales CSV and get a full revenue breakdown, an AI-written promo email, and a data-backed answer to "what should I build next?" — in under 10 seconds.

## The problem, and who it's for

Millions of solo creators sell digital products — Notion templates, ebooks, preset packs, courses — through Payhip and Gumroad. They are not analysts. They already have the data (their platform's CSV export) but no time, no SQL, and no BI budget to turn it into decisions. Generic dashboards (Metabase, Power BI, Looker) answer "what happened?" with charts, then leave the creator staring at the screen wondering what to *do*. The three questions that actually keep them up at night: Is my store growing? What should I promote? What should I build next? Off-the-shelf BI answers none of them.

Creator Income Copilot is built for exactly that user: the solo digital-product seller who checks their payout dashboard more often than their bank account, and needs a second brain — not another chart.

## How it works

Upload → insight → action, in four stages:

1. **Upload.** Drag a Payhip or Gumroad orders CSV onto the page, or click "Try sample data". No login, no signup, nothing to configure. `POST /api/analyze` (or `/api/sample/analyze`) accepts the file (≤5MB, .csv/.txt).
2. **Parse.** The parser auto-detects the schema — Payhip, Gumroad, or generic — via synonym-based header matching ("Order Date" / "Created At" / "Date" → date). Bad rows become warnings, never crashes.
3. **Analyze.** Deterministic analytics compute total revenue, orders, average order value, repeat-purchase rate, a daily revenue curve (Chart.js), top products with revenue share, 7-day momentum, and churn signals (refund rate >10%, repeat rate <15%, a former top product slowing down).
4. **Act.** The report goes to an LLM via OpenRouter (gemini-2.0-flash, JSON-schema-constrained output) which produces: 3–6 data-grounded insights; a promo email (subject + body) for the top product built from real numbers; and a next-product recommendation that quotes actual customer questions as demand evidence.

**Demo flow (2 minutes):** open the app → click "Try sample data" → watch the staged loading overlay → KPI cards populate → the revenue chart draws → trends show green/red/flat badges → the AI panel appears with insights, a promo email ready to copy, and a "build this next" card citing a real buyer question. Total time from blank page to a complete, actionable business review: under 10 seconds.

## Why this isn't a BI tool

BI tools describe; this one decides. Three things generic dashboards cannot do:

- **Agentic recommendations.** The output is a prioritized action list, not a chart: *"This product's refund rate is 28% — fix the download experience"*, *"Revenue is up 41% week-over-week — promote now."*
- **Ready-to-send promo copy.** The email subject and body are generated from actual revenue/units/momentum figures and delivered with a one-click Copy button — it converts analysis into revenue directly.
- **Next-product ideation from customer questions.** Buyer questions in the export are treated as free demand research — the one data source generic BI never reads. *"Do you have a meal-planning template?"* becomes a concrete product recommendation with the question quoted verbatim as evidence.

## Tech stack — AI-native by design

Python 3.11, FastAPI + uvicorn, Pydantic v2, vanilla JS + Chart.js, zero database. The AI layer isn't a bolted-on chatbot: the LLM is the output stage of a typed pipeline, constrained to emit exactly the `LLMInsights` schema and validated by Pydantic on every response. The demo works **keyless**: if `OPENROUTER_API_KEY` is missing, the call times out (25s), or the model returns invalid JSON, a deterministic heuristic fallback — rule-based insights, template promo email, keyword-matched next-product — serves the same schema, flagged via `used_fallback`. The product degrades gracefully instead of failing, and the AI path costs pennies per run. Stateless per request: no user data is ever stored.

## Post-hackathon viability

**Who pays:** the same solo creators — Gumroad alone claims 2M+ sellers; Payhip and Etsy digital sellers add millions more. **Why they pay:** this produces deliverables that directly drive sales (promo email) and revenue (next-product roadmap), priced at $9/month — less than the price of a single product, and self-justifying the moment one recommendation lands. **Cost structure:** each analysis is a small JSON payload and a short LLM completion — pennies — leaving healthy margins at scale. **Roadmap:** platform API sync (one-click Gumroad/Payhip connect), weekly email digests, promo A/B variants, multi-store support. Revenue intelligence for the long tail of creators — currently the most underserved, most numerous software market there is.
