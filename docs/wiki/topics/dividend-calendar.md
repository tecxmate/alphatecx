---
title: Dividend Calendar (dividend_calendar)
type: topic
slug: dividend-calendar
date: 2026-07-21
updated: 2026-07-21
attributed_to: [antigravity-agent]
belongs_to: [system-architecture]
source: code
status: active
tags: [mcp, dividend, ex-dividend, twse, corporate-action, m1-adopt]
related: [system-architecture, flow-leaders-scan, alphatecx]
---

## Summary
`dividend_calendar(ticker_id, date)` answers "does a buyer today still receive the dividend?" —
the exact check that stops quoting an already-ex yield as if it were forward (the 華碩 error).
It returns the most-recent-past and next-upcoming ex-dividend/ex-rights event and whether the
stock has already gone ex.

## Data-source discovery (why TWT49U, not t187ap45_L)
- `opendata/t187ap45_L` (股利分派情形) has the dividend **amount** and board/meeting dates but
  **NOT the ex trading date** — useless for "does a buyer today get it?".
- **TWT49U** (除權除息計算結果表) is the authoritative **ex-date** source: 資料日期 = ex date,
  權/息 type, 權值+息值 value, pre-ex close + reference price. **TWT48U** (預告表) is the upcoming
  forecast. No FinMind needed for this ("adopt before build").

## Code
- `sql/016_dividends.sql` — `raw_twse_dividend` (PK `ex_date,ticker_id`) + mcp_viewer GRANT/RLS.
- `src/harvester/twse.py` — `fetch_twse_ex_dividend(start,end)` (TWT49U), `fetch_twse_ex_forecast`
  (TWT48U), `_roc_cn_to_iso` ('115年07月01日' → '2026-07-01').
- `src/harvester/loader.py::upsert_dividends` — a later `forecast` never overwrites an `actual` row.
- `src/harvester/daily.py` step 5d — this + previous calendar month (TWT49U times out on wide
  ranges in peak season) + forecast.
- `db_v2.query_dividend` + `index.py::dividend_calendar` + `tests/test_dividends.py`.

## Behaviour / limits
- `ex_type` 息 (cash) / 權 (rights) / 權息 (both); `cash_dividend` is 元/股, combined for 權息.
- `already_ex` true once past the ex date → a new buyer does NOT receive it.
- TWSE-listed coverage only (the 除權除息 tables). **No forward estimate is ever synthesised** —
  consensus forward yields remain a documented gap (label `source: manual`/`web`).
- Acceptance: 華碩 2357 @ 2026-07-10 → ex 2026-07-01, cash 42.0, already_ex.
