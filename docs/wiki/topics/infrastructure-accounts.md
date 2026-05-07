---
title: Infrastructure accounts
type: topic
slug: infrastructure-accounts
date: 2026-05-08
updated: 2026-05-08
belongs_to: [system-architecture]
source: synthesis
status: active
tags: [infra, accounts, vendors]
related: [2026-05-07-neon-over-supabase, 2026-05-07-v2-review-fixes]
---

## Summary
Where the production resources live and which login/org owns each. Recorded so future-you (or a fresh agent) doesn't waste a session hunting for a console.

## Neon Postgres

- **Organization:** `Tecxmate` (`org-muddy-hill-84308768`)
- **Project:** `alphatecx` (`restless-butterfly-45054019`)
- **Console:** <https://console.neon.tech/app/projects/restless-butterfly-45054019>
- **Region:** AWS `us-east-1` (proxy host `c-5.us-east-1.aws.neon.tech`)
- **Postgres version:** 17
- **Plan:** Free tier — 0.25 CU fixed, 512 MiB branch logical-size limit, 6h history retention
- **Created:** 2026-04-29 (originally provisioned for v1; v2 reuses it)
- **Roles:**
  - `neondb_owner` — writer; used by harvester, backfill, schema migrations. DSN in root `.env` as `DATABASE_URL`.
  - `mcp_viewer` — read-only role created 2026-05-07; SELECT on raw + view + dim_supply_chain + ingestion_log; no INSERT/UPDATE/DELETE; password generated locally and stored in root `.env` as `MCP_VIEWER_PASSWORD`. DSN in `mcp_server/.env` as `MCP_DATABASE_URL`. Used by both local MCP and Vercel-deployed MCP.
- **Login:** the Google or GitHub identity tied to "Tecxmate" — separate from the Vercel `nikolasdoan` account.

## Vercel

- **Account:** `nikolasdoan`
- **Org/team:** `nikolasdoans-projects` (Hobby / personal team)
- **Projects:**
  - `alphatecx-mcp` (`prj_ChmH8nsrEwcIq6GQ9QDmjzNBLRb0`) — v1 MCP, lives at `/Users/niko/antigravity/alphatecx/mcp_server`.
  - `alphatecx-v2-mcp` — v2 MCP, lives at `/Users/niko/antigravity/alphatecx-2/mcp_server`. Public URL: <https://alphatecx-v2-mcp.vercel.app>.
- **Env vars (v2 production):** `MCP_DATABASE_URL`, `MCP_BEARER_TOKEN`. `DATABASE_URL` is intentionally NOT set in production — would leak writer creds onto the public function.

## Telegram

- Bot token + chat id in root `.env` (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`); reused from v1.

## Open questions
- Free-tier Neon is at ~363 MB / 512 MB after Gemini's T86 prune. Need a plan if backfill grows beyond that — paid tier vs. tighter retention.
- No automatic Neon backups beyond the 6h history window. Acceptable for now; reconsider once positions/journal data starts living here too.

## History
- 2026-04-29 — Neon project provisioned for v1.
- 2026-05-07 — v2 schema applied; `mcp_viewer` role provisioned ([decision](../decisions/2026-05-07-v2-review-fixes.md)).
- 2026-05-08 — Vercel `alphatecx-v2-mcp` project created; MCP deployed pointing at `mcp_viewer` DSN.
