---
title: Infrastructure accounts
type: topic
slug: infrastructure-accounts
date: 2026-05-08
updated: 2026-08-08
belongs_to: [system-architecture]
source: synthesis
status: active
tags: [infra, accounts, vendors]
related: [2026-05-07-neon-over-supabase, 2026-05-07-v2-review-fixes]
---

## Summary
Where the production resources live and which login/org owns each. Recorded so future-you (or a fresh agent) doesn't waste a session hunting for a console.

## Neon Postgres

**Active project (since 2026-05-08):**
- **Endpoint:** `ep-cold-lab-aqklxtzs` (region `c-8.us-east-1.aws`)
- **Region:** AWS `us-east-1`
- **Postgres version:** 17.8
- **Plan:** Free tier
- **Project name:** `alphatecx-v2` (or whatever name was assigned at creation)
- **Created:** 2026-05-08, in a Neon account Niko owns directly (not Tecxmate)
- **Console:** <https://console.neon.tech> — log in with the account you own.
- **Auth setup:** project was created with **Neon Auth** enabled (`neon_auth.*` schema present). Important quirk: this set the database `search_path` to `''` instead of `"$user", public, neon_auth`. Application code compensates via `psycopg_pool` `configure` hook in `loader.py` and `db_v2.py` which runs `SET search_path TO public, neon_auth` per-connection. The Neon pooler rejects `options=-csearch_path` at startup, so the configure hook is the only viable path.
- **Roles:**
  - `neondb_owner` — writer; used by harvester, backfill, schema migrations. DSN in root `.env` as `DATABASE_URL`.
  - `mcp_viewer` — read-only role; SELECT on raw + view + dim_supply_chain + ingestion_log; no INSERT/UPDATE/DELETE; password in root `.env` as `MCP_VIEWER_PASSWORD`. DSN in `mcp_server/.env` as `MCP_DATABASE_URL`.
- **Usage-accounting note:** The console's "monthly storage allowance" warning is project/account usage, not necessarily just the active branch's current `pg_database_size()`. Check the org **Billing** page or the banner's **Review usage** detail for root-branch storage, child-branch storage, instant-restore/history storage, compute CU-hours, and network transfer.

**Old project (decommission window):**
- **Organization:** `Tecxmate` (`org-muddy-hill-84308768`)
- **Project:** `alphatecx` (`restless-butterfly-45054019`)
- **Console:** <https://console.neon.tech/app/projects/restless-butterfly-45054019>
- **Status:** running but no longer written to. DSNs preserved in `.env.old-tecxmate-20260508` (root + `mcp_server/`) as a 24h safety net. Login was tied to a Tecxmate-affiliated account that Niko could not access from his usual identity, which is why the migration happened.
- **Decommission:** delete from Neon console after 2026-05-09 once the new project is verified stable.

## Vercel

- **Account:** `nikolasdoan`
- **Org/team:** `nikolasdoans-projects` (Hobby / personal team)
- **Projects:**
  - `alphatecx-mcp` (`prj_ChmH8nsrEwcIq6GQ9QDmjzNBLRb0`) — v1 MCP, lives at `/Users/niko/antigravity/alphatecx/mcp_server`.
  - `alphatecx-v2-mcp` — v2 MCP, lives at `/Users/niko/antigravity/alphatecx-2/mcp_server`. Public URL: <https://alphatecx-v2-mcp.vercel.app>.
- **Env vars (v2 production):** `MCP_DATABASE_URL`, `MCP_BEARER_TOKEN`. `DATABASE_URL` is intentionally NOT set in production — would leak writer creds onto the public function.

## GitHub repository

- **Canonical remote (since 2026-08-08):** `https://github.com/tecxmate/alphatecx.git` — the repo
  now lives under the **`tecxmate` org**.
- **Old personal remote:** `https://github.com/nikolasdoan/alphatecx.git`. Still works via GitHub's
  automatic redirect, but that is fragile — update local clones:
  ```
  git remote set-url origin https://github.com/tecxmate/alphatecx.git
  ```
  Observed 2026-08-08: a `git push` from a clone still pointing at the personal URL succeeded but
  printed `remote: This repository moved. Please use the new location: …/tecxmate/alphatecx.git`.
- **Deliberate move — access is fine.** [niko] (Nikolas) moved the repo to the tecxmate org
  himself; **he is the CEO of Tecxmate**, and the move was made specifically so co-founder [brian]
  can have access. This is *not* the access trap that hit the Neon side in 2026-05-08 (that was an
  orphaned Tecxmate-affiliated Neon login [niko] couldn't reach). The org is under [niko]'s control.
  It does reverse the earlier "repo moved back to personal" (commit `75e40b7`) — now the org is the
  intended home because the project is going commercial with a co-founder.

- **Zeabur `mcp` service auto-deploys from `main`** (git-connected to `tecxmate/alphatecx`; confirmed 2026-08-09 via `zeabur deployment list` — one RUNNING deployment per commit, source `refs/heads/main`). The earlier "CLI-uploaded, manual deploy" note is superseded. `apply_delta.py` still applies DB migrations manually to the Zeabur public owner endpoint (`8.209.197.81:32046/zeabur`).

## Telegram

- Bot token + chat id in root `.env` (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`); reused from v1.
- Scheduled Telegram briefs from `news_harvest.yml` are disabled as of 2026-06-17. The workflow still harvests news on schedule, but scheduled runs force `MODE='none'`; manual `workflow_dispatch` can still send a selected brief mode.

## Open questions
- No automatic Neon backups beyond the 6h history window. Acceptable for now; reconsider once positions/journal data starts living here too.

## History
- 2026-04-29 — Neon project provisioned for v1.
- 2026-05-07 — v2 schema applied; `mcp_viewer` role provisioned ([decision](../decisions/2026-05-07-v2-review-fixes.md)).
- 2026-05-08 — Vercel `alphatecx-v2-mcp` project created; MCP deployed pointing at `mcp_viewer` DSN.
- 2026-08-08 — GitHub repo moved to the `tecxmate` org (`github.com/tecxmate/alphatecx`); local
  clone still on the personal URL and reaching it via GitHub's redirect.
- 2026-05-27 — Scheduled GitHub Actions harvest/news crons disabled to reduce Vercel CPU-hour usage; workflows remain manually runnable ([decision](../decisions/2026-05-27-disable-scheduled-harvest-crons.md)).
- 2026-06-11 — Neon reached the free-tier storage cap at 490 MB. Pruned old all-market raw rows, compacted affected tables with `VACUUM FULL`, and reduced the database to 158 MB ([decision](../decisions/2026-06-11-neon-retention-prune.md)).
- 2026-06-11 — Neon docs confirmed console usage is broken down by root storage, child-branch storage, instant-restore/history storage, compute, and transfer; a top-level monthly storage banner can lag or reflect project/account usage beyond the current active database size.
- 2026-06-17 — Scheduled pre-market/intraday Telegram briefs from `news_harvest.yml` disabled while scheduled news harvesting remains active ([decision](../decisions/2026-06-17-disable-scheduled-telegram-briefs.md)).
