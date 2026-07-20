---
title: flow_leaders_scan — median-anchored flatness, z-score not a gate
type: decision
slug: 2026-07-21-flow-leaders-scan
date: 2026-07-21
updated: 2026-07-21
attributed_to: [niko, antigravity-agent]
belongs_to: [flow-leaders-scan, limit-board-scanner, system-architecture]
source: chat
status: active
tags: [mcp, scanner, twse, flow, accumulation, sleeper, data-quality]
related: [flow-leaders-scan, limit-board-scanner, system-architecture, taiwan-ai-supply-chain]
---

## Context
Niko handed over `CLAUDE_CODE_HANDOFF.md` (a TW equity data-layer roadmap) and
`scan_limit_board_spec_2.md`, asking to build "all the things that are missing" — leaving
the already-shipped `scan_limit_board` as-is. `flow_leaders_scan` is the roadmap's marquee
"generative" tool (M2a): find quiet foreign accumulation into a still-cheap, still-flat
price — the 拓凱 signature — *before* the move, rather than triaging what already ran.

The handoff set two **non-negotiable** acceptance tests: 拓凱 (4536) must land top-20 and
triage `sleeper` as of 2026-06-30; 日馳 (1526) must triage `chase` as of 2026-07-17. It
also warned: "If the scan misses 拓凱, the weights are wrong."

## Decisions

1. **Price/flatness is sourced from `raw_twse_valuation.close`, not `raw_twse_ohlcv`.**
   `raw_twse_ohlcv` covers only ~513 names (top-500 by turnover) and has **zero rows for
   both acceptance tickers**. `raw_twse_valuation` carries a daily `close` (plus PE/PB/yield)
   for ~1.1k TWSE names with history — both 拓凱 and 日馳 are fully covered. The scoreable
   universe is therefore `valuation ∪ ohlcv` closes (~1.2k), driven off that priced set so
   the per-ticker LATERAL joins run ~10× fewer times. TPEX has **no** valuation → most TPEX
   names are unpriced and not returned (documented gap, not a silent drop).

2. **Flatness is median-anchored, not endpoint-to-endpoint.** 拓凱 has a single corrupt
   TWSE print — `close = 87.3` on 2026-05-13, sandwiched by ~152 closes (PE jumps too). Any
   max/min- or first/last-based range reads a ~50% phantom swing. `price_move_pct` is now
   *latest vs the window median*; `price_range_pct` is *(p90−p10)/median*. A lone bad tick
   cannot move either. This was the single fix that took 拓凱 from rank 379 → 9.

3. **Single-day z-score does NOT gate selection.** The handoff's `min_foreign_z = 1.0`
   default would *exclude* 拓凱, whose final-day `foreign_net_z20` is ~−0.4 — a multi-week
   grind has no closing-day spike. The real accumulation signal is **buy-day ratio +
   cumulative net**, not one day's z. `min_foreign_z` is therefore an OPTIONAL, off-by-default
   filter; the primary rank is `sleeper_score` (accumulation 35 / flatness 25 / valuation 20 /
   under-owned 10 / no-froth 5 / revenue 5).

4. **`consecutive_foreign_buy_days` from `view_ticker_momentum` is unusable for historical
   scans** — the matview is computed as-of *now*, so it returns 1 for every ticker at any past
   `as_of`. Streak was dropped from scoring (acceptance passes without it); if wanted later it
   must be computed inline from `raw_twse_t86`.

## Verification
Both acceptance tests pass live against Neon (2026-07-21 run): 拓凱 rank **9/1219**, triage
`sleeper`; 日馳 triage `chase` (no_earnings + distributing). 15 pure-function unit tests in
`tests/test_flow_leaders.py`; full suite 64 passing.

## Deviations from spec (recorded, deliberate)
- `min_foreign_z` demoted from a `1.0` default gate to an optional off-by-default filter (see #3).
- `max_price_move_pct` / `max_pe` / `max_foreign_held` / `min_buy_day_ratio` shape the score and
  the `accumulation_into_flat` signature rather than hard-filtering the candidate set, so a
  strong name just over a threshold still ranks instead of vanishing.
