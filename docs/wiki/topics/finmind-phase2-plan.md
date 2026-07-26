---
title: FinMind integration (Tool Review v2 Phase 2)
type: topic
slug: finmind-phase2-plan
date: 2026-07-26
updated: 2026-07-27
belongs_to: [flow-leaders-scan, system-architecture]
source: synthesis
status: active
tags: [finmind, dividend, news, roadmap, tool-review]
related: [2026-07-26-flow-leaders-dividend-enrichment, 2026-07-27-finmind-phase2-build, flow-leaders-scan, dividend-calendar]
---

## Status: #1 + #2 (reframed) + #4 BUILT 2026-07-27 — see [[2026-07-27-finmind-phase2-build]]
Free-tier token wired; nightly ETL live. Cash/stock split, honest ex-date `dividend_trap`, and the
governance-news overlay ship. Only the true 5y 填息 metric + dividend-adjusted flatness remain
blocked (need paid `TaiwanStockPriceAdj`). Read the fill-probability reality section below — it is
why `dividend_trap` is ex-date-based, not probability-based.

## Summary
The Tool Review v2 items that need FinMind (not TWSE-native). Phase 1 shipped forward-cash yield,
ex-div proximity, the stale-price guard, and the revenue numeric guard — see
[[2026-07-26-flow-leaders-dividend-enrichment]]. Phase 2 (this page) added the FinMind-backed
dividend/news enrichment.

## Prerequisite (blocker)
- **`FINMIND_TOKEN`** in `.env` (gitignored) **and** on the `alphatecx-v2-mcp` Vercel project.
  The ETL needs a central limiter + cache; the MCP read path must never call FinMind synchronously
  (serverless budget). Wire it as a nightly harvester into Neon, same shape as the TWSE ETL, then
  the scanner reads from Neon.

## FinMind tiers (verified 2026-07-27, finmind.github.io/login + quickstart)
- **Anonymous / no token:** 300 req/hr.
- **Free registered** (sign up + verify email → token from account page): **600 req/hr**.
- **Paid "sponsor"** (2 tiers): higher hourly limits **and** a few paid-only datasets/features.
- **Free tier unblocks 3 of the 4 deferred items** (nightly ETL, not request-time):
  - #1 `TaiwanStockDividend` (cash/stock split) — **free**.
  - #2 `TaiwanStockDividendResult` (填息 → dividend_trap) — **free**.
  - #4 `TaiwanStockNews` (governance overlay) — **free**.
  - #5 `TaiwanStockPriceAdj` / `taiwan_stock_daily_adj` (dividend-adjusted flatness) — **PAID-only**.
- Free-tier caveat: per-ticker fetch at 600/hr (the "all stocks for one date" call is paid). ≤50
  board hits = trivial; a full ~1.2k nightly backfill ≈ 2h throttled — fine overnight, or enrich
  hits on-demand. So a **free token gets Phase 2 #1/#2/#4**; only #5 needs a paid plan.

## Deferred work items
1. **`dividend_trap` + `fill_probability_5y` (review #2, highest deferred priority).** Compute the
   5-year 填息 (gap-refill) probability from `TaiwanStockDividendResult` + price history. Flag
   `dividend_trap` when `already_ex_this_cycle AND fill_probability_5y < 0.30`; it downgrades
   `sleeper` → `watch` and strips `yield`. Acceptance: 晶華 (2707) @ 2026-07-24 → `dividend_trap`,
   triage ≤ `watch`. *(Phase 1 already removes 晶華's `yield` flag; this adds the explicit trap +
   downgrade.)*
2. **Clean cash/stock decomposition, all history (review #1 full).** `TaiwanStockDividend`
   separates `CashEarningsDistribution` / `StockEarningsDistribution`. TWT49U only stores combined
   權值+息值, so historical `cash_yield` for names *without* a forward forecast needs FinMind.
3. **News / governance overlay (review #4).** Join `TaiwanStockNews` (or MOPS 重大訊息 `t187ap04`);
   add `recent_material_news_count` (30d) + surface 1–3 headlines. Optional keyword flag
   `governance_risk` (洗錢/掏空/內線/財報不實/下市/違約交割/搜索/起訴) — **surface only, never
   auto-downgrade** (false positives likely). Motivating case: 台中銀 money-laundering indictment.
4. **Dividend-adjusted flatness (review #5).** When `recently_ex`, compute flatness on
   `TaiwanStockPriceAdj` (dividend-adjusted) rather than raw close, so an ex-drop doesn't read as
   weakness or fake-flatness. Depends on #1's `recently_ex` (already shipped in Phase 1).

## Also worth a TWSE-native backfill (no FinMind)
- **Backfill `raw_twse_dividend` actuals further back** (TWT49U currently only 2026-06-01 →). Would
  let `recently_ex` catch names like 晶華 (ex 2026-04-16) that are currently invisible. Cheap; does
  NOT need FinMind. Still won't give fill probability.

## Fill-probability data reality (discovered 2026-07-27 during backfill)
`TaiwanStockDividendResult.max_price` is the **ex-day limit-up band** (2812: before 21.9, max 24.05
= +9.8%, min 19.7 = −10%), **not** a post-ex recovery high. So `max_price >= before_price` is
trivially true → a naive fill metric reads ~1.0 for everything (computed 1.0 for 晶華, which the
review said never fills). A real 5-year 填息 probability needs a multi-year **adjusted** price
series = `TaiwanStockPriceAdj`, which is **paid-only**. Conclusion: **do not fabricate
`fill_probability_5y`.** The `finmind_fill_stats` table + pure `fill_probability()` are retained
(the function is correct given a proper price series; wire it if we ever get paid adj-price), but
they do **not** drive triage.

`dividend_trap` was therefore reframed to an honest, computable condition that hits the same
acceptance cases: **already went ex within ~250 days AND no upcoming ex** (dividend spent, buyer
waits ~a year) → downgrade sleeper→watch + strip yield. FinMind's full-history ex-dates make this
work for 晶華 (ex 2026-04-16, which TWSE's June-onward window lacked). 台中銀 has an upcoming ex →
not a trap.

## Open questions
- **Resolved:** the adj-price endpoint (`taiwan_stock_daily_adj`) IS paid-only — the true 5y 填息
  metric (#5-adjacent) needs a paid plan; #1/#4 + the reframed #2 do not. (Verified 2026-07-27.)
- Proxy FinMind through the Alpha MCP vs. run FinMind's own MCP — see `CLAUDE_CODE_HANDOFF.md` M1.

## History
- 2026-07-26 — carved out of Tool Review v2 as the FinMind-gated remainder; [niko] chose to ship
  TWSE-native first and defer this. `status: proposed` until a token is provided.
