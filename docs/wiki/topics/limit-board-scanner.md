---
title: Limit Board Scanner (scan_limit_board)
type: topic
slug: limit-board-scanner
date: 2026-07-17
updated: 2026-07-17
attributed_to: [antigravity-agent]
belongs_to: [system-architecture]
source: code
status: active
tags: [mcp, scanner, twse, tpex, limit-up, limit-down, triage]
related: [2026-07-17-limit-board-scanner-eod-only, system-architecture, alphatecx]
---

## Summary

`scan_limit_board` scans the Taiwan 漲停/跌停 board for a session and triages each hit as
`sleeper` / `watch` / `chase`. It answers both halves of board triage: *who* is at the limit,
and *which of them is a base-breakout vs. a chase*. EOD only — see
[the scoping decision](../decisions/2026-07-17-limit-board-scanner-eod-only.md).

Code: `mcp_server/api/limit_board.py`, `db_v2.query_limit_board_enrichment`,
tool in `mcp_server/api/index.py`. Tests: `tests/test_limit_board.py`.

## Data sources

| Market | Endpoint | Notes |
|---|---|---|
| TWSE | `www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?type=ALLBUT0999` | ~1,371 rows; the board is **one table among ~10** in the payload |
| TPEX | `www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?type=AL` | ~10,088 rows incl. warrants; date-parameterised |

Both carry close, signed change, and the last disclosed bid/ask. ~1,950 equities after
filtering.

## Exchange quirks — learned the hard way, do not re-derive

- **`reference_price = close - change`.** Verified 848/848 exact against TPEX's own published
  次日參考價 for the 2026-07-16 session. The derivation already carries the exchange's
  ex-dividend / ex-rights adjustments, so it must **not** be replaced with a raw previous
  close — on an ex-day the raw previous close gives the wrong limit price.
- **The §3 tick table is correct.** Verified 885/889 against TPEX's own published
  次日漲停價/次日跌停價. The 4 misses were 3 names with a corporate action pending the *next*
  session plus one no-limit new listing — none contradict the table.
- **TWSE HTML-wraps the 漲跌(+/-) sign** for colour: `<p style= color:red>+</p>`. Strip tags
  before reading the sign. TPEX instead signs 漲跌 inline (`'-3.26'`) with no direction column.
- **The exchanges spell "no quote" differently: TWSE prints `'--'`, TPEX prints `'0.00'`.**
  This one is a live trap — parsing TPEX's `0.00` literally reads as a 0.00 offer and
  **silently misses every TPEX lock** (14 of 36 on 2026-07-16). `_price()` collapses
  non-positive quotes to None so lock detection is uniform. A real quote is never zero.
- **TPEX intermittently truncates chunked responses** (`IncompleteRead`). Retries are required,
  not optional.
- **TPEX's `openapi/v1/tpex_mainboard_daily_close_quotes` is a today-only snapshot** — no date
  parameter. Unusable for historical scans; `dailyQuotes` is the one to use.
- **New listings trade with no band.** TPEX signals this with a sentinel 次日漲停價 of
  `9995.00` / 次日跌停價 `0.01`. We detect it generically instead: a move beyond ±10.5% means
  the security has no limit, so `has_price_limit=false` and we never claim it hit a limit it
  doesn't have.
- **The board's `次日漲停價` is a free oracle** for validating the tick table against the
  exchange's own arithmetic. Worth re-running if the tick rules ever change (spec §8 asks for
  exactly this reconciliation).
- **TWSE's `stat` distinguishes "no session" from "refused"; TPEX's does not.** TWSE returns
  `很抱歉，沒有符合條件的資料!` for a weekend/holiday and a *different* message for a real
  refusal (e.g. `查詢日期大於今日，請重新查詢!`). Only the former may be treated as a holiday —
  conflating them lets a TWSE outage pass as a quiet non-trading day while TPEX succeeds,
  presenting half the market as the board. TPEX always returns `stat: 'ok'`, 0 rows, for
  weekend and far-future dates alike, so it can signal nothing.
- **A malformed date makes TPEX return _today's_ board** (~10k rows) instead of an error. So
  `date` must be validated strictly (`YYYY-MM-DD`, not in the future) before any fetch, or a
  typo silently answers with the wrong session under the requested label.
- **Both endpoints answer in 1–2.5s** (TWSE ~239 KB, TPEX ~1.5 MB; measured 2026-07-17). The
  fetch budget is `_TIMEOUT=10` × `_RETRIES=2` × 2 markets ≈ 42s worst case. This is the only
  tool here that makes outbound calls, so the only one with a real time budget — but it fits
  comfortably inside the platform default. Vercel's function duration ceiling is per *function*,
  not per tool, and all 35 tools share the single `api/index.py` function; its `maxDuration`
  defaults to 300s under Fluid Compute (all plans), ~7× the worst case, so **no `maxDuration`
  override is set** — an earlier `maxDuration: 60` was reverted because it would have capped the
  other 34 (Neon-only) tools at 60s to solve a non-problem.

## Partial-coverage guard

A session where one exchange has a board and the other doesn't does not exist. Since TPEX
cannot report failure, `scan_limit_board` compares per-market row counts and, if a requested
market contributed zero rows while another contributed data, appends an explicit
`partial coverage: ...` error rather than presenting the survivor as the market. Every
response carries `universe_by_market` so coverage is visible without inspecting `errors`.

## EOD lock detection works — contrary to the spec

Spec §4 asserted `is_locked` is "unknowable from close-only data → set `is_locked = null`".
It isn't: both feeds publish the last disclosed bid/ask at the close, so a one-sided book
(漲停鎖住) is directly observable.

```
locked_up   = at_limit_up   AND no ask quote AND bid at/above the limit
locked_down = at_limit_down AND no bid quote AND ask at/below the limit
```

On 2026-07-16 this identified 36 locked names out of 37 at-limit. `lock_time` and intraday
queue depth remain genuinely realtime-only and stay null.

## Deviations from the spec, and why

1. **`is_locked` is populated at EOD** rather than null (above).
2. **A null `pe_ratio` is not automatically the `no_earnings` anti-flag.** §6 says null P/E ⇒
   `no_earnings` ⇒ `chase`, but §8 admits `raw_twse_valuation` (TWSE BWIBBU) simply has **no
   TPEX coverage** — it holds ~1,128 tickers, all TWSE. Applied literally, every 上櫃 name
   auto-labels `chase`, precisely where §8 says "a lot of the limit-up action" is. The
   enrichment query returns a `valuation_known` marker so the anti-flag fires only on "row
   present, P/E null" (the genuine no-positive-earnings case TWSE prints as `-`), not on "we
   hold no row".
3. **`foreign_net_z20` is computed from `raw_twse_t86`, not read from `signal_value`.** §5
   sources it from `view_latest_signals`. That table covers **58 tickers**; `raw_twse_t86`
   covers **12,791**. Sourced from signals, z20 was null for ~every hit, so `accumulating`
   never fired and **`triage="sleeper"` was unreachable — the one verdict the tool exists to
   produce**. Recomputed in SQL with the same definition as `src/quant/indicators.zscore`
   ((latest − mean20) / sample stddev20), so the classified names still agree with
   `q_indicators`. After the change: z20 populated 32/32, sleepers surfaced.

## Coverage caveats

Enrichment is all LEFT JOIN — a hit is never dropped for missing context.

| Source | Tickers | Note |
|---|---|---|
| `raw_twse_t86` | ~12,791 | all-market; drives flow + z20 |
| `raw_twse_holdings` | ~2,245 | all-market |
| `raw_twse_valuation` | ~1,128 | **TWSE only** — no TPEX P/E, P/B, yield |
| `raw_twse_margin` | ~1,865 | can lag; read as-of the scan date |
| `signal_value` | **58** | classified universe only — `rsi_14`, `sma_*`, `rs_vs_market_60`, `pct_below_52w_high` are null for nearly every board hit |

`pct_below_52w_high` being ~always null means the `off_highs` flag effectively never fires.
Deepening OHLCV coverage would fix that; it is the obvious next improvement.

All enrichment reads **as-of the scan date**, not "latest", so a post-mortem of an old
session reports what was knowable that day.

## Universe

Common stock only: 4-digit numeric codes. ETFs/ETNs (5–6 digits, e.g. `00400A`, `006203`) and
TPEX warrants are excluded — ETFs use a finer tick scale (the exchange's own `NextLimitUp` for
`006201` is `45.43`, not a 0.05-tick multiple), and some foreign-tracking ETFs have no price
limit at all.
