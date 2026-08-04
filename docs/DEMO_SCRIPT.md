# Creator Income Copilot — 90-Second Demo Script

For the NativeBuilder hackathon video. Total runtime target: **90 seconds**.
Tone: fast, confident, no dead air. Every scene has a job: show the product, show the
intelligence, show it never breaks.

---

## 0. Before you hit record

1. Start the server: `uvicorn main:app --port 8000` (from the repo root).
2. Open `http://localhost:8000` in a clean Chrome window, **1280x720 or wider**, zoom
   ~90% so the whole dashboard is visible. Pre-load the page so fonts/CDN are cached.
3. **Do NOT configure OPENROUTER_API_KEY.** The demo runs keyless on the heuristic
   engine — that is a feature, not a fallback (it proves the app works anywhere).
4. Close all other tabs. Mute notifications. You have one job: click and talk.

**Golden rule: read numbers off the screen, don't memorize them.** The cheat sheet in
§7 tells you what to expect so nothing surprises you, but point at the live cards.

---

## 1. Scene-by-scene

### Scene 0 — Cold open (0:00–0:08)

| What you do | What you say |
|---|---|
| Wide shot of the landing page. Wave at the upload zone with the cursor. | "Every digital creator has this problem: your sales CSV is a spreadsheet, and your decisions are a guessing game. **Creator Income Copilot** turns that CSV into a full income report — analytics, a promo email, and a plan for what to build next. No login. Nothing stored. Watch." |

Point at: the header, the drop zone ("Drop your sales CSV here").

---

### Scene 1 — Try sample data (0:08–0:22)

| What you do | What you say |
|---|---|
| Click **"Try the sample dataset →"** (the secondary button under the drop zone — or press **S**). | "No CSV on hand? One click — sample data." |
| While the overlay shows, do NOT click anything. Let the stages tick. | "It walks through the pipeline live: parsing the CSV, crunching the numbers, generating insights. A full analysis in a couple of seconds." |

Point at: the loading overlay's three stages
("Parsing CSV... → Crunching numbers... → Generating AI insights...").

> Expected: 120-row StudioNova Payhip export -> dashboard. See §7 for exact numbers.

---

### Scene 2 — The numbers (0:22–0:42)

The dashboard has auto-scrolled to the results. Move top-to-bottom, ~5 seconds each.

| What you do | What you say |
|---|---|
| Point at the **KPI cards** (revenue, orders, avg order value, repeat rate). | "Sixty days of StudioNova's sales: **$2,543 in revenue, 116 orders, 96 customers** — all net of refunds. These are real numbers from the CSV, not estimates." |
| Point at the **revenue line chart** (purple) and the **orders bars** (teal). | "Revenue over time — the purple line is money, the teal bars are orders, same day. See that spike around July 28th? That's a launch day — and the line is still climbing into August." |
| Point at the **top products list** and its share bars. | "Top products by revenue, with their share of the store: the **Mega Bundle leads at $833** — 33% of everything. And each row has a momentum badge." |
| Point at the **green "+42.9%"** badge on Content Planner Pro. | "Content Planner Pro is up 43% in the last week — that's the product that's accelerating." |

---

### Scene 3 — The warnings (0:42–0:55)

| What you do | What you say |
|---|---|
| Point at the **Trends** card (green/red badges). | "Overall revenue is up 27% week-over-week — but look closer: the Mega Bundle, your biggest earner, is down 33%. The trend panel catches that." |
| Point at the **Churn signals** card, specifically **"Minimal Finance Tracker — high refund rate, medium"**. | "Churn signals flag the risks a spreadsheet hides: the Finance Tracker has an **18% refund rate** — above our 10% threshold. And repeat purchases are only at 11%, so this store is leaking customers. These are the warnings that tell a creator *what to fix*, not just what happened." |

---

### Scene 4 — The AI panel (0:55–1:15) — the money shot

| What you do | What you say |
|---|---|
| Scroll to the **AI Copilot** panel. Point at **Key insights**. | "Now the Copilot layer. Insights aren't generic — they're grounded in this exact dataset: best-selling day is **Saturday**, the July cohort is only repeating at 4.6%, so the recommendation is a post-purchase follow-up sequence." |
| Point at the **Next product to build** card. | "And the next product isn't a guess — it's pulled from a **real buyer question** in the data. Someone asked, quote, 'How do I duplicate this template in Notion? Total beginner here' — so the recommendation is a beginner-focused template, with the customer's own words as evidence." |
| Point at the **Draft promo email** card, then **click "Copy email"**. | "And a ready-to-send promo email for the best-seller, built from real revenue and momentum — one click, straight to your clipboard." |
| When the button flips to **"Copied!"**, point at it. | "Copied. You could paste that into Mailchimp right now." |

---

### Scene 5 — It never breaks + your own data (1:15–1:30)

| What you do | What you say |
|---|---|
| Point at the **"heuristic mode"** chip next to the AI Copilot title. | "Notice this chip: 'heuristic mode'. This whole demo is running **with no API key and no internet dependency** — the intelligence engine is built in, so it works anywhere, any time. Drop in an OpenRouter key and it upgrades to a live LLM — same output shape, smarter prose." |
| Click **"← New upload"**, then drag a real CSV onto the drop zone (or click **Upload CSV** / press **U**). | "And your own data? Drop any export — **Payhip, Gumroad, Shopify, Ko-fi, Lemon Squeezy, or generic** — the schema is auto-detected. Five megabytes, no login, nothing stored. Thirty seconds from CSV to decisions." |
| Hold on the loading overlay for 1 second. | "Creator Income Copilot." (fade out) |

---

## 2. Timing cheat sheet

```
Scene 0  cold open          0:00 - 0:08   8s
Scene 1  try sample data    0:08 - 0:22  14s
Scene 2  numbers            0:22 - 0:42  20s
Scene 3  warnings           0:42 - 0:55  13s
Scene 4  AI panel           0:55 - 1:15  20s
Scene 5  resilience+upload  1:15 - 1:30  15s
                                   TOTAL 90s
```

If you run long anywhere, cut Scene 5's upload demo (keep the heuristic-mode chip —
it's the line that separates this from every other "AI dashboard").

---

## 3. Exact expected values — StudioNova sample (store 1)

Verified by running the real pipeline (heuristic mode). Numbers render live, so read
them off the screen; these are what you should see:

| Panel | Expected |
|---|---|
| Period | 2026-06-05 → 2026-08-03 |
| Total revenue | $2,543.85 (net of refunds) |
| Orders / customers | 116 orders, 96 unique customers |
| Avg order value | $21.93 |
| Repeat purchase rate | 11.5% |
| Top product | StudioNova Mega Bundle — $833.00, 17 units, 32.8% share, **down 33.3%** |
| Rising product | Content Planner Pro — $665.00, **up 42.9%** |
| Overall trend | Up +26.8% (last 7d $548.96 vs prior 7d $432.98) |
| Churn signal 1 | Minimal Finance Tracker — high refund rate, 18.2% (2 of 11 orders), medium |
| Churn signal 2 | All products — low repeat rate 11.5%, low |
| Churn signal 3 | Mega Bundle — slowing sales (was top, down 33%), medium |
| Deep-dive insights | July cohort (65 customers) repeats at 4.6%; Aug cohort no repeats yet; best day Saturday ($56.11/day avg); slowest Thursday ($34.75/day) |
| Promo email subject | "StudioNova Mega Bundle — All Templates + Ebook is your $833 best-seller — see why" |
| Next product | Template recommendation citing the real question "How do I duplicate this template in Notion? Total beginner here, sorry!" |
| Warnings card | Hidden (0 warnings — sample parses clean) |

---

## 4. Alternate paths (only if something misbehaves)

- **Chart.js CDN blocked (offline venue):** the chart panel shows "Chart.js failed to
  load" but every other panel renders. Don't panic — pivot to KPI + AI panel and say
  "the chart needs a CDN fetch, everything else is self-contained."
- **Sample button unresponsive:** press **S** (keyboard shortcut) or reload the page.
- **LLM key is set by accident and the call hangs:** the 25-second timeout falls back
  to heuristics automatically — say "watch — even if the model stalls, the built-in
  engine takes over." The heuristic chip will appear. (Don't do this live; test first.)
- **Uploaded file rejected:** expected toasts: wrong extension ("Please upload a .csv or
  .txt file.") or >5MB. Use them as a *feature* demo if you need filler: "see — it
  validates your file before it ever touches the pipeline."

---

## 5. Optional: second store (only if you have 15 spare seconds)

The backend ships a second fictional store — **PixelPerch** (Gumroad-style presets
store, 80 orders, 5 products, $1,203 net revenue). The frontend demo uses store 1, but
you can show diversity via the API or a bookmarklet:

```
curl -X POST "http://localhost:8000/api/sample/analyze?store=2"
```

Story beat: "a different store, a different platform — same pipeline." Skip if you're
over 90s.

---

## 6. What the judges should remember

1. **CSV in → decisions out.** One upload produces KPIs, trends, churn signals, a promo
   email, and a next-product recommendation.
2. **The AI is grounded.** Insights, email, and the recommendation cite *real numbers
   and real buyer questions* from the upload — never invented figures.
3. **It cannot fail on stage.** Keyless heuristic engine, graceful LLM degradation,
   stateless in-memory processing, per-panel error isolation.
4. **Zero setup for the user.** No login, no database, no config — open the page and go.

---

## 7. One-line pitch (use in the video description)

> Creator Income Copilot turns a creator's sales CSV into a live income report — with
> churn signals, a drafted promo email, and a data-grounded next-product plan — in
> under 10 seconds, with no login and no stored data.
