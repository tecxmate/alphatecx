---
title: Upgrade from Stateless MCP to Systematic Supabase Pipeline
type: decision
slug: 2026-05-07-stateful-upgrade
date: 2026-05-07
attributed_to: [niko]
belongs_to: [alphatecx]
source: chat
status: active
tags: [architecture, supabase, pipeline]
related: [system-architecture, alphatecx-v1, taiwan-ai-supply-chain]
---

## Context

The existing alphatecx system (v1) uses a stateless MCP pattern: each Claude query triggers a live TWSE API call, returns raw JSON, and has no memory of previous days. This makes it impossible to spot multi-day accumulation trends, aggregate flows by sector, or answer questions like "Compare the 5-day foreign capital flow between AI Energy and Server ODMs." Niko described the current state as "I only query data per question chat not systematic yet."

## Decision

Build a v2 architecture centered on Supabase (Postgres) as the single source of truth. A daily scheduled Python job (GitHub Actions + Polars) harvests TWSE data at 16:00 CST, stores it in Supabase, and a materialized view (`view_sector_momentum`) pre-computes sector-level flows. Claude's MCP queries the database, not the raw APIs.

## Rationale

- **Accumulation over time**: storing daily data enables 3-day, 5-day, and multi-week trend analysis — the core value proposition for the 3-month outlook. [niko]
- **Lean, not heavy**: avoids Kubernetes/Airflow; GitHub Actions is free and zero-maintenance. [gemini-agent]
- **Eliminates rate limits**: TWSE API is called once/day by a cron job, not per-query. [gemini-agent]
- **Existing MCP pattern works**: v1 already proves the MCP-to-Claude bridge; v2 just swaps the data source from live API to pre-loaded Postgres. [niko]
- **Supply chain mapping baked in**: `dim_supply_chain` table lets Claude answer sector questions without prompt-engineering every time. [gemini-agent]

## Consequences

- A new Supabase project must be provisioned.
- The `dim_supply_chain` table must be seeded with all ticker-to-pillar mappings from the supply chain map.
- The v1 MCP server continues running during development; some tools may be ported or retired.
- A Python/Polars extraction script must be written and tested.
- The tech team receives a handover document based on the architecture topic.

## Provenance

- Discussed on 2026-05-07 between [niko] (owner) and [gemini-agent] (agent), ingested by [antigravity-agent].
- Source: `docs/chats/chat-gemini.txt`
