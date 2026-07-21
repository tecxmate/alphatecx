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
`quote(symbols, source)` returns realtime-ish quotes for a **watchlist** from one of two sources —
**Fugle** (keyed realtime feed, preferred) or **TWSE MIS** (no key, throttled) — including the
authoritative tick-rounded limit-up/down prices. Not a market scanner; breadth belongs to
[[limit-board-scanner]] / [[flow-leaders-scan]].

## Sources
- **Fugle** (`fugle.py`) — `GET api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}`,
  header `X-API-KEY`. Preferred: richer 5-level book, lower latency, no cookie/throttle dance.
  One call per symbol → capped at 40. Fugle returns `referencePrice` but not the band, so limit
  prices are computed via `limit_board.limit_up/down` (the same table scan_limit_board validated).
  Needs **`FUGLE_API_KEY`** (in `.env` locally; **must be added to Vercel env for production**).
- **MIS** (`quote.py`) — cookie-primed batch (≤50/call, cap 100). Fallback / no-key path.
- `source="auto"` (default) uses Fugle when the key is set, else MIS, and falls back to MIS if
  Fugle returns nothing. `response._quote_source` says which answered.

## Code
- `mcp_server/api/fugle.py` — Fugle client + pure `parse_quote` (unit-tested).
- `mcp_server/api/quote.py` — MIS client + pure `parse_msg`.
- `mcp_server/api/db_v2.py::ticker_markets` — resolves each code's board for the MIS `tse_`/`otc_`
  prefix; unknown codes probe both.
- `mcp_server/api/index.py::quote` — the tool; routes source, stamps `phase` +
  `price_is_indicative` from [[session-state]].
- Tests: `tests/test_quote.py`, `tests/test_fugle.py`.

## Non-obvious behaviour
- **Serverless constraint:** the market-wide MIS poller (~40–60 batched calls, needs persistent
  state) cannot run on the stateless Vercel function — same reason scan_limit_board is EOD-only.
  This tool is deliberately watchlist-scoped.
- `z='-'` before the first print → `last_price: null` (never a fabricated price / false limit hit).
- `is_at_limit` uses TWSE's authoritative `u`/`w`, never a recomputed limit.
- MIS returns an empty-code row for an unknown symbol; the tool drops those so a bad code lands in
  `missing`, not as a blank quote.
- During 08:30–09:00 the price is a 試撮 simulation → `price_is_indicative: true` + warning.
