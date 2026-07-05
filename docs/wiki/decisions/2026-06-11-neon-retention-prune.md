---
title: Neon retention prune after storage cap
type: decision
slug: 2026-06-11-neon-retention-prune
date: 2026-06-11
attributed_to: [niko, codex-agent]
belongs_to: [system-architecture, infrastructure-accounts, historical-backfill]
source: chat
status: active
tags: [database, neon, retention, operations]
related: [2026-05-07-neon-over-supabase, historical-backfill, infrastructure-accounts]
---

## Context

Niko reported that the Neon project had consumed its storage allowance, and the Neon console showed the project at the free-tier limit. Live inspection found `pg_database_size(current_database())` at 490 MB, with most space in all-market raw tables: `raw_twse_t86` at 129 MB, `raw_twse_holdings` at 119 MB, and `raw_twse_margin` at 110 MB.

## Decision

Prune old bulk market data and keep a bounded recent window: 60 trading days for `raw_twse_t86`, `raw_twse_valuation`, and `raw_twse_index`; 30 trading days for `raw_twse_holdings` and `raw_twse_margin`; the latest 3 `lead_lag` snapshots; news from 2026 onward; and flow-signal rows only for retained T86 dates. Keep long `raw_twse_ohlcv` history because it was only 14 MB and remains useful for indicators and backtests.

## Rationale

The original historical-backfill plan expected holdings and margin depth to be around 30 trading days. Current views and MCP workflows mostly read the latest 20 trading days, while flow z-scores need only a modest buffer beyond the 20-day window. `lead_lag` is a derived snapshot table and can be regenerated, so keeping every prior snapshot is not worth the storage cost. [codex-agent]

## Consequences

After deletes and `VACUUM (FULL, ANALYZE)` on the affected tables, Neon database size dropped from 490 MB to 158 MB. Retained ranges after cleanup: T86 from 2026-03-05 to 2026-06-08, holdings from 2026-04-15 to 2026-06-08, margin from 2026-03-26 to 2026-06-08, valuation/index from late February 2026 onward, and `lead_lag` snapshots from 2026-05-22 to 2026-06-07.

One unrelated operational issue surfaced: `refresh_momentum_views()` failed on `view_ticker_momentum` because ticker `6241` produced a duplicate key under the materialized view's unique index. `refresh_quant_views()` succeeded. The duplicate-ticker view refresh should be handled as a separate data/modeling bug.

## Provenance

- Discussed and executed on 2026-06-11 between [niko] (owner) and [codex-agent] (agent).
