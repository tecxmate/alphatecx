---
title: Realtime Quote (quote)
type: topic
slug: realtime-quote
date: 2026-07-21
updated: 2026-07-21
attributed_to: [antigravity-agent]
belongs_to: [system-architecture]
source: code
status: active
tags: [mcp, realtime, twse-mis, quote, watchlist]
related: [session-state, limit-board-scanner, system-architecture]
---

## Summary
`quote(symbols)` returns realtime-ish quotes for a **watchlist** (≤100 codes) from TWSE MIS,
including the authoritative pre-tick-rounded limit-up/down prices (`u`/`w`). It is not a market
scanner — MIS is rate-limited and stateful, so breadth belongs to
[[limit-board-scanner]] / [[flow-leaders-scan]].

## Code
- `mcp_server/api/quote.py` — MIS client + pure `parse_msg` (unit-tested). Primes the
  `index.jsp` cookie, batches ≤50 with a rate-limit sleep, caps at 100 symbols.
- `mcp_server/api/db_v2.py::ticker_markets` — resolves each code's board for the `tse_`/`otc_`
  prefix; unknown codes probe both.
- `mcp_server/api/index.py::quote` — the tool; stamps `phase` + `price_is_indicative` from
  [[session-state]].
- Tests: `tests/test_quote.py`.

## Non-obvious behaviour
- **Serverless constraint:** the market-wide MIS poller (~40–60 batched calls, needs persistent
  state) cannot run on the stateless Vercel function — same reason scan_limit_board is EOD-only.
  This tool is deliberately watchlist-scoped.
- `z='-'` before the first print → `last_price: null` (never a fabricated price / false limit hit).
- `is_at_limit` uses TWSE's authoritative `u`/`w`, never a recomputed limit.
- MIS returns an empty-code row for an unknown symbol; the tool drops those so a bad code lands in
  `missing`, not as a blank quote.
- During 08:30–09:00 the price is a 試撮 simulation → `price_is_indicative: true` + warning.
