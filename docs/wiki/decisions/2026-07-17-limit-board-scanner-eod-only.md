---
title: scan_limit_board ships EOD-only; realtime deferred
type: decision
slug: 2026-07-17-limit-board-scanner-eod-only
date: 2026-07-17
updated: 2026-07-17
attributed_to: [niko]
belongs_to: [limit-board-scanner, system-architecture]
source: chat
status: active
tags: [mcp, scanner, twse, tpex, vercel, scope]
related: [limit-board-scanner, system-architecture, taiwan-ai-supply-chain]
---

## Context
Niko supplied a written spec (`scan_limit_board_spec.md`) for a Taiwan limit-up/limit-down
board scanner to add to the Alpha MCP server, to replace manual screenshot-reading of the
漲停/跌停 board and feed the `tw-equity-alpha` Mode 4 board-triage loop. The spec called for
`mode: "realtime" | "eod" = auto`, defaulting to realtime during the 09:00–13:30 Taipei
session via the TWSE MIS endpoint.

Two premises in the spec did not survive contact with this repo:

1. **Realtime does not fit the deployment.** The MCP server runs as a stateless Vercel
   serverless function (`mcp_server/vercel.json`). The spec's own §8 budgets a full-market
   MIS sweep at ~40–60 batched calls with a 3–5 s stagger, i.e. ~3–4 minutes — well past the
   function timeout. `lock_time` ("first timestamp `at_limit` became true, persist per ticker
   per day") additionally needs state across polls that a stateless function does not have.
   The spec acknowledged this ("or maintain a persistent poller and serve from cache") but
   left it unresolved.
2. **The board cannot be served from our database.** The spec's §5 enrichment join assumes
   the local tables can supply the board. They cannot: `raw_twse_ohlcv` is harvested only for
   the classified universe plus a top-500 backfill (`src/harvester/daily.py`), ~58 tickers
   with signals, against a ~1,950-name market.

## Decision
Ship `scan_limit_board` **EOD-only**. `mode="realtime"` returns an explicit not-implemented
error naming the serverless constraint rather than silently degrading. The board itself is
fetched **live from the exchanges at call time** (two HTTP requests — TWSE `MI_INDEX`
`type=ALLBUT0999` and TPEX `dailyQuotes` `type=AL`), and enrichment is joined from Neon
afterwards in a single batched query.

## Rationale
Niko chose EOD-only from three options (EOD-only / EOD + realtime over a bounded candidate
set / EOD + full-market realtime via a GitHub Actions poller). [niko]

EOD-only is the smallest correct thing that makes the actual use case work: board triage of
any session, including post-mortems of past sessions, which is what the spec's §9 examples
mostly ask for. Realtime full-market remains available later via a poller + cache table
without changing the tool's contract.

Fetching the board live rather than from Neon is not a workaround — it is the only option
that yields full-market coverage, and it costs two requests. Deepening the OHLCV harvest to
all ~2,000 names purely to serve this tool would have been a large, ongoing storage and
rate-limit commitment, and was rejected against the
[2026-06-11 Neon retention prune](2026-06-11-neon-retention-prune.md) which deliberately cut
all-market raw data to compact the database.

## Consequences
- New module `mcp_server/api/limit_board.py`; new tool `scan_limit_board` in
  `mcp_server/api/index.py`; new batch join `db_v2.query_limit_board_enrichment`.
- The tool makes live outbound calls to TWSE/TPEX on every invocation — a first for this MCP
  server, whose other tools are Neon-only. Exchange downtime degrades the tool; retries are
  built in.
- `mode="realtime"`, and therefore `lock_time`, are unavailable. `lock_time` is always null.
- Three spec deviations were required to make the tool correct; they are recorded in
  [limit-board-scanner](../topics/limit-board-scanner.md) rather than here.
- Coverage is common stock only. ETFs/ETNs/warrants are excluded — they carry a different
  tick scale and some foreign-tracking ETFs have no price limit at all.

## Provenance
- Discussed on 2026-07-17 between [niko] (owner) and [antigravity-agent] (agent).
- Spec: `~/Downloads/scan_limit_board_spec.md`.
- Validated against the live 2026-07-16 session before merge.
