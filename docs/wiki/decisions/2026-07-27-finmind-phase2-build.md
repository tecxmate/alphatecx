---
title: FinMind Phase 2 built — cash/stock split, honest dividend_trap, governance news
type: decision
slug: 2026-07-27-finmind-phase2-build
date: 2026-07-27
attributed_to: [niko]
belongs_to: [flow-leaders-scan]
source: chat
status: active
tags: [finmind, dividend, news, enrichment, tool-review, etl]
related: [finmind-phase2-plan, 2026-07-26-flow-leaders-dividend-enrichment, flow-leaders-scan]
---

## Context
[niko] supplied a free-tier FinMind token (level 1, 600 req/hr; verified `TaiwanStockDividend`,
`TaiwanStockDividendResult`, `TaiwanStockNews` accessible, `TaiwanStockPriceAdj` paid-blocked) and
chose to build Tool Review v2 items **#1 (cash/stock split) + #2 (dividend_trap) + #4 (governance
news)**. See [[finmind-phase2-plan]].

## Decision
Wired a nightly FinMind ETL into Neon and joined it into `flow_leaders_scan`. The MCP read path
never calls FinMind (600/hr, latency) — the harvester lands data in Neon and the scanner reads it.

New: `sql/017_finmind.sql` (raw_finmind_dividend, raw_finmind_dividend_result, finmind_fill_stats,
raw_finmind_news + mcp_viewer grants); `src/harvester/finmind.py` (client + pure parsers +
`fill_probability` + governance keywords); loader upserts; `daily.py` step 5e (bounded universe =
classified + upcoming-ex, to stay under 600/hr) + `harvest_finmind()`; `scripts/backfill_finmind.py`
(resumable, wider backfill); scanner LATERAL joins + scorer flags.

## Rationale — the honest `dividend_trap`
The review specified `dividend_trap = already_ex AND fill_probability_5y < 0.30`, assuming FinMind's
`TaiwanStockDividendResult` yields a 5-year 填息 probability. **It does not.** `max_price` there is
the **ex-day limit-up band** (2812: before 21.9, max 24.05 = +9.8%, min 19.7 = −10%), not a post-ex
recovery high — so `max_price >= before_price` is trivially true and a naive metric reads ~1.0 for
everything (it computed **1.0 for 晶華**, which the review said *never* fills). A real 5y metric
needs multi-year **adjusted** prices = `TaiwanStockPriceAdj`, which is **paid-only**.

So we did **not** fabricate a fill probability. `dividend_trap` was reframed to the honest,
computable half that hits the same acceptance: **went ex within ~250 days AND no upcoming ex** →
the annual dividend is spent, a buyer waits ~a year → strip `yield`, downgrade sleeper→watch (never
overrides a chase). FinMind's full-history ex-dates make it work for 晶華, whose April ex TWSE's
June-onward TWT49U window lacked. The pure `fill_probability()` + `finmind_fill_stats` are retained
for the day we get paid adj-price, but do **not** drive triage. [niko] to be informed of this
deviation.

## Consequences
- Scanner rows gain: `cash_yield_ttm`, `fm_cash_dividend`/`fm_stock_dividend`, `already_ex`,
  `dividend_trap`, `recent_material_news_count`, `governance_news_count`, `news_headlines`; flags
  `dividend_trap` and `governance_risk` (surface-only).
- Live-verified @2026-07-24: 晶華 2707 → `dividend_trap`, triage `watch` (was sleeper); 台中銀 2812 →
  no trap (upcoming ex 8/4), cash 0.39/stock 0.67; governance keyword flags real 違約交割 news (3037).
- `FINMIND_TOKEN`: in `.env` (gitignored) + **GitHub Actions secret** (nightly harvester runs in
  CI, not Vercel — the Vercel read path needs no token). daily_harvest.yml passes it; empty ⇒ step
  self-skips.
- Tests: +18 (test_finmind.py 11, DividendTrapTests 6, +1); suite **117** green.
- Coverage: nightly harvest is bounded (classified + upcoming-ex). Wider coverage =
  `scripts/backfill_finmind.py --universe dividend` (paced for 600/hr). 62 names backfilled now.
- **Still blocked (paid):** true 5y 填息 probability + dividend-adjusted flatness (v2 #5) →
  `TaiwanStockPriceAdj`.

## Provenance
- Discussed 2026-07-27 between [niko] (owner, supplied token, chose #1+#2+#4) and [antigravity-agent].
- Implementing commit: (this commit).
