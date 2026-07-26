---
title: Flow-Leaders Scan (flow_leaders_scan)
type: topic
slug: flow-leaders-scan
date: 2026-07-21
updated: 2026-07-26
attributed_to: [antigravity-agent]
belongs_to: [system-architecture]
source: code
status: active
tags: [mcp, scanner, twse, flow, accumulation, sleeper, generative, dividend]
related: [2026-07-21-flow-leaders-scan, 2026-07-26-flow-leaders-dividend-enrichment, finmind-phase2-plan, limit-board-scanner, dividend-calendar, system-architecture, alphatecx]
---

## Summary

`flow_leaders_scan` is the *generative* board tool: a market-wide screen for sustained
foreign net buying into a still-cheap, still-flat price (the 拓凱 signature), producing a
`sleeper_score` (0–100), `sleeper_flags`, and a `triage` verdict (`sleeper` / `watch` /
`chase`) per hit. Where `scan_limit_board` triages what already moved, this finds what is
being quietly accumulated first. See [[limit-board-scanner]] for the sibling tool and the
shared rubric vocabulary.

## Where the code lives
- `mcp_server/api/flow_leaders.py` — pure scoring: `score_row`, `price_move_pct`,
  `price_range_pct`, `margin_usage_pct`. Deterministic; unit-tested directly.
- `mcp_server/api/db_v2.py` — `query_flow_leaders(as_of, window_days, markets)` (one
  market-wide SQL pass) and `latest_flow_date()` (default as-of).
- `mcp_server/api/index.py` — the `@mcp.tool() flow_leaders_scan(...)` wrapper (validation,
  filters, sort, `_stamp`) + the `sc_capabilities` entry.
- `tests/test_flow_leaders.py` — 24 tests: the two acceptance verdicts, robustness, and the
  dividend-enrichment / revenue-guard cases.

## Data model (why these tables)
- **Flow** — `raw_twse_t86` (all-market, ~12.8k tickers, per-day `foreign_net`). The scan's
  edge is breadth, so flow must come from T86, not the ~58-name signal matviews.
- **Price / valuation** — `raw_twse_valuation` (TWSE-only, ~1.1k names): daily `close` +
  PE/PB/dividend_yield with history. Unioned with `raw_twse_ohlcv.close` (~513 names) for the
  price series. **Most TPEX names are unpriced → not returned** (documented gap).
- **Enrichment** — `raw_twse_holdings` (foreign_held/room), `raw_twse_margin`
  (balance/limit → froth), `raw_monthly_revenue` (YoY inflection), and `raw_twse_dividend`
  (next/last ex-date + forecast cash), as-of `as_of`.

## Dividend enrichment (2026-07-26, [[2026-07-26-flow-leaders-dividend-enrichment]])
- **`yield` flag is forward-cash-gated.** `cash_yield_fwd` = next scheduled *cash* dividend
  (TWT48U forecast) ÷ close; the flag needs `>= 3.0`. The blended TWSE 殖利率 (`dividend_yield`)
  no longer earns it — it conflated cash + stock (台中銀 read 5.18 vs ~1.9 real cash). No forecast
  ⇒ `cash_yield_fwd: null`, no flag (not a claim of zero yield).
- **Ex-div proximity:** `days_to_ex` / `days_since_ex` + `ex_div_imminent` (≤14 cal days) /
  `recently_ex` (≤20 days) flags (informational).
- **`stale_price_warning`** top-level when the scan `as_of` isn't today (re-quote before acting).
- **`rev_inflecting` suppressed** when `|yoy| >= 200` (營建/建設 project-completion noise).
## FinMind enrichment (2026-07-27, [[2026-07-27-finmind-phase2-build]])
Nightly FinMind ETL → Neon (`raw_finmind_*`, `sql/017`), joined into the scan. The read path never
calls FinMind. New per-hit fields/flags:
- **Cash/stock split (#1):** `fm_cash_dividend` / `fm_stock_dividend` (latest year) + `cash_yield_ttm`
  (cash-only trailing, context — the `yield` flag still gates on forward cash from Phase 1).
- **`dividend_trap` (#2, honest):** went ex within ~250d AND no upcoming ex → dividend spent →
  strip `yield`, downgrade sleeper→watch (never overrides a chase). Uses FinMind's full-history
  ex-dates (catches 晶華's April ex that TWT49U lacked). **Not** fill-probability based — FinMind's
  `max_price` is the ex-day limit band, so a real 5y 填息 metric needs paid adj-price. See the plan.
- **Governance overlay (#4):** `recent_material_news_count`, `governance_news_count`,
  `news_headlines` (≤3); `governance_risk` flag (洗錢/掏空/… keyword) — surface-only, no downgrade.
- **Blocked (paid):** true 填息 probability + dividend-adjusted flatness → [[finmind-phase2-plan]].
- Coverage: nightly = classified + upcoming-ex; wider = `scripts/backfill_finmind.py`.

## Non-obvious behaviour (see [[2026-07-21-flow-leaders-scan]] for full rationale)
- **Flatness is median-anchored** (latest vs window median; range = (p90−p10)/median) to
  survive corrupt single prints — e.g. 4536's phantom `87.3` on 2026-05-13. This one fix
  moved 拓凱 from rank 379 → 9.
- **`min_foreign_z` is off by default.** Single-day z would exclude multi-week grinders
  (拓凱's last-day z ≈ −0.4). Accumulation = buy-day ratio + cumulative net.
- **`view_ticker_momentum.consecutive_foreign_buy_days` is as-of-now**, so it reads 1 for a
  historical `as_of` — unusable for backtests; not used here.
- Liquidity floor (`min_turnover_twd`) only drops a name whose turnover is *known-and-below*;
  a missing OHLCV row never drops a hit (cross-cutting "never silently drop" rule).

## Acceptance (live, 2026-07-21)
拓凱 (4536) @ 2026-06-30 → rank **9/1219**, `sleeper`. 日馳 (1526) @ 2026-07-17 → `chase`.
