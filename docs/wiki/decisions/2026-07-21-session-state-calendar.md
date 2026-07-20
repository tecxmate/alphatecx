---
title: session_state calendar — classifier, manual typhoon overrides, mcp_viewer grant
type: decision
slug: 2026-07-21-session-state-calendar
date: 2026-07-21
updated: 2026-07-21
attributed_to: [antigravity-agent, niko]
belongs_to: [session-state, system-architecture]
source: chat
status: active
tags: [mcp, calendar, twse, rls, permissions, timezone]
related: [session-state, flow-leaders-scan, system-architecture]
---

## Context
`session_state` (handoff M3a) needs a trading calendar: weekends are trivial, but statutory
holidays and ad-hoc typhoon closures are not. The TWSE holiday schedule endpoint
(`rwd/zh/holidaySchedule`, ROC query year) is authoritative for statutory days.

## Decisions
1. **Closure classifier.** The schedule mixes closures with the open reference days that bracket
   a break. A row is a closure UNLESS its name contains `開始交易` or `最後交易`. `市場無交易`
   (settlement-only) lacks both markers and is correctly a closure. Verified against the full
   2026 schedule (24 closed / 27 rows).
2. **Manual typhoon overrides.** TWSE does not publish typhoon closures in the schedule, so they
   are `source='manual'` inserts into `market_holidays`. `upsert_market_holidays` guards the
   nightly TWSE re-harvest so it never clobbers a manual row.
3. **Do not fabricate closures.** The handoff cited 2026-07-10 as a Typhoon Bavi closure, but this
   DB has 4,742 T86 rows for that date — it traded. No manual row was inserted; inventing one
   would contradict the data.
4. **mcp_viewer GRANT + RLS.** The serverless MCP reads as the restricted `mcp_viewer` role; a
   new table with no grant returns `permission denied`. Local dev connects as `neondb_owner`, so
   tests passed while production would have failed. `sql/015` now grants SELECT + adds a permissive
   RLS policy (guarded on the role existing). **General rule: every new MCP-read table repeats this.**

## Verification
Live: CNY 2026-02-16 closed (農曆除夕及春節), 2026-02-23 open (resume), 端午 2026-06-19 closed,
Sundays closed, 2026-07-10 open. 9 unit tests in `tests/test_session_state.py`.
