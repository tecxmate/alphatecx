---
title: Database backups & restore runbook
type: topic
slug: db-backups
date: 2026-08-11
updated: 2026-08-16
attributed_to: [claude-agent]
belongs_to: [system-architecture, infrastructure-accounts]
source: chat
status: active
tags: [postgres, backup, restore, zeabur, ops]
related: [2026-07-31-migrate-neon-to-zeabur, system-architecture, paid-connector-deploy]
---

## Why this exists

The 2026-07-31 migration moved the database to a **self-hosted Zeabur Postgres — which has
no backups**. Zeabur's prebuilt Postgres ships none by default, and the Neon "rollback"
instance froze at cutover, going staler by one trading day every day. Until 2026-08-11 a
single volume loss meant losing the entire harvested history (T86 flows, OHLCV, news,
Risk Guard state, customers/usage) with no recovery path. The paid connector made that an
unacceptable posture: customer identities and billing state now live in this database too.

## What runs

`.github/workflows/db_backup.yml` — 18:30 Taipei, weekdays (after the 16:30 harvest chain,
so each dump captures the session it belongs to), plus `workflow_dispatch` for on-demand
dumps (take one **before** any risky migration).

- `pg_dump --format=custom --no-owner --no-privileges` over the same public endpoint the
  harvesters use, with the same `&gssencmode=disable` suffix (same libpq hang otherwise).
- The dump's TOC is verified with `pg_restore --list`, including presence of
  `raw_twse_t86`, `raw_twse_ohlcv`, `dim_ticker`, `customers` — a truncated dump fails
  the run instead of failing the restore.
- Uploaded as a GitHub Actions **artifact, 5-day retention** on the private repo.
- Failure alerts to Telegram, same channel as the harvest.

Five dailies is point-in-time depth, not an archive. If longer retention is ever needed
(or the Actions storage quota — 500 MB on the free tier — starts rejecting uploads), the
next step is external object storage (R2/S3), not longer artifact retention.

### Why `--no-owner --no-privileges`

The restore target is a fresh instance whose roles don't exist yet. Ownership and grants
are **code, not data** in this repo: `apply_schema.py --rls` recreates `mcp_viewer` and
every grant (including the `024` read backfill) deterministically. Restoring privileges
from a dump would just reintroduce whatever grant drift the dump happened to contain.

## Restore runbook

A backup that has never been restored is a hope, not a backup. Walk this once on a scratch
instance.

1. **Get a dump**: repo → Actions → "DB Backup" → pick a run → download the artifact.
2. **Provision Postgres** (fresh Zeabur service, or local Docker for a drill).
3. **Restore the data** (`-d` must point at an existing, empty database):

   ```bash
   pg_restore --no-owner --no-privileges -d "$NEW_DATABASE_URL" alphatecx-YYYY-MM-DD.dump
   ```

4. **Recreate role + grants** — the dump deliberately carries neither:

   ```bash
   DATABASE_URL="$NEW_DATABASE_URL" MCP_VIEWER_PASSWORD=... python apply_schema.py --rls
   ```

5. **Verify grants landed** — `apply_delta.py` reads privileges back and fails loudly:

   ```bash
   ZEABUR_DATABASE_URL="$NEW_DATABASE_URL" python apply_delta.py --yes
   ```

6. **Repoint consumers**: the `mcp` service's env vars in Zeabur, the GitHub Actions
   `DATABASE_URL` secret (keep the `?sslmode=disable` query string — the workflows append
   `&gssencmode=disable` to it), `cron` and `worker` env vars.
7. **Smoke-test**: `/health`, then one data tool (`q_valuation` on 2330), one rg tool
   (`rg_status`), and `my_profile` for the customers table.

## Known limits

- **Daily granularity.** Anything written between the last dump and a failure is lost.
  Acceptable: harvest data re-ingests from TWSE by re-running the pipeline for missed
  dates (`python -m src.backfill.run`); the genuinely irreplaceable low-velocity tables
  (`customers`, `rg_journal`, `watchlist`, theses) change far slower than daily.
- **Credentials ride in the dump** (`customers.secret_hash` — sha256 of high-entropy
  tokens, not reversible; email addresses in plaintext). Artifacts are visible to repo
  collaborators, the same trust domain as the `DATABASE_URL` secret itself.
- **The dump crosses the public internet in cleartext**, like every GH-Actions DB
  connection since the TLS-less Zeabur cutover — this workflow adds no new exposure, but
  inherits the existing one (see the 2026-07-31 migration decision).

## History

- 2026-08-16 — Scheduled backup runs from 2026-08-12 through 2026-08-14 were failing before
  producing artifacts because the workflow installed `postgresql-client-17` while Zeabur runs
  Postgres 18.4; `pg_dump` refuses to dump a newer server. Updated the workflow to install
  `postgresql-client-18`.
