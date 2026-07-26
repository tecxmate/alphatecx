---
title: FinMind integration (Tool Review v2 Phase 2)
type: topic
slug: finmind-phase2-plan
date: 2026-07-26
updated: 2026-07-26
belongs_to: [flow-leaders-scan, system-architecture]
source: synthesis
status: proposed
tags: [finmind, dividend, news, roadmap, tool-review, deferred]
related: [2026-07-26-flow-leaders-dividend-enrichment, flow-leaders-scan, dividend-calendar]
---

## Summary
The Tool Review v2 items that **cannot** be done with TWSE-native data and are deferred until a
FinMind token exists. Phase 1 (TWSE-native) shipped forward-cash yield, ex-div proximity, the
stale-price guard, and the revenue numeric guard — see
[[2026-07-26-flow-leaders-dividend-enrichment]]. This page is the not-yet-built remainder.

## Prerequisite (blocker)
- **`FINMIND_TOKEN`** in `.env` (gitignored) **and** on the `alphatecx-v2-mcp` Vercel project.
  FinMind free tier ≈ 600 req/hr — the ETL needs a central limiter + cache; the MCP read path must
  never call FinMind synchronously (serverless budget). Wire it as a nightly harvester into Neon,
  same shape as the TWSE ETL, then the scanner reads from Neon.

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

## Open questions
- FinMind adj-price endpoint is paid-tier on some plans — verify before relying on #4.
- Proxy FinMind through the Alpha MCP vs. run FinMind's own MCP — see `CLAUDE_CODE_HANDOFF.md` M1.

## History
- 2026-07-26 — carved out of Tool Review v2 as the FinMind-gated remainder; [niko] chose to ship
  TWSE-native first and defer this. `status: proposed` until a token is provided.
