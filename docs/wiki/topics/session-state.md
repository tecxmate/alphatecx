---
title: Session State + Market Calendar (session_state)
type: topic
slug: session-state
date: 2026-07-21
updated: 2026-07-21
attributed_to: [antigravity-agent]
belongs_to: [system-architecture]
source: code
status: active
tags: [mcp, session, calendar, twse, timezone, 試撮]
related: [flow-leaders-scan, limit-board-scanner, system-architecture]
---

## Summary
`session_state()` answers "is the market open, what phase, and is this price real?"
It exists to kill one error class: mistaking a 試撮 (08:30–09:00 pre-open simulated auction)
price for a real trade. In that window `price_is_indicative=true` and a `warning` is set.

## Code
- `mcp_server/api/session_state.py` — pure phase logic (`phase_for`, `build_state`, `PHASES_TODAY`).
- `mcp_server/api/db_v2.py::market_closure(date_iso)` — reads `market_holidays`.
- `mcp_server/api/index.py::session_state(date=None)` — the `@mcp.tool()` wrapper.
- `src/harvester/twse.py::fetch_twse_holidays(year)` + `loader.upsert_market_holidays` +
  `daily.py` step 5c — nightly calendar ETL.
- `sql/015_market_calendar.sql` — `market_holidays` table + mcp_viewer GRANT/RLS.
- Tests: `tests/test_session_state.py`.

## Phases (Asia/Taipei)
`pre_open_auction` 08:30–09:00 (indicative) · `regular` 09:00–13:30 · `after_hours` 13:30–14:30 ·
`closed` otherwise. On a non-trading day every clock time is `closed`.

## Calendar rules (non-obvious)
- `is_trading_day` = weekday<5 AND no `is_closed` row in `market_holidays`.
- The TWSE schedule lists **open reference days** (開始交易/最後交易) alongside closures; the
  harvester marks a row `is_closed=false` iff the name contains one of those markers. `市場無交易`
  (settlement-only) has neither marker and stays a closure.
- Ad-hoc **typhoon** closures are NOT in the TWSE schedule → insert manually with
  `source='manual'`; a nightly re-harvest won't overwrite manual rows.
- `calendar_source` is `"calendar"` normally, `"weekend_only"` if the holiday table can't be read
  (degrades instead of failing).
- **Any new MCP-read table must `GRANT SELECT` + add an RLS policy for `mcp_viewer`** — the
  serverless server reads as that role; local dev connects as `neondb_owner` and hides the gap.
  This bit `market_holidays` first (see [[2026-07-21-session-state-calendar]]).
