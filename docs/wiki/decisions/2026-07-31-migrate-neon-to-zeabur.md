---
title: Migrate Postgres from Neon to self-hosted Zeabur
type: decision
slug: 2026-07-31-migrate-neon-to-zeabur
date: 2026-07-31
updated: 2026-07-31
attributed_to: [niko]
belongs_to: [system-architecture]
source: chat
status: active
tags: [architecture, database, neon, zeabur, migration]
related: [system-architecture, 2026-05-07-neon-over-supabase, view-ticker-momentum-refresh-break, infrastructure-accounts]
---

## Context

Niko deployed a PostgreSQL service on Zeabur and asked to move the alphatecx warehouse off Neon onto it. Neon had been the store since [2026-05-07](2026-05-07-neon-over-supabase.md).

Audit found no Neon lock-in: server was stock Postgres 17.10 with only `plpgsql` installed, and every caller reads `os.getenv("DATABASE_URL")` (`src/config.py:11`). The `neon_auth` schema was an unused scaffold (all tables 0 rows).

## Decision

Migrate via `pg_dump -Fc` → `pg_restore`, keeping Neon live as rollback. Target: Zeabur Postgres **18.4** at `8.209.197.81:32046`, db `zeabur`, user `root`.

## How it was done

- Local `pg_dump`/`pg_restore` are 14.19 and refuse a 17/18 server. Both were run inside a `postgres:18` container instead.
- `--no-owner --no-acl --exclude-schema=neon_auth`.
- Roles are cluster-level and never travel in a dump. 20 tables carry 24 RLS policies bound to `mcp_viewer`, so that role was created on the target **before** restore or every policy would have errored.

## Outcome

26 of 27 relations match source exactly by `count(*)`. Indexes 56 = 56, policies 24 = 24, real constraints identical (2 FK / 21 PK / 1 unique). `ANALYZE` run. 295 MB restored.

`pg_constraint` shows 138 rows on the target vs 24 on Neon — that is PG18 cataloguing NOT NULL constraints (114 of type `n`), a version behaviour change, not a schema difference. Don't read it as drift.

`view_ticker_momentum` is the one relation that did **not** come over populated — its `REFRESH` failed on a genuine pre-existing defect, see [view-ticker-momentum-refresh-break](../topics/view-ticker-momentum-refresh-break.md).

## Consequences

- **Collation changed: `C.UTF-8` (Neon) → `en_US.utf8` (Zeabur).** Encoding is UTF8 on both and Chinese text survived byte-for-byte (md5 of `company_name` matches), but `ORDER BY` on text columns now sorts differently. Expect dashboard row order to shift; it is not corruption. Sequences (`ingestion_log_id_seq`=1996, `sc_edges_edge_id_seq`=36) match, so the next harvest insert won't collide.
- **Zeabur has TLS disabled.** `sslmode=require` is rejected outright (`pg_stat_ssl.ssl = f`), so the new `DATABASE_URL` must drop it. Neon enforced TLS; this does not, so superuser credentials and query payloads now cross the public internet in cleartext on a port open to scanners. Mitigation is Zeabur private networking or a tunnel — unresolved as of this entry.
- Two Neon-specific workarounds in `daily_harvest.yml` become obsolete: the `&gssencmode=disable` suffix and the `/etc/hosts` IPv4 pin (which points at a Neon hostname and must come out).
- `sql/003_rls.sql` hardcoded `GRANT CONNECT ON DATABASE postgres` — wrong on every host we've used (`neondb`, then `zeabur`). Now resolved at runtime via `current_database()` inside a `DO` block.

## Cutover — done 2026-07-31

- `sql/002_views.sql` matview fix, `018_riskguard.sql`, `003_rls.sql` and `014_dim_ticker_classify.sql` applied to Zeabur. Applied via `psql`, not `apply_schema.py`: there is no venv here and `psycopg` isn't installed system-wide.
- `018_riskguard.sql` had **never been applied anywhere** — the 10 `rg_*` tables were created for the first time on Zeabur.
- `apply_schema.py` now lists `014` in the `--rls` branch (it GRANTs to `mcp_viewer`, so it can't run before `003` creates the role).
- `mcp_viewer` password regenerated; stored in `.env` (gitignored, `chmod 600`). Verified end-to-end: connecting *as* `mcp_viewer` reads `view_ticker_momentum` (10,584), `dim_ticker` (13,500) and `rg_positions`.
- `.env` and the GitHub Actions `DATABASE_URL` secret both repointed. The secret ends `?sslmode=disable` **deliberately** — all three workflows build `${{ secrets.DATABASE_URL }}&gssencmode=disable`, so a secret with no query string would push `&gssencmode=disable` into the database name.
- The `/etc/hosts` "Pin Neon hostname to IPv4" step removed from all three workflows; Zeabur's host is a literal IPv4.
- `pytest -q`: 191 passed, 5 skipped.
- The matview fix was also applied to **Neon**, which was suffering the same broken refresh; both hosts now hold 10,584 fresh rows.

## Remaining

~~**The Vercel deployment still points at Neon**~~ — **superseded the same day.** The env switch was never performed: the MCP server moved to Zeabur instead, so it now reads Postgres over the project's private network. See [2026-07-31-mcp-server-vercel-to-zeabur](2026-07-31-mcp-server-vercel-to-zeabur.md).

What that does *not* resolve: the GitHub Actions harvesters still reach `8.209.197.81:32046` from outside Zeabur, so the write path continues to send credentials in cleartext. Neon and Vercel both stay live as rollback.

## Zeabur CLI

Authenticated 2026-07-31 with a token from [niko]. The project is `alphatecx` (`6a6c3c70c553a2bc513cf1ce`), holding one `postgresql` service (`6a6c3e4d2e9443830f4905ae`).

**Install from GitHub releases, not npm.** `@zeabur/cli` on npm is abandoned at `0.2.9`, and that build targets a dead `gateway.zeabur.com` — it now serves a Traefik default self-signed cert, so every call fails as `x509: certificate signed by unknown authority`. That reads like a local CA/proxy fault and isn't one. Only `v0.21.0`+ uses the live `api.zeabur.com`. Release assets are bare binaries, not tarballs:

```bash
curl -sL -o zeabur https://github.com/zeabur/cli/releases/download/v0.21.0/zeabur_0.21.0_darwin_arm64
chmod +x zeabur
./zeabur auth login --token "$ZEABUR_TOKEN"
```

The token is stored in `~/.config/zeabur`; it was pasted in cleartext into a chat transcript, so rotate it in the dashboard once the cutover is finished.
