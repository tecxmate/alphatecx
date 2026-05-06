---
title: Switch from Supabase to Neon Postgres
type: decision
slug: 2026-05-07-neon-over-supabase
date: 2026-05-07
attributed_to: [niko]
belongs_to: [system-architecture]
source: chat
status: active
tags: [architecture, database, neon]
related: [system-architecture, alphatecx-v1, 2026-05-07-stateful-upgrade]
---

## Context

The original Gemini chat proposed Supabase as the database. During implementation, Supabase CLI auth and dashboard login proved friction-heavy. Niko asked: "Can we use Neon instead? Is Supabase necessary?"

## Decision

Use Neon Postgres (same as v1) instead of Supabase. Reuse the existing Neon project and `DATABASE_URL`.

## Rationale

- **Everything we need is standard Postgres**: tables, materialized views, upserts, indexes, RLS — Neon does all of this identically to Supabase. [antigravity-agent]
- **Already proven**: v1's `psycopg3` pool + Neon is battle-tested and Niko already has the account/credentials. [niko]
- **Zero friction**: direct `psql` / `psycopg` access vs Supabase dashboard login + CLI auth issues. [antigravity-agent]
- **Supabase's unique features (Edge Functions, official MCP) aren't needed**: we use Python scripts + GitHub Actions for ingestion, and v1 already has a working custom MCP. [antigravity-agent]
- **Same Neon project** can hold both v1 bot state tables and v2 market data tables without conflict. [niko]

## Consequences

- Replaced `supabase-py` with `psycopg[binary]` + `psycopg-pool` in requirements
- Loader uses `executemany` with parameterized SQL (same pattern as v1's `db.py`)
- `.env` uses `DATABASE_URL` instead of `SUPABASE_URL` + `SUPABASE_SERVICE_KEY`
- No Supabase Edge Functions — Telegram alerts handled by Python directly
- MCP will use custom FastMCP (like v1) instead of Supabase MCP

## Provenance

- Discussed on 2026-05-07 between [niko] (owner) and [antigravity-agent] (agent).
