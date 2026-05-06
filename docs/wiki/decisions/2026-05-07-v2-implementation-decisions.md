---
title: v2 Implementation Decisions
type: decision
slug: 2026-05-07-v2-implementation-decisions
date: 2026-05-07
attributed_to: [niko]
belongs_to: [alphatecx, system-architecture]
source: chat
status: active
tags: [architecture, supabase, telegram, backfill]
related: [2026-05-07-stateful-upgrade, system-architecture, alphatecx-v1]
---

## Context

Follow-up to the stateful upgrade decision. Niko answered all 6 open questions and added a new requirement: historical data backfill.

## Decisions

1. **Database: Supabase** (confirmed). v1 uses Neon for bot state — Supabase is a new, separate project for market data.
2. **Ticker codes: queried from API**, not manually seeded. The TWSE T86 endpoint already returns all tickers with their codes; we can dynamically populate `dim_supply_chain` by matching codes from the API response.
3. **v1 stays running**. The existing `alphatecx` workspace continues operating. v2 is additive, not a replacement.
4. **Ingestion scope: maximum coverage, T86 priority**. Ingest as many TWSE/TPEX endpoints as possible. Priority order: T86 (institutional flow) → MI_QFIIS (foreign holdings) → margin data → OHLCV → monthly revenue.
5. **Alerting: Telegram**. Reuse the existing Telegram bot infrastructure from v1.
6. **Tech team: Claude Code agents**. Antigravity (this agent) starts now; more Claude Code agents join tomorrow. Wiki is the handover mechanism.
7. **Historical backfill: yes**. Accumulate past data for better prediction. Backfill ~90 trading days to have meaningful trend baselines from day one.

## Rationale

- Supabase over Neon for v2 keeps the databases separated by concern: Neon = bot state, Supabase = market data + supply chain analysis. [niko]
- Dynamic ticker querying from the API avoids manual maintenance of a ticker-to-pillar mapping that would go stale. The supply chain classification can be a separate enrichment step. [niko]
- Keeping v1 running means zero risk during v2 development — the existing MCP and Telegram alerts continue working. [niko]
- Historical backfill is critical: the materialized views (`view_sector_momentum`) are useless with only 1 day of data. 90 trading days (~4.5 months) gives enough history for 5-day, 20-day, and even monthly trend analysis. [niko]

## Consequences

- Supabase project needs to be provisioned (Niko or agent via CLI).
- The backfill script must respect TWSE rate limits (they throttle at ~3-5 req/sec). Needs sleep intervals.
- The `dim_supply_chain` table becomes semi-dynamic: tickers from API, pillar/node classification added as enrichment.
- Telegram bot token and chat ID can be reused from v1's `.env`.

## Provenance

- Discussed on 2026-05-07 between [niko] (owner) and [antigravity-agent] (agent).
