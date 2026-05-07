---
name: V2 review fixes
description: Code review of Gemini's V2 implementation and the remediation pass that followed.
type: decision
attributed_to: [antigravity-agent]
belongs_to: [system-architecture, mcp-server]
source: chat
date: 2026-05-07
---

# V2 senior-engineer review + remediation pass

## Context

Gemini built V2 (Neon Postgres pipeline + FastMCP server) on top of the V1 MCP that Claude wrote. Niko asked for a code-quality / integrity audit. This decision records the findings and what was fixed in the same turn.

## Findings

### Critical
1. **MCP runs with writer DB credentials.** `apply_schema.py` skipped `sql/003_rls.sql`, so the `mcp_viewer` role was never provisioned. The wiki claimed RLS was the security model, but in production the MCP connects with the same `DATABASE_URL` as the loader.
2. **SQL identifier injection footgun.** `query_ticker_momentum` validated `order_col`, but `query_sector_momentum` and `query_compare_nodes` interpolated identifiers without validation.

### High
3. `view_sector_momentum.top_ticker_5d_name` and `top_ticker_5d` were two separate correlated subqueries grouped on different keys — they could return values from different rows.
4. `datetime.utcnow()` in `_today_iso` and `log_ingestion`. TWSE is Asia/Taipei (UTC+8); `_as_of` rolled over 8 hours early.
5. `telegram._fetch_top_sectors` swallowed all exceptions silently — broken view = empty digest, no log.
6. `sql/003_rls.sql` used `CREATE POLICY IF NOT EXISTS` (PG15+ only) and contained a literal `'CHANGE_ME_IN_SUPABASE'` placeholder password.

### Medium
7. **Idempotency gap.** `upsert_t86` used autocommit `executemany`, then `log_ingestion` ran separately. A mid-batch crash left a partially-written day marked `ok`, which `get_ingested_dates` then skipped on retry.
8. `executemany` for ~7000 × 90 days is slow (one round-trip per row) — flagged but not changed.
9. `apply_schema.py` ad-hoc `;`/`$$` statement splitter was fragile.
10. `sc_data_status` ran `COUNT(*)` on every raw table on each call.

## What was fixed

| # | File | Change |
|---|------|--------|
| 2 | `mcp_server/api/db_v2.py` | Centralized `_ALLOWED_FLOW_COLS` + `_safe_col` helper; applied to all three call sites. |
| - | `mcp_server/api/db_v2.py` | DSN now reads `MCP_DATABASE_URL` first, falls back to `DATABASE_URL`. |
| 4 | `mcp_server/api/index.py` | `_today_iso` uses `Asia/Taipei`. |
| - | `mcp_server/api/index.py` | Fail-fast on missing `MCP_BEARER_TOKEN` instead of silently mounting nothing. |
| 4, 7 | `src/harvester/loader.py` | `Asia/Taipei` for ingestion timestamps; new `atomic()` ctx manager; all `upsert_*` and `log_ingestion` accept optional `c=` cursor. |
| 7 | `src/backfill/run.py` | Each backfill iteration wraps upsert + log_ingestion in `atomic()`. |
| 5 | `src/alerts/telegram.py` | `_fetch_top_sectors` logs exception via `log.exception`. |
| 3 | `sql/002_views.sql` | New `ranked_tickers` + `top_per_node` CTEs; single source for top ticker name + id. |
| 6 | `sql/003_rls.sql` | Password read from `mcp_viewer.password` GUC; policies use `DROP IF EXISTS` + `CREATE` for PG portability. |
| 9 | `apply_schema.py` | Splitter removed; `--rls` flag opt-in; reads `MCP_VIEWER_PASSWORD` env. |
| 10 | `mcp_server/api/db_v2.py` | `sc_data_status` uses `pg_stat_user_tables.n_live_tup`. |

## Open follow-ups (NOT done in this pass)

- **Provision `mcp_viewer` role on Neon and re-point MCP at it.** Niko opted to stage this separately. Until done, MCP retains write credentials.
- **Refresh `view_sector_momentum`** after deploy: `SELECT refresh_momentum_views();` — required because the view definition changed.
- **Switch `executemany` to `copy()` / `execute_values`** for backfill performance.
- **TW holiday calendar** for `trading_day_candidates` (saves rate-limit budget on closed days).

## Why

The architecture and idempotency primitives were sound; the gaps were in security boundary (MCP role) and edge-case correctness (timezone, view subquery, partial-failure). Fixing them is cheap individually and high-leverage in aggregate.
