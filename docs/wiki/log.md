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

## [2026-05-08] decision | First worked digest — 01-quant.md
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Generated `docs/digests/2026-05-08/01-quant.md` by querying live MCP tools (sc_sector_momentum, q_screener, q_indicators) on prod URL. End-to-end exercise of every q_* tool we shipped today.
- Reference example for what scheduled-task output should look like once the cron lands. Format follows `docs/digests/README.md`.
- **Substantive read from the data:** clear sector rotation — foreign capital out of foundry (TSMC -50M shares 20d), into server-build stack (Foxconn +542M 20d, +216M 5d). Six names show foreign_z>1.0; four of those are server-ODM infrastructure. One sharp divergence flagged: 3443 GUC has RSI 88 / MACD hist 143 (both extreme) but foreign_z = -1.82 — institutions distributing into retail-momentum euphoria. Universe-wide pct_below_52w_high mostly 0.0 (uniformly elevated regime).

## [2026-05-08] decision | Phase 2a shipped — RSS news harvester (no LLM yet)
attributed_to: [antigravity-agent]   belongs_to: [system-architecture, mcp-server]
- Researched + validated 12 news feeds via live HTTP fetches. Tier A (6 direct RSS): DIGITIMES Asia, Nikkei Asia, Bloomberg Tech, Bloomberg Markets, Federal Reserve press, ECB press. Tier B (6 Google News query feeds): per-pillar EN, per-pillar zh-TW (the Taiwan-domestic workaround for Focus Taiwan / Taipei Times having no native RSS), Taiwan Strait geopolitics, Fed rates, supply-chain controls. Catalogued in `src/news/sources.py`.
- New schema: `sql/005_news.sql` — `raw_news` table (PK on canonicalised URL; sentiment + ticker_mentions columns reserved as null until Phase 2b classifier lands). RLS additions in 003.
- Harvester: `src/news/harvest.py`. Two-stage dedup: canonical URL is PK; title-hash check catches Google News re-pointing to same article via different URLs. ON CONFLICT updates published_at when previously null (so feedparser fixes apply retroactively). Detects fresh insert vs update via RETURNING (xmax = 0).
- First full run: **735 new articles in 4 minutes, 0 source errors.** 800 unique titles across 12 sources. DigiTimes alone returned 65 directly-on-topic headlines (MediaTek freeze, Delta Malaysia expansion, WinWay April revenue).
- Found Nikkei Asia RSS contains no date field at all (only id/link/title) — accepted; MCP queries fall back to fetched_at when published_at is null.
- New MCP tools: `n_recent`, `n_for_ticker`, `n_source_status`. Deployed to Vercel.
- **Cross-validation moment**: quant digest this morning flagged Foxconn (2317) with foreign_net_z20 = 2.93. Independent text search of the news harvester (`n_for_ticker(2317, days=2)`) surfaces the headline "外資買超...鴻海" ("foreigners net buying Foxconn") from a Taiwan-domestic financial outlet. The structured signal and the public narrative agree on the same name on the same day. This is exactly the kind of convergence the dual-agent Skill is designed to surface — and it's working with text-fallback before the entity-extraction layer is even built.
- Phase 2a explicitly defers the LLM sentiment/entity-extraction step. User wants to see article quality for a few days before paying ~$2/day for Haiku classification. Next: cron the harvester (Vercel Cron or one of the 15 Claude Scheduled Tasks), watch coverage for a week, then decide on Phase 2b.

## [2026-05-08] decision | First worked disagreement scan — 06-disagreement.md
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Generated `docs/digests/2026-05-08/06-disagreement.md` by cross-referencing this morning's quant flags (01-quant.md) with the news harvester output (n_for_ticker queries on 8 names).
- Three patterns surfaced:
  1. **Convergence** (3 names: Foxconn 2317, Lite-On 2301, Delta 2308) — quant + narrative both point bullish. Lower asymmetric edge, the move is in the public discourse.
  2. **Silent strength** (4 names: Wistron 3231, Quanta 2382, Zhen Ding 4958, GlobalWafers 6488) — quant flags positive flow / momentum, news output has 0 mentions in 3 days. The flow scan is catching names beneath the headline cycle.
  3. **Sharp divergence** (1 name: GUC 3443) — RSI 87.8 + MACD hist 143 (extreme momentum) BUT foreign_net_z20 = −1.82 (institutional distribution) AND 0 news mentions. Classic distribution-into-strength: technicals euphoric, flow opposite, narrative absent.
- Confirms the system's central design thesis: data + narrative compared yields candidates the naive scan of either alone would miss. The "silent strength" category is the lean-and-bold setup the user asked for.
- This is the cron version of the dual-agent design (cheap, automated, no LLM call); the manual decide-on-ticker Skill will run on candidates surfaced here.

## [2026-05-08] decision | GitHub Actions cron live — debug saga + 2 lessons learned
attributed_to: [antigravity-agent]   belongs_to: [system-architecture, infrastructure-accounts]
- Both workflows live: `daily_harvest.yml` (16:30 Taipei weekdays) and `news_harvest.yml` (4× daily). Verified end-to-end: 218 articles ingested in the run after the fix landed.
- **Two GH-Actions-vs-Neon gotchas debugged the hard way:**
  1. **IPv6 path is dead on hosted runners.** Neon hostnames return both A and AAAA. Default Linux `getaddrinfo` prefers IPv6, but the runner's IPv6 egress hangs on send. `/etc/gai.conf` precedence tweak didn't take effect (psycopg-binary likely uses bundled resolver). Fix: edit `/etc/hosts` to pin the pooler hostname to its IPv4. libpq does normal hostname-based connect with proper SNI, no IPv6 attempted.
  2. **GSS encryption negotiation hangs.** Even after IPv4 was confirmed reachable (`nc -vz` <1ms), psycopg connect still timed out at 15s+. libpq tries Kerberos GSS encryption *before* TLS, and Neon's pooler doesn't reply in a way libpq expects, so it sits there. Fix: append `&gssencmode=disable` to the DSN env var in the workflow.
- Both fixes together unblock GH-Actions ↔ Neon connectivity. Local Mac and Vercel ignore both gracefully (gssencmode=disable is the libpq default-when-no-keytab-present anyway, and `/etc/hosts` only affects the runner image).
- Total commits in the debugging session: 9 (one revert of an unhelpful `_force_ipv4` helper). Final fix was a 1-line env-var append + a 7-line `/etc/hosts` step.
- **Phase 2a is now operationally complete.** News harvester runs unattended on cron; raw_news fills continuously; n_recent / n_for_ticker / n_source_status MCP tools serve fresh data.

## [2026-05-08] decision | Taiwan-aware cron schedule + brief generator
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User specified: crons more intensive around Taiwan trading hours, focus on key signals + findings during day, after-hours thesis status update. Acknowledged that the technical part is doable on cron; deeper analysis stays in Claude app.
- New schedule (UTC → Taipei):
  - 23:30 / 07:30 weekdays: pre-market brief (Telegram)
  - 02:00 / 10:00 weekdays: intraday alerts (silent unless threshold)
  - 04:00 / 12:00 weekdays: intraday alerts
  - 06:30 / 14:30 weekdays: intraday alerts (T86 publishing window)
  - 08:30 / 16:30 weekdays: existing daily pipeline + post-close brief
  - 13:00 / 21:00 daily: news harvest only
  - 22:00 / 06:00 daily: news harvest only
- Brief generator at `src/cron/brief.py` with three modes; intraday is the gated mode (foreign_z>2, RSI>80 or <20, BB%B outside [0,1], OR watchlist ticker named in last-1h news). Pre/post always send.
- Digests stored in new `daily_digest` table; user chose DB-only (vs commit-MD-back) to keep cron simple. Two new MCP tools `d_recent` / `d_for_date` serve them. Telegram tone "quiet" — morning + evening briefs, alerts only on threshold trip.
- Local end-to-end test produced 3 real Telegram messages (pre/intra/post) using actual data — confirming the news+signals→digest→Telegram pipeline. Intraday alert correctly named the morning's flagged tickers (Foxconn 2317, Lite-On 2301) plus 4 indicator extremes.
- Phase A of user's brief: cron-driven Telegram + DB digests. Phase B (manual deep analysis via Claude app + decide-on-ticker Skill) is the unchanged half.

## [2026-05-08] decision | First decide-on-ticker run — 3443 GUC, naive pass
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- First execution of `decide-on-ticker` Skill produced [theses/2026-05-08-3443-overbought-with-foreign-distribution.md](../theses/2026-05-08-3443-overbought-with-foreign-distribution.md) + journal opened at [journals/3443-guc.md](../journals/3443-guc.md).
- **Naive verdict: mildly long-biased, conviction 2/5.** The discipline tool pushed back on the morning quant digest's intuitive read.
- **Notable surprise**: the morning digest read GUC's RSI 87 + foreign_z = −1.82 + 0 news mentions as classic "distribution into strength" (bearish). The backtest harness contradicts: same combination (RSI > 75 AND foreign_z < −1) on this universe has historically been *continuation*, not reversal — n=8, hit rate 87.5%, avg fwd 5d return +12.4%. The 10d sample (n=3) shows +32.7% avg. Sample warnings honored: too thin to bet on, but enough to refuse the opposite assumption.
- **Real-time flow update**: by today's close, foreign_net_z20 had improved from −1.82 to −0.26, RSI cooled from 87 to 79, and total_net flipped *positive* (trust funds absorbing the foreign selling, +367K shares vs foreign −177K). Absorption thesis is being tested in real time.
- **Catalyst / invalidation defined**: foreign_z > 0 within 5d = continuation confirmed; close < SMA-50 (3034) = thesis off. Next review 2026-05-15.
- **Aware pass deferred** until Phase 2b news pipeline lands — important honest gap: cannot answer "why are foreigners selling?" from data alone.
- This first run validated the skill's discipline mechanism: the "obvious" read got challenged by the backtest, the thesis output reflects the tension explicitly, and the catalyst/invalidation are tied to specific data triggers (not narrative).

## [2026-05-08] decision | Output schema sharpening — borrowed from ZhuLinsen/daily_stock_analysis
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User shared https://github.com/ZhuLinsen/daily_stock_analysis. Most of it doesn't fit (mainland-Chinese universe, Chan/Elliott methodology, 11-strategies agent chat, paid news APIs), but their decision-dashboard schema is sharper than ours: `signal/score/sentiment_label/risks[]/catalysts[]/action_checklist[]`.
- Borrowed two things only: (1) the structured frontmatter fields for `decide-on-ticker` thesis output, (2) "Action checklist" sections in pre-market and post-close briefs.
- `skills/decide-on-ticker/SKILL.md` — added six new frontmatter fields. The first run on 3443 GUC predates this schema and stays as-is (calibration run).
- `src/cron/brief.py` — pre-market and post-close briefs now generate a 1-3 item action checklist from the day's data: open theses → "review trigger conditions", extreme foreign_z → "watch follow-through", top news → "cross-reference". Telegram messages now end with the checklist so the do-list is the last thing the user reads.
- Smoke test on today's data surfaced two new alerts: **6488 GlobalWafers** and **3324 Auras** both at `foreign_net_z20 = +4.25` (extreme accumulation), based on freshly-landed 2026-05-08 T86 data from the daily run that just completed.
- Decided NOT to borrow: their methodology (no rigorous backtest culture), data sources (wrong markets), LLM abstraction (we're committed to Anthropic), or web-app paradigm (we're MCP+Skills).

## [2026-05-08] decision | Watchlist layer added — 6488 + 3324
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- Created `docs/watchlist/` with `README.md` (conventions + lifecycle), `active.md` (the table, parsed by cron), and `archived/` (closed-out entries).
- Added today's two extreme-foreign-z names with reason context distinguishing the two setups:
  - **6488 GlobalWafers** — foreign_z=+4.25 (5d cum +9.24M shares) at 52w high, but total_z=−4.25 (foreigners buying while domestic institutions distribute). Escalation trigger: foreign_z stays > 1.5 for 2 more sessions OR domestic flow flips aligned.
  - **3324 Auras** — foreign_z=+4.25 today, 5d cum still −2.96M (sharp reversal), 12% off 52w high, all institutions aligned today (total_z=+4.25 too). Escalation trigger: another foreign net-buy day in next 3 sessions AND price reclaims SMA-50 (1041).
- Cron `src/cron/brief.py` extended:
  - New `_watchlist()` parser reads `docs/watchlist/active.md` (lightweight markdown-table parser, no yaml dep).
  - Action-checklist priority order now: (1) open theses → review triggers, (2) watchlist names with extreme flow today → escalation candidate, (3) plain extremes → "add to watchlist if it sustains", (4) top news cross-reference.
  - Briefs now have a `## Watchlist` section + show watchlist count in the Telegram header.
- Smoke test on today's data produced action checklist:
  1. Review thesis on 3443 GUC
  2. Escalation candidate: 6488 環球晶 (watchlist + foreign_z +4.25)
  3. Escalation candidate: 3324 雙鴻 (watchlist + foreign_z +4.25)
- Watchlist intentionally excludes thesised names (3443 sits in `docs/theses/` instead). Names should escalate to thesis or drop within ~5 trading days.

## [2026-05-08] decision | Telegram bot — watchlist + ticker queries
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture, mcp-server]
- New write surface: Vercel function `/bot/webhook` on the same project as the MCP, gated by Telegram's secret-token header AND owner chat-id check. Different DSN: `BOT_DATABASE_URL` (writer) vs MCP's `MCP_DATABASE_URL` (read-only). MCP boundary intact.
- Source-of-truth for watchlist moved from `docs/watchlist/active.md` to a new `watchlist` table (`sql/007_watchlist.sql`). Two existing rows (6488, 3324) seeded inline. The MD file kept as a stub pointing at the bot. Briefs + MCP read from DB now.
- Bot commands implemented:
  - `/watch <ticker> [reason]` — add (validates ticker against dim_supply_chain)
  - `/unwatch <ticker>` — archive (status=archived, kept for history)
  - `/watchlist` — show active rows
  - `/q <ticker>` — quant indicator snapshot (RSI/MACD/BB/foreign_z/RS)
  - `/n <ticker>` — last 7d news mentions
  - `/thesis <ticker>` — points at the file in `docs/theses/`
  - `/help` — command list
- New MCP tool `w_watchlist(status)` — Claude app can read same source via MCP.
- 4 new Vercel env vars: BOT_DATABASE_URL (writer + gssencmode=disable), TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_WEBHOOK_SECRET (32-byte URL-safe random, generated locally, not committed).
- Telegram webhook registered to https://alphatecx-v2-mcp.vercel.app/bot/webhook with secret_token header.
- Defense-in-depth: even if the URL leaks, requests without the secret-token header get 403; even if both leak, the chat-id check filters everyone except the owner; even if both bypassed, the bot is bounded to the watchlist + read tools (no thesis/MD edits, no DDL).

## [2026-05-08] decision | view_universe + MCP write tools (w_add/w_remove)
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User flagged conceptual overlap between dim_supply_chain (curated knowledge) and watchlist (dynamic state). Solution: keep tables separate (different concerns) but add a unified read view `view_universe` that joins them with the latest signal stack. One row per classified ticker, watched names sort first.
- New MCP tools: `u_universe(filter='all'|'watching'|'extreme')`, `w_add(ticker, reason, escalation_trigger)`, `w_remove(ticker)`. The two write tools mutate the watchlist table directly via the MCP role.
- **Security model adjustment**: mcp_viewer was originally SELECT-only across all tables. Extended narrowly to also have INSERT + UPDATE on the `watchlist` table only (no DELETE — archived-not-deleted pattern preserved). All other tables remain SELECT-only. Net security: same blast radius as the Telegram bot — both gates (URL-secret token / Telegram secret-token header) lead to the same write surface, so MCP write tools don't expand what an attacker could do if a token leaks. DELETE attempts still blocked at role level (verified end-to-end).
- Manual GRANT step required after apply_schema run — the DO-block GRANT didn't propagate (still SELECT-only after script). Re-running `GRANT INSERT, UPDATE ON watchlist TO mcp_viewer` directly fixed it. TODO: investigate why DO-block didn't apply (probably ordering or transaction quirk; not blocking).
- Smoke test on prod surfaced two new unwatched extremes worth considering: 2301 Lite-On (RSI 73, foreign_z 0.39) and 6155 Winway (RSI 60, foreign_z 2.37).
- 2026-05-10 [topic] supply-chain-audit-2026-05-10 — Audited Gemini's seeded 26: flagged 3 misclassifications (2399 BIOSTAR ≠ BMC; 6155 Junpao ≠ testing-probing; 6923 中台 ≠ green-energy DC). Proposed swap to 5274 ASPEED, ~25 expansion tickers (Wiwynn, Accton, BizLink, Lotes, Nanya, Aspeed, ITEQ/EMC/TUC CCL, Kinsus, MPI, Gudeng, Acter, etc.), `sc_edges` schema for explicit supply links, and ~150-ticker context backfill. Pending user sign-off.
- 2026-05-10 [topic] correlation-graph-3d — Built 3D correlation network: Mantegna distance + classical MDS pipeline (`src/quant/correlation_snapshot.py`), three.js viewer (`mcp_server/api/graph_view.py`) at `/g/{MCP_BEARER_TOKEN}/`, color=pillar, size=vol, yellow edges=`sc_edges`, blue edges=ρ≥0.7. ~280 LOC frontend, no build step. Smoke-tested locally; OHLCV backfill (~200 tickers × 12 months) running in background — full snapshot will regenerate once data lands.
- 2026-05-10 [topic] correlation-graph-3d (revised) — Replaced hand-rolled three.js viewer (~400 LOC JS) with plotly (~150 LOC Python in `build_plotly_html`). Drag-rotate, hover, modebar all free; custom drop-lines/compass dropped as not essential. graph_view.py is now 33 LOC reading a prebuilt HTML file. Net: same interactivity, no JS in the project.
- 2026-05-10 [topic] correlation-graph-3d (revised again) — Switched from plotly 3D to matplotlib 2×2 light-theme PNG: cluster (top-down), cluster vs 30d return, risk/return scatter, correlation heatmap. User preference: 3D was hard to read; 2D multi-panel reads instantly. New `/g/{TOKEN}/graph.png` route for direct image (Telegram).
- 2026-05-10 [topic] correlation-graph-3d (interactive added) — Added plotly 2D for the web viewer (zoom/pan/hover/linked axes between cluster panels). Matplotlib still renders graph.png for Telegram/reports. Two outputs from one snapshot: static PNG + interactive HTML. /g/{TOKEN}/graph.png unchanged; /g/{TOKEN}/ now serves the plotly version.
- 2026-05-10 [feature] lead-lag analysis — Computes pairwise log-return correlations at lags 0..7 days for the classified universe. Stored in `lead_lag` table; refreshed by daily cron. New MCP tool `q_lead_lag(upstream, downstream, min_corr, min_gain)` exposes forward-leading pairs. Initial signal already shows e.g. 6488 GlobalWafers → 3664 cleanroom at lag=1 (ρ=0.57), plausible silicon-supply→cleanroom-demand causality.
- 2026-05-10 [feature] thesis-status cron — `src/cron/thesis_status.py` reads docs/theses/*.md with status:active, formats a current-state report (price vs open, RSI, foreign_z, foreign_5d, catalyst/invalidation prose preview), sends Telegram, persists to daily_digest. Wired into daily_harvest after post_close. Doesn't try to evaluate prose triggers — surfaces the metrics those triggers care about so user can scan in 30s.
- 2026-05-10 [feature] daily-digest enrichment — post_close brief now reads correlation snapshot's discovery candidates and lead_lag's top forward-leading pairs, includes them in both the markdown digest and the Telegram short summary. Discovery already surfaces 2329 Orient Semi, 2369 Lingsen, 2451 Transcend as semiconductor candidates — real supply-chain peers we hadn't classified.
- 2026-05-10 [feature] /d/{TOKEN}/ data dashboard — Static HTML dashboard with 4 tabs: Watchlist / Theses / Discovery / Lead-lag. Plain HTML <table>s with vanilla-JS sort + filter (~50 LOC JS, no frameworks). Light theme matching graph viewer. Regenerated nightly by daily_harvest. Auth: same URL-as-secret as MCP/graph.
- 2026-05-10 [feature] valuation + sector indices — Two new TWSE endpoints harvested daily: BWIBBU_d (per-ticker P/E, P/B, dividend yield) → `raw_twse_valuation`; MI_INDEX type=IND (TAIEX + ~56 sector + cross-market indices) → `raw_twse_index`. Two new MCP tools: `q_valuation` (filters: pillar, max_pe, max_pb, min_yield) and `q_index_history`. Treasury stocks (TWT38U) and day-trade ratio (TWT54U) deferred — endpoints 404 under current TWSE URL scheme; need URL hunt.
- 2026-05-10 [feature] sql/012_gemini_additions — Adopted three good ideas from Gemini's drift edits to seed_supply_chain.py: + 2454 MediaTek (semiconductor / ic-design — major TW AI-chip designer, was missing), reclassify 8046 Nan Ya PCB to semiconductor/ic-substrate (ABF substrates are chip-level interconnect upstream of advanced packaging — Gemini's call is more accurate than 009's), + 2314 MTI (infrastructure / network-communication, marginal but completes coverage). Classified universe now 56. Marked seed_supply_chain.py as deprecated; SQL migrations are the source of truth.

- 2026-05-10 [chore] repo cleanup — Reclaimed 620 MB local disk (rm -rf .venv data __pycache__). Moved Investment Management/TW_Semi_Alpha_2026-05-10.md → docs/reports/2026-05-10-tw-semi-alpha.md (cleaner location). Removed empty Investment Management/ folder. Ingested supply_chain_analysis.txt (Gemini's volume-rank scan) → adopted three findings as sql/013: 1815 Fulltech (infrastructure / pcb-materials, NEW node — Low-Dk glass fiber upstream of CCL), 2313 Compeq (infrastructure / high-speed-pcb, HDI for AWS ASICs / Google TPU), 3706 MiTAC (infrastructure / server-odm, Intel DSG takeover + Oracle/OpenAI). Classified universe now 59. Then deleted supply_chain_analysis.txt (its content is now in SQL + this log entry).
- 2026-05-10 [feature] graph viewer — in-page ticker search + classify — Added a search/classify panel to the Plotly graph page (`build_plotly_2d_html` in `src/quant/correlation_snapshot.py`) plus a `POST /g/{TOKEN}/classify` endpoint (`mcp_server/api/graph_view.classify_ticker`, route in `mcp_server/api/index.py`). Autocomplete is powered by the full `dim_ticker` directory baked into the page at snapshot-build time; Save UPSERTs `(ai_pillar, node)` into `dim_ticker`. New classifications appear as coloured nodes only after the next `python -m src.quant.correlation_snapshot`. attributed_to: [niko, antigravity-agent] belongs_to: [correlation-graph-3d, taiwan-ai-supply-chain]
