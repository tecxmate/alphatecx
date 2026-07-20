# Screening & board triage

Covers **Mode 1 (discover)** and **Mode 4 (judge a board/screenshot)**. The goal is to separate a
quietly-accumulated sleeper from a crowded chase or a value trap.

## Contents
1. The Sleeper Score (the core rubric)
2. Discovery funnel (how to build a shortlist)
3. Board / screenshot triage
4. The Avoid Catalog (red-flag patterns, with examples)
5. Thresholds cheat-sheet

---

## 1. The Sleeper Score

Score a candidate against these. The 拓凱 archetype hit ~9/9. Treat 6+ with no hard red flag as a
real candidate; anything with an active red flag (§4) is out regardless of score.

| # | Trait | Green (score) | Data source |
|---|---|---|---|
| 1 | Cheap on **earnings** | P/E < ~20 *with positive, non-collapsed EPS* | `q_valuation` |
| 2 | Reasonable asset value | P/B roughly < 3 (context-dependent) | `q_valuation` |
| 3 | Income cushion | dividend yield ≳ 3% | `q_valuation` |
| 4 | Under-owned | foreign-held % low (e.g. <20%), large room | `twse_foreign_holdings` |
| 5 | **Accumulation into flat price** | foreign net-buy most of last 15–20 sessions while price sat flat | `raw_flow_history` |
| 6 | Not-yet-run | flat base / first-twitch, *not* +30%+ in weeks | `twse_daily_history` |
| 7 | No leverage froth | margin balance tiny vs limit; short ≈ 0 | `twse_margin_balance` |
| 8 | Fundamental inflection | monthly revenue YoY turning up | `monthly_revenue` |
| 9 | Peer/customer confirms | peers/customers show the same inflection | `monthly_revenue` on peers |

**Bonus (not scored, but decisive for conviction):** a near-term catalyst (revenue print ~10th,
earnings, ex-div, spin-off), relative strength on red days, and free optionality (new end-markets).

**The two make-or-break signals**, if you only check two things:
- **#5 accumulation-into-flat-price** — steady foreign net buying while the price is pinned is smart
  money absorbing supply before a breakout. This is the highest-signal trait. Its inverse (foreign
  *distribution into a rising price*) is the strongest sell/avoid tell.
- **#6 not-yet-run** — compute the % move over the last ~4–6 weeks. >30–40% = you're late; the base
  is gone.

---

## 2. Discovery funnel

**Start with `flow_leaders_scan`.** It runs this entire funnel market-wide in one call — it *is* the
Sleeper Score, automated (accumulation-into-flat + cheap + under-owned + no-froth + revenue
inflection), returning ranked hits with `sleeper_score`, `sleeper_flags`, and `triage`. Read the
`sleeper` rows first, then vet the top few by hand (§1) and add the qualitative layer (moat, catalyst,
peer confirmation) it can't see. Pass `date=` to reproduce a past session for a post-mortem. Don't
gate on `min_foreign_z` (a slow grinder has no closing-day z-spike). It is **TWSE-effective** —
coverage needs a harvested price, so most TPEX (上櫃) names won't appear; for a TPEX candidate or a
non-price universe (a theme's supply chain, a peer group, a screenshot), fall back to the **by-hand
funnel** below. `q_screener` only covers the classified AI-supply-chain universe and will NOT surface
petrochem/defense/textile/traditional sleepers, so the by-hand pass still matters.

1. **Pick a universe.** Options: the user's enhanced screener output; a sector list; a limit-up /
   hot board (Mode 4); a theme's supply chain; or a peer group around a name the user likes.
2. **Valuation gate.** `q_valuation` each candidate. Drop: null-P/E (loss-making) unless explicitly
   hunting a cyclical turn; P/E inflated by collapsed earnings (fallen-angel trap — check price vs
   history); story-premium names at 40×+.
3. **Flow gate.** `raw_flow_history` (~18 sessions). Keep names with *net foreign accumulation*,
   especially into a flat price. Drop names foreigners are distributing, and flag the specific
   "foreign selling into a 投信 ramp" pattern (see §4).
4. **Ownership + froth.** `twse_foreign_holdings` (low held % = runway) and `twse_margin_balance`
   (clean = cash-driven).
5. **Structure.** `twse_daily_history` — is it a base or a parabola? Reclaimed MAs? Position in range?
6. **Fundamental inflection.** `monthly_revenue` YoY + triangulate with 2 peers/customers.
7. **Rank** by Sleeper Score, present the shortlist, note each one's catalyst and single biggest risk.

**Meta-lesson from experience:** the cleanest sleepers are often *not* labeled with the hot theme.
拓凱 screened as "sporting goods / composites" at 11× with foreign accumulation precisely because the
market hadn't reclassified it as a "robot/AI" stock yet. When a whole theme's pure-plays are all
40–250× and being distributed, hunt the *adjacent, still-mis-filed* name instead — that's where the
sleeper profile survives.

---

## 3. Board / screenshot triage (Mode 4)

**Start with `scan_limit_board`** — it fetches the live TWSE/TPEX limit-up/down board (EOD) and
triages each hit `sleeper`/`watch`/`chase` with the same rubric, replacing the manual screenshot read.
Use `direction`, `min_pct`, `locked_only`, `min_turnover_twd`, and `date=` for a past session. It
returns *who's at the limit and which are real*; the human judgement below (rotation vs stock-picking,
theme segmentation) is what you add on top. If the user pasted a screenshot of a board the tool can't
reproduce (a different market, an intraday snapshot), fall back to reading it by hand as below.

When triaging the board (tool-returned or by hand):

1. **Is it a rotation event or stock-picking signal?** A board *packed* with one sector (e.g.,
   petrochem + textiles + shipbuilding all limit-up on the same day) is usually a macro **rotation**
   (money leaving semis into traditional), not 60 independent breakouts. Say so — most of the board
   is laggard-chasing, the opposite of a sleeper.
2. **Segment by theme** from the tickers (petrochem, defense/ship, biotech, AI/optical, components,
   textiles, etc.).
3. **Filter out the junk** hard, per the user's criteria:
   - Biotech/pharma lottery (binary, event-driven) — cut.
   - Penny / low-price 補漲 (catch-up) names — cut.
   - Cyclical bounce with null/negative earnings (petrochem trough) — cut for long-term; may be a
     short-term catalyst trade only (see entry_sizing §Short-term).
   - Already-run / AI names that limit-upped because they were *already* hot — cut (extended).
4. **Keep the survivors:** fundamentally sound + was-sleeping + just-moving, ideally with a
   structural (not feedstock/rumor) driver. Verify each with the Sleeper Score.
5. **State the hard truth:** a limit-up board *by definition* contains only names that already woke.
   The best base-breakouts usually *don't* limit-up on day one. Use the board as a **watchlist**, not
   a buy list — note the survivors, then wait for a pullback-and-hold, or find the same theme's name
   that *didn't* limit up yet (the true still-asleep play).

---

## 4. The Avoid Catalog (red-flag patterns)

Each is a hard stop for the long-term sleeper thesis. Recognize them by name.

- **Parabola / consecutive limit-ups.** +30–70% in weeks, or 2–4 straight limit-ups. Example
  pattern: a name up ~74% in five weeks printing an intraday blow-off then reversing. Buying here is
  buying someone else's exit. "Good business" doesn't rescue a vertical entry.
- **Foreign distribution into a 投信/retail ramp.** The *entire* run is driven by 投信
  (investment-trust) buying while foreigners *sell every step up*. Fragile: 投信 support vanishes
  after quarter-end, and foreigners (usually smarter money) are already leaving. A rising price on
  net foreign selling is a distribution top, not accumulation.
- **Fallen-angel P/E trap.** Price is "half off the peak" so it *looks* cheap, but P/E is 30–90×
  and P/B is elevated because *earnings collapsed faster than price*. Optically cheap, fundamentally
  expensive. Check P/E and P/B, not just the % off the high.
- **Cyclical null-P/E bounce.** Petrochem/panel/shipping names at trough with no earnings (null
  P/E) or below book. This is an oil/feedstock/freight-rate bet, not stable growth — exactly the
  "roller coaster" to avoid for a long-term sleeper. Confirm with flow: dealers distributing into
  the pop = trader's game.
- **Value trap.** Cheap (low P/E) *and* foreigners persistently selling. Cheap for a reason — no
  catalyst, or a structural discount (e.g., -KY China/governance). Cheapness without accumulation is
  not a sleeper.
- **Story-premium theme pure-play.** The consensus name in a hot theme, re-rated to 40–250× (robot
  reducers, cobots, chassis). Highest beta *up and down*; you're paying full price for the narrative,
  late. If the user wants the theme, hunt the cheap adjacent name instead.
- **Biotech / penny / roller-coaster.** Binary, illiquid, or chronically whippy. Not sleepers.

**Liquidity trap sub-flag:** even a good-looking base is un-tradeable if turnover is a few million
NT$/day (tens of thousands of shares). Size will be trapped. Watchlist-only unless sizing tiny.

---

## 5. Thresholds cheat-sheet

These are defaults, not laws — always read them in context (sector, cycle, rate environment).

- **Cheap:** P/E < ~15 (excellent) / < ~20 (good), *with real EPS*; P/B < ~2 (excellent) / < ~3 (ok).
- **Income:** yield > 3% is a meaningful cushion; > 4.5% is strong.
- **Under-owned:** foreign held < ~20% with large room = runway.
- **Accumulation:** foreign net-positive on ≳ 70% of the last ~18 sessions, especially into flat price.
- **Not-run:** < ~15% above the 4–6-week base; be wary above +30%; avoid above +40%.
- **Froth:** margin balance < ~5% of limit and short ≈ 0 = clean.
- **Inflection:** monthly revenue YoY positive and accelerating, ideally 2 months running and
  peer-confirmed. (One strong month is a signal, not a trend.)
