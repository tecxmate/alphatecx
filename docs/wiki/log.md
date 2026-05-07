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

## [2026-05-08] decision | V2 MCP deployed to Vercel
attributed_to: [antigravity-agent]   belongs_to: [mcp-server, system-architecture]
- Created Vercel project `alphatecx-v2-mcp` under `nikolasdoans-projects`. Linked `mcp_server/` and pushed env vars to Production + Development:
  - `MCP_DATABASE_URL` → mcp_viewer DSN (read-only role)
  - `MCP_BEARER_TOKEN` → reused from local .env
  - `DATABASE_URL` deliberately NOT set on Vercel — would defeat the read-only boundary.
- Production: <https://alphatecx-v2-mcp.vercel.app>. Smoke-tested `/health`, 404 fallback, `sc_sector_momentum`, `sc_data_status` end-to-end.
- Bug surfaced + fixed: `sc_data_status` queries `ingestion_log`, but `003_rls.sql` originally blocked viewer access to it. Granted SELECT + RLS policy on `ingestion_log` to `mcp_viewer` in prod and updated `sql/003_rls.sql` to match. The original "internal only" intent was inconsistent with exposing a status tool publicly.
- Cold-start verified < 5s; subsequent calls hit warm pool. Free-tier Neon connection pool sized at max=3 in `db_v2.py` so multiple concurrent serverless invocations don't exhaust it.

## [2026-05-08] external | Located Neon project — Tecxmate org, project alphatecx
attributed_to: [niko]   belongs_to: [infrastructure-accounts]
- Used Neon MCP `list_projects` to identify the project: org `Tecxmate` (`org-muddy-hill-84308768`), project `alphatecx` (`restless-butterfly-45054019`), AWS `us-east-1`, Postgres 17, free tier.
- Console: <https://console.neon.tech/app/projects/restless-butterfly-45054019>. Login is the Google/GitHub identity tied to the "Tecxmate" org — separate from the Vercel `nikolasdoan` account.
- Captured all account ownership in [topics/infrastructure-accounts.md](topics/infrastructure-accounts.md) so this doesn't need re-discovery.

## [2026-05-08] decision | Migrated Neon DB to user-owned account
attributed_to: [niko]   belongs_to: [infrastructure-accounts, system-architecture]
- Old project (`alphatecx`, Tecxmate org) was inaccessible to Niko via web console — login was tied to a Tecxmate-affiliated identity he could no longer access. App code worked via stored DSN, but DB management (rotating creds, scaling, backups) was blocked.
- Niko created a new Neon project (`ep-cold-lab-aqklxtzs`, c-8.us-east-1.aws, PG 17.8) under an account he owns directly, with Neon Auth enabled.
- Migrated 1,495,632 data rows + 1,050 ingestion_log entries via `pg_dump --data-only | psql --single-transaction`. Row counts verified identical to source.
- New project quirk: Neon Auth set `search_path = ''`. Pooler rejects `options=-csearch_path` at connection startup. Application compensates via `psycopg_pool` `configure` hook (`loader.py`, `mcp_server/api/db_v2.py`) which runs `SET search_path TO public, neon_auth` per connection.
- Generated fresh `mcp_viewer` password; applied `sql/003_rls.sql` on new DB; verified read-only boundary (SELECT works, INSERT denied).
- Replaced env vars: root `.env` (`DATABASE_URL`, `MCP_VIEWER_PASSWORD`), `mcp_server/.env` (`MCP_DATABASE_URL`, `DATABASE_URL` fallback), Vercel Production + Development (`MCP_DATABASE_URL`).
- Redeployed `alphatecx-v2-mcp` on Vercel; smoke-tested `sc_data_status`, `sc_sector_momentum` end-to-end on production URL.
- Old DSNs preserved in `.env.old-tecxmate-20260508` (gitignored) for 24h safety net. Old project to be deleted after 2026-05-09.
- `.gitignore` updated to cover `.env.old-*` so the backup files can never be accidentally committed.

## [2026-05-08] decision | Renamed dim_supply_chain → dim_ticker; added filtered view
attributed_to: [niko]   belongs_to: [system-architecture]
- Old setup conflated two responsibilities: a 7,096-row ticker universe (auto-discovered from T86) and a 27-row curated supply-chain classification. Calling it `dim_supply_chain` made the second invisible — Niko opened the Tables view and saw mostly NULLs.
- Renamed the physical table to `dim_ticker`. Created `dim_supply_chain` as a view with `WITH (security_invoker = true)`, filtering `WHERE ai_pillar IS NOT NULL`. Indexes renamed `idx_dsc_*` → `idx_dt_*`. RLS policy renamed `mcp_viewer_read_supply_chain` → `mcp_viewer_read_ticker`; view inherits via security_invoker.
- Writers point at `dim_ticker`: `loader.upsert_supply_chain` (function name kept for back-compat), `seed_supply_chain.py`. Readers untouched: materialized views in `002_views.sql` JOIN `dim_ticker` (so they see all 7k tickers and COALESCE NULLs to 'unclassified'); MCP `query_supply_chain` reads `dim_supply_chain` (the 27-row view).
- `sc_data_status` table_names list: `dim_supply_chain` → `dim_ticker` so `pg_stat_user_tables.n_live_tup` returns the meaningful count.
- Live DB migrated atomically; materialized views recreated and refreshed; Vercel redeployed; verified `sc_supply_chain_map` returns 27 rows with TSMC/Foxconn/etc, no NULL leak.

## [2026-05-08] decision | Analysis system plan locked
attributed_to: [niko]   belongs_to: [system-architecture]
- Filed [decisions/2026-05-08-analysis-system-plan.md](decisions/2026-05-08-analysis-system-plan.md). Phased plan for extending v2 from a data pipeline into a decision system.
- Three layers: MCP/Neon (structured), daily digests in `docs/digests/YYYY-MM-DD/*.md` (15 Claude Scheduled Tasks/day budget), and Skills for on-demand dual-agent depth.
- Build order: sequential, validate each phase. Phase 0 = OHLCV backfill, Phase 1 = quant tools + backtest harness, Phase 2 = news pipeline, Phase 3 = first 5 scheduled tasks, Phase 4 = first 2 skills.
- Decided: backtest harness lands in Phase 1 (not deferred), even though ~90 days of T86 is thin. Discipline matters more than data depth right now.
- Dual-agent narrative-naive vs narrative-aware reasoning lives as a Claude Skill (manual, on-demand), not a scheduled task. Cron version is a cheap "disagreement scan" that flags candidates for the deep skill to analyze.

## [2026-05-08] ingest | Phase 0 done — OHLCV backfilled
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Wired OHLCV backfill into `src/backfill/run.py` with `--only ohlcv --ohlcv-months N`. Scope: classified supply-chain tickers + 0050 benchmark, skip-detection via direct query on `raw_twse_ohlcv`.
- 12-month backfill loaded **5,897 bars across 26 tickers**. 25/26 classified tickers fully covered (227 trading days each).
- Diagnosed and corrected 4 issues found during backfill: `2325` SPIL removed (delisted to ASE 2018); `6155` market label TPEX→TWSE; `6488` TWSE→TPEX; `3664` TWSE→TPEX. Fixes applied to seed_supply_chain.py and live DB. `3553` Jentech remains a TODO — returns empty on TWSE/TPEX OHLCV endpoints, absent from T86; likely on Emerging Stock Market (興櫃) or wrong ticker code.
- TSMC's 2025-06 and 2025-07 came up empty on first run (transient TWSE response); a re-run with skip-detection naturally re-attempted them and they filled in.

## [2026-05-08] decision | Phase 1 quant module shipped (indicators + backtest + MCP tools)
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- New SQL: `sql/004_quant.sql` — `signal_value` table (long-form, indexed by signal+date and ticker+date) and `view_latest_signals` materialized view (wide-form per-ticker snapshot). RLS policies in `003_rls.sql` guard signal_value for the mcp_viewer role.
- New Python: `src/quant/indicators.py` (Polars-based pure functions: RSI/MACD/BB/ATR/SMA/RS), `src/quant/compute_signals.py` (orchestrator that reads OHLCV, computes all indicators, upserts to signal_value, refreshes the matview), `src/quant/backtest.py` (single-threshold backtest harness — hit-rate, avg/median/best/worst return, sample-by-ticker breakdown, sample_warning if n<30).
- 42,595 signal-rows computed for 25 of 26 classified tickers (3553 Jentech skipped — no OHLCV data available).
- Three new MCP tools: `q_indicators(ticker_id)`, `q_screener(...)`, `q_backtest(signal, threshold, direction, forward_days, lookback_days)`. Deployed to Vercel; smoke-tested end-to-end on production URL.
- **First honest backtest result:** RSI < 30 oversold rule on this universe (84 obs) shows hit_rate=50%, avg_return=-1.1% — counter to textbook "mean reversion" intuition. RSI > 70 (901 obs) shows hit_rate=56.6%, avg=+1.9% — the AI-rally regime favors trend continuation over mean reversion. MACD histogram > 0 (3013 obs, hit_rate=56.7%, avg=+2.0%) is the strongest single-signal expectancy. The discipline tool is doing its job: it's already telling us not to trust an "obvious" signal.
- Phase 1 entry criteria for Phase 3 digests: any signal added to a daily digest must first produce a hit-rate report from `q_backtest` showing the rule's historical expectancy on this universe.

## [2026-05-08] decision | Phase 1.5 — flow signals + compound backtests
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Extended `src/quant/indicators.py` with `pct_below_52w_high`, rolling `zscore`, `rolling_sum`. Added `pct_below_52w_high` to the price-signal compute path.
- New `src/quant/compute_flow_signals.py` orchestrator reads T86 (instead of OHLCV) and writes flow z-scores: `foreign_net_z20`, `foreign_net_5d_sum`, `total_net_z20`. Same `signal_value` table; downstream consumers don't care about source.
- 1,116 flow signal-rows added (sparse — T86's 45-day depth allows ~25 days of usable rolling-z output per ticker after the 20-day burn-in).
- New MCP tool `q_backtest_compound(conditions, forward_days, lookback_days)` — multi-condition AND backtest via self-joins on signal_value, capped at 4 conditions. Strict allowlist on signal name + op (`<`/`>` only).
- Screener extended: `foreign_z_above`, `pct_below_52w_high_above` filters; matview adds the 4 new columns.
- **Compound discovery surfaced by the harness:** naive `RSI<30` had **negative** expectancy (avg -1.1%, 84 obs); `RSI<40 AND MACD_hist>0` (oversold-dip-within-uptrend) jumps to **69.2% hit rate over 39 observations**. Compound rule discovers something the simple rule misses — exactly why we built the harness.
- Universe sanity check: `pct_below_52w_high < -10` returns **zero observations**. Every classified ticker is within 10% of its 52-week high. Confirms the regime is uniformly bullish.
- 6 names show `foreign_net_z20 > 1.0`: 2317 Foxconn (z=2.93), 2301 Lite-On (z=2.74), 3231 Wistron (z=1.54), 4958 Zhen Ding (z=1.36), 2382 Quanta (z=1.30), 2308 Delta (z=1.19). 4/6 are server-ODM infrastructure pillar — clean read on where foreign capital is concentrated.

## [2026-05-08] decision | Phase 4 partial — decide-on-ticker Skill scaffold + output dirs
attributed_to: [antigravity-agent]   belongs_to: [system-architecture, mcp-server]
- Created `docs/digests/`, `docs/theses/`, `docs/journals/` directories with READMEs spelling out conventions, frontmatter, lifecycle states.
- Wrote `skills/decide-on-ticker/SKILL.md` — the dual-agent decision skill. 6 steps: read prior context, naive pass (data only, hard isolation rule), aware pass (data + news, deferred until Phase 2), reconcile, write thesis to `docs/theses/`, append to journal.
- Naive pass is fully operational today using existing MCP tools (`sc_supply_chain_map`, `q_indicators`, `sc_ticker_momentum`, `raw_flow_history`, `sc_sector_momentum`, `q_backtest_compound`). Aware pass is marked pending Phase 2 news; until then the reconcile step treats the naive view as the final view with a note.
- Hard rules baked in: never share context between naive and aware sub-tasks (the whole point is the isolation), never write a thesis without a backtest justifying the pattern, never hide a naive↔aware disagreement, never edit a closed thesis.
- Output convention: `docs/theses/YYYY-MM-DD-<ticker>-<slug>.md` with required frontmatter (status, catalyst, invalidation, naive_conviction, aware_conviction, disagreement). Journal append-only at `docs/journals/<ticker>-<slug>.md`.
- The skill is invoked manually in the Claude app with the project loaded — that's the shared memory across runs. Scheduled tasks produce digests; skills produce theses.
