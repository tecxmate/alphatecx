# Wiki Log

Append-only. Newest entries at the bottom. Standard prefix: `## [YYYY-MM-DD] <kind> | <subject>`.

`<kind>` ∈ `ingest | decision | chat | lint | external`.

Quick recent log: `grep "^## \[" docs/wiki/log.md | tail -10`.

## [2026-05-07] ingest | Wiki bootstrapped from Gemini chat transcript
attributed_to: [niko]   belongs_to: [alphatecx]
- Ingested `docs/chats/chat-gemini.txt` — Niko × Gemini conversation covering TWSE API analysis, Taiwan AI supply chain mapping (4 pillars), and v2 architecture proposal (Supabase + GitHub Actions + Polars)
- Created stakeholders: [niko](stakeholders/niko.md), [antigravity-agent](stakeholders/antigravity-agent.md), [gemini-agent](stakeholders/gemini-agent.md)
- Created topics: [alphatecx](topics/alphatecx.md), [alphatecx-v1](topics/alphatecx-v1.md), [taiwan-ai-supply-chain](topics/taiwan-ai-supply-chain.md), [system-architecture](topics/system-architecture.md)
- Created decision: [2026-05-07-stateful-upgrade](decisions/2026-05-07-stateful-upgrade.md) — upgrade from stateless MCP to Supabase pipeline
- Also inspected existing v1 codebase (`alphatecx` workspace): documented MCP server (10 tools), TWSE data layer, APEX TW strategy, and their limitations motivating v2

## [2026-05-07] decision | v2 implementation decisions resolved
attributed_to: [niko]   belongs_to: [alphatecx, system-architecture]
- Supabase confirmed (separate from v1's Neon); ticker codes queried from API dynamically
- v1 stays running; ingestion scope: max coverage, T86 priority; alerting: Telegram
- Tech team = Claude Code agents (Antigravity now, more tomorrow); wiki is the handover mechanism
- **Historical backfill approved**: ~90 trading days of T86, 30 days of holdings/margin, 90 days OHLCV
- Created [2026-05-07-v2-implementation-decisions](decisions/2026-05-07-v2-implementation-decisions.md)
- Created [historical-backfill](topics/historical-backfill.md) — backfill strategy with rate limits and storage estimates

## [2026-05-07] decision | Phase 1 implementation built
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Built complete Phase 1 codebase: SQL schema (3 files), Python harvester (6 modules), backfill script, daily harvest, Telegram alerts, GitHub Actions workflow
- `sql/001_schema.sql` — 6 data tables + ingestion_log with composite PKs
- `sql/002_views.sql` — `view_sector_momentum` + `view_ticker_momentum` materialized views with 1/3/5/10/20-day windows and consecutive buy day tracking
- `sql/003_rls.sql` — `mcp_viewer` read-only role with RLS policies
- `src/harvester/twse.py` — ported from v1's battle-tested `sources.py`, adapted for date-parameterized batch queries
- `src/harvester/transform.py` — Polars transformation layer
- `src/harvester/loader.py` — Supabase upserts with idempotency and gap detection
- `src/backfill/run.py` — backfill script: resumable, rate-limited, supports `--only` and `--days` flags
- `src/harvester/daily.py` — daily harvest for GitHub Actions
- `src/alerts/telegram.py` — daily summary + sector momentum alert
- `src/seed_supply_chain.py` — seeds ~27 companies from strategic map with AI pillar/node classification
- `.github/workflows/daily_harvest.yml` — cron at 16:30 CST with failure notification
- **Next**: provision Supabase project, fill `.env`, run schema SQL, then backfill

## [2026-05-07] decision | Switched from Supabase to Neon Postgres
attributed_to: [niko]   belongs_to: [system-architecture]
- Niko asked "Can we use Neon instead?" — answer: yes, Supabase is not necessary, everything is standard Postgres
- Rewrote `loader.py` from supabase-py to psycopg3 (same pattern as v1's `db.py`)
- Replaced requirements: `supabase` → `psycopg[binary]` + `psycopg-pool`
- Created [2026-05-07-neon-over-supabase](decisions/2026-05-07-neon-over-supabase.md)

## [2026-05-07] ingest | System live — first data flowing
attributed_to: [antigravity-agent]   belongs_to: [alphatecx]
- Schema applied to Neon: 6 data tables + ingestion_log + 2 materialized views ✅
- Supply chain seeded: 27 companies across 4 AI pillars ✅
- 5-day T86 test backfill: 32,296 rows, 0 errors ✅
- Materialized views producing real intelligence:
  - Server ODMs (鴻海/Foxconn): +210M shares foreign net, 3-day streak
  - GlobalWafers: +8.9M shares, 5-day consecutive buy streak
  - TSMC: -3.7M shares (selling → trickle-down pattern confirmed)
- Full 90-day backfill launched in background

## [2026-05-07] decision | MCP tools & Data Scope Insights
attributed_to: [antigravity-agent]   belongs_to: [system-architecture, mcp-server]
- Deployed 7 specialized FastMCP tools (`sc_sector_momentum`, `sc_compare_nodes`, `sc_accumulation_screen`, etc.) to `/mcp/<secret>` on Neon.
- Documented that only **5 core datasets** are pulled from TWSE to minimize noise (T86, Holdings, Margin, Revenue, OHLCV).
- **Insight documented**: Normalizing absolute flow volume against `shares_outstanding` reveals *relative accumulation intensity* (e.g. Foxconn and Wistron accumulating at similar 1.4-1.5% intensity despite size differences).
- Fixed a bug in `certifi` (Python 3.12 venv vs old 3.9) and a `raw_monthly_revenue` date parsing error during the background backfill.

## [2026-05-07] decision | V2 senior-engineer review + remediation pass
attributed_to: [antigravity-agent]   belongs_to: [system-architecture, mcp-server]
- Reviewed Gemini's V2 implementation; filed [decisions/2026-05-07-v2-review-fixes.md](decisions/2026-05-07-v2-review-fixes.md).
- SQL injection: centralized identifier allowlist (`_safe_col`) in `mcp_server/api/db_v2.py` covering `query_sector_momentum`, `query_ticker_momentum`, `query_compare_nodes`. Previously only `query_ticker_momentum` validated.
- Timezone: switched `_today_iso` (MCP) and `log_ingestion` (loader) to `Asia/Taipei` — UTC was mislabeling `_as_of` for ~8h/day.
- Idempotency: added `loader.atomic()` ctx manager; `backfill/run.py` now commits upsert + ingestion log together. Partial-batch crashes no longer leave a day marked 'ok'.
- View bug: `view_sector_momentum.top_ticker_5d` and `top_ticker_5d_name` now picked from a single `ROW_NUMBER()` window — could disagree before.
- MCP fail-fast: missing `MCP_BEARER_TOKEN` raises at startup instead of silently mounting nothing.
- MCP can now read `MCP_DATABASE_URL` (falls back to `DATABASE_URL`) for read-only role separation. Read-only role itself NOT yet provisioned on Neon — open follow-up.
- `sql/003_rls.sql`: removed hardcoded `'CHANGE_ME_IN_SUPABASE'` placeholder; password now read from `mcp_viewer.password` GUC. `CREATE POLICY IF NOT EXISTS` (PG15-only) replaced with `DROP IF EXISTS` + `CREATE`.
- `apply_schema.py`: dropped fragile `;`/`$$` splitter; added `--rls` opt-in flag.
- Telegram: `_fetch_top_sectors` now logs exceptions instead of swallowing them silently.
- `sc_data_status` row counts now use `pg_stat_user_tables.n_live_tup` instead of `COUNT(*)`.

## [2026-05-08] decision | mcp_viewer role provisioned + MCP cut over to read-only DSN
attributed_to: [antigravity-agent]   belongs_to: [system-architecture, mcp-server]
- Generated `MCP_VIEWER_PASSWORD` (stored in root `.env`); ran `python apply_schema.py --rls`.
- Verified on Neon: role `mcp_viewer` exists with LOGIN, 6 SELECT-only policies in `pg_policies`, RLS enabled on all 7 tables.
- Verified isolation: viewer DSN can `SELECT count(*)` from `raw_twse_t86` (231,977 rows) and `view_sector_momentum`; INSERT returns `permission denied for table raw_twse_t86`; SELECT on `ingestion_log` returns `InsufficientPrivilege` (no policy granted).
- `mcp_server/.env`: added `MCP_DATABASE_URL` (viewer DSN) — `db_v2.py` prefers this over `DATABASE_URL`.
- Restarted uvicorn (`api.index:app` :8787); end-to-end JSON-RPC test of `sc_sector_momentum` returned correct data — `_as_of=2026-05-08` (Taipei tz fix verified) and `top_ticker_5d/name` align (2317/鴻海, 2301/光寶科 — view fix verified).
- `view_sector_momentum` REFRESH'd successfully on first try; the long-hung Python process was stuck on the second view's REFRESH because of the Neon pooler dropping the connection. Re-issued `view_ticker_momentum` REFRESH with `CONCURRENTLY` against the direct (non-pooler) host so it doesn't compete with the live backfill.

## [2026-05-08] decision | Empty-day memoization (M4) — backfill no longer re-fetches holidays
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- `loader.get_ingested_dates` now returns `status IN ('ok','empty')` so retries skip both successful and confirmed-empty days.
- `backfill/run.py`: T86, holdings, margin paths now `log_ingestion(... status='empty')` when TWSE returns no rows.
- Retroactively scanned `backfill.log` and inserted 42 `empty` rows into `ingestion_log` for holidays already discovered (Apr 4 Tomb Sweeping, May 1 Labor Day, May 30 Dragon Boat, etc.) — split across `twse_holdings`/`twse_margin`.
- Saved budget per re-run: ~42 days × 3s rate-limit = ~126s wasted HTTP roundtrips eliminated.
- `executemany → COPY` (M2) deferred: 6-function refactor, current backfill running, not safe to land mid-run. Logged as open follow-up.
