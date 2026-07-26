---
title: Flow-leaders enrichment — forward-cash yield, ex-div proximity, stale guard (Tool Review v2 Phase 1)
type: decision
slug: 2026-07-26-flow-leaders-dividend-enrichment
date: 2026-07-26
attributed_to: [niko]
belongs_to: [flow-leaders-scan]
source: chat
status: active
tags: [mcp, scanner, dividend, enrichment, tool-review]
related: [flow-leaders-scan, dividend-calendar, 2026-07-21-flow-leaders-scan]
---

## Context
Tool Review v2 (live use 2026-07-22 → 07-26) found the `flow_leaders_scan` *engine* sound but
its dividend/labelling layer misleading in ways that invite wrong buys:
- **#1** the `yield` flag keyed off `raw_twse_valuation.dividend_yield` — TWSE's blended 殖利率,
  which sums cash + stock-implied value. 台中銀 (2812) read **5.18** when the real forward *cash*
  yield is **~1.9** (cash 0.39 / close 20.45), producing a false "high-yield defensive" thesis.
- **#3** no ex-dividend proximity awareness (華碩 ex 7/1, 台中銀 ex 8/4 both needed manual web checks).
- **#6** no stale-price guard on the EOD scan.
- **#7** project-completion revenue noise (順天 +4,115%) earned `rev_inflecting`.

The review assumed these were "wiring existing FinMind data", but **FinMind was never wired** in
this repo (documented follow-up needing a token). So the fixable-now subset is TWSE-native only;
the probability/news items (#2 `dividend_trap`/`fill_probability_5y`, #4 governance news, #5
dividend-adjusted flatness) genuinely need FinMind.

## Decision
Niko chose **"TWSE-native now, FinMind next"**: ship the TWSE-native subset immediately, scope the
FinMind ETL as a non-blocking Phase 2.

Phase 1 (this commit):
- **Yield flag is forward-cash-gated.** New `cash_yield_fwd(row)` = next scheduled *cash* dividend
  (TWT48U forecast `cash_value`) ÷ close. The `yield` flag requires `cash_yield_fwd >= 3.0`; the
  blended `dividend_yield` no longer earns it. No forecast row ⇒ `cash_yield_fwd: null`, no flag
  (absence ≠ a claim of zero yield).
- **Ex-div proximity:** `days_to_ex` / `days_since_ex` + flags `ex_div_imminent` (≤14 cal days ≈ 10
  trading) and `recently_ex` (≤20 days). Informational, not anti-flags. Fed by two new LATERAL
  joins on `raw_twse_dividend` in `query_flow_leaders`.
- **`stale_price_warning`** top-level when the scan `as_of` isn't today (#6).
- **`rev_inflecting` suppressed** when `|yoy| >= 200` (#7). (Numeric guard, since `dim_ticker` has
  no industry column to suppress by 營建/建設.)

## Rationale
Being conservative on the yield flag (only flag when a forward cash figure exists) fixes both
台中銀 (→1.9, no flag) **and** 晶華/2707 (no dividend record at all → no flag) in one move — the
exact two live failures. The `dividend_trap` downgrade the review wanted for 晶華 needs 填息
history (FinMind) and is deferred; but the dangerous income *label* is already removed. The
valuation *sub-score* still credits the blended trailing yield (≤5 pts, cheapness proxy) so 拓凱's
score is unchanged — only the flag moved. [niko] approved the scope split.

## Consequences
- `flow_leaders.score_row` gains an `as_of` kwarg (kept pure via `date.fromisoformat`, no clock
  read) and emits `cash_yield_fwd`, `days_to_ex`, `days_since_ex`.
- `query_flow_leaders` SQL: +2 LATERAL joins (`du` upcoming, `dr` recent) on `raw_twse_dividend`;
  `_stamp` source now includes `raw_twse_dividend`.
- Tests: `tests/test_flow_leaders.py` 15 → 24 (DividendYieldTests, RevenueGuardTests). Suite 100.
- Live-verified @ 2026-07-24: 2812 cash_yield_fwd 1.91 + ex_div_imminent + no yield flag; 2707 no
  yield flag; 2357 recently_ex fires @7/10, not @7/24 (past the 20d window).
- **Deferred to Phase 2 (FinMind):** true `dividend_trap`/`fill_probability_5y` (#2), governance
  news overlay (#4), dividend-adjusted flatness (#5), full historical cash/stock split (#1). See
  [[finmind-phase2-plan]].

## Provenance
- Discussed 2026-07-26 between [niko] (owner) and [antigravity-agent] (agent); scope chosen via
  the "TWSE-native now, FinMind next" option.
- Implementing commit: (this commit).
