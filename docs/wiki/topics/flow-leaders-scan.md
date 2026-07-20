---
title: Flow-Leaders Scan (flow_leaders_scan)
type: topic
slug: flow-leaders-scan
date: 2026-07-21
updated: 2026-07-21
attributed_to: [antigravity-agent]
belongs_to: [system-architecture]
source: code
status: active
tags: [mcp, scanner, twse, flow, accumulation, sleeper, generative]
related: [2026-07-21-flow-leaders-scan, limit-board-scanner, system-architecture, alphatecx]
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
- `tests/test_flow_leaders.py` — 15 tests pinning the two acceptance verdicts + robustness.

## Data model (why these tables)
- **Flow** — `raw_twse_t86` (all-market, ~12.8k tickers, per-day `foreign_net`). The scan's
  edge is breadth, so flow must come from T86, not the ~58-name signal matviews.
- **Price / valuation** — `raw_twse_valuation` (TWSE-only, ~1.1k names): daily `close` +
  PE/PB/dividend_yield with history. Unioned with `raw_twse_ohlcv.close` (~513 names) for the
  price series. **Most TPEX names are unpriced → not returned** (documented gap).
- **Enrichment** — `raw_twse_holdings` (foreign_held/room), `raw_twse_margin`
  (balance/limit → froth), `raw_monthly_revenue` (YoY inflection), as-of `as_of`.

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
