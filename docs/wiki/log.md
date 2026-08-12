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
- 2026-05-11 [decision] graph PNG — drop matplotlib, render via Plotly+Kaleido — Replaced `build_matplotlib_panels` in `src/quant/correlation_snapshot.py` with `build_combined_png` that calls `_fig_combined(...).to_image(...)` so the static PNG (Telegram/reports) and the interactive HTML viewer share a single rendering codepath. Why: two codepaths for the same figure was dead weight; matplotlib only ever shipped PNGs nobody re-opened after Telegram. requirements: -matplotlib, +kaleido==0.2.1 (last self-contained Kaleido; bundles its own Chromium so CI doesn't need a separate Chrome install). attributed_to: [niko, antigravity-agent] belongs_to: [correlation-graph-3d]
- 2026-05-11 [feature] graph viewer — one-click "Rebuild graph" button — Added `↻ Rebuild graph` button next to the meta header in `build_plotly_2d_html` and a `POST /g/{TOKEN}/rebuild` endpoint backed by `graph_view.rebuild_graph()`. Server-side it calls `build_snapshot` + `build_plotly_2d_html` in-process (~15-25s) and returns the fresh HTML; the JS swaps the page via `document.write`. Best-effort writes `graph.html` + `graph_snapshot.json` to disk so local reloads survive; on Vercel's read-only fs the write is swallowed and only the in-session swap takes effect. PNG regen intentionally skipped (Kaleido boot is slow and the static PNG isn't on the viewer's critical path). Decision: Option A from the chat menu — A=in-process regen, B=GitHub Actions dispatch, C=hybrid; user picked A for tight feedback loop, accepting that the committed snapshot still needs a CI run for everyone-else updates. attributed_to: [niko, antigravity-agent] belongs_to: [correlation-graph-3d]
- 2026-05-11 [feature] graph viewer — rebuild window selector — Added a 60d/90d/120d/180d dropdown next to the ↻ Rebuild button; selected value is sent as `?window=N` to `POST /g/{TOKEN}/rebuild` and forwarded to `build_snapshot(window_days=...)`. Server clamps to [30, 365]. Why: Vercel hobby has a 60s function timeout; the default 120d rebuild is ~22s locally but Neon cold-start could push it over on hobby — 60d is the escape hatch. attributed_to: [niko, antigravity-agent] belongs_to: [correlation-graph-3d]
- 2026-05-11 [decision] graph viewer — drop rebuild button, regen on GET with 60s TTL cache — Reverted yesterday's `↻ Rebuild graph` button + `POST /g/{TOKEN}/rebuild` endpoint. `GET /g/{TOKEN}/` now calls `build_snapshot` + `build_plotly_2d_html` in-process on each visit, with a 60-second in-memory TTL cache so pan/zoom/tab swaps don't pay the recompute cost. `classify_ticker` invalidates the cache on save so a refresh after Save shows the new node immediately. Why: the Save+Rebuild two-step was a layered architecture for what's mentally one thing — "the graph is the DB rendered". Net deletion: ~70 LOC removed (rebuild_graph(), rebuild route, button, window selector, JS IIFE, post-save hint) vs ~25 LOC added (TTL cache + render helper). Caveats: (1) committed `graph.html` becomes a cold-start fallback only — CI nightly still regenerates it for static consumers / Telegram; (2) Vercel hobby's 60s function timeout still applies on first hit per cold instance; if it bites we'll add back a window override or move regen to a cron-warmed cache. attributed_to: [niko, antigravity-agent] belongs_to: [correlation-graph-3d]
## [2026-05-11] chat | Architecture review
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Reviewed repo structure, MCP/API modules, harvester orchestration, schema scripts, workflows, and dashboard generation.
- Recommended incremental modularization over a platform rewrite, with major rewrite deferred until scheduling, multi-user, or scale constraints appear.
- Updated [Architecture Review 2026-05-11](topics/architecture-review-2026-05-11.md).

## [2026-05-11] decision | codex/optimize branch started
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- Created branch `codex/optimize` for incremental architecture cleanup.
- Started with low-risk extraction: `mcp_server/api/security.py` for URL-secret auth checks and `mcp_server/api/query_safety.py` for SQL column allowlisting.
- Added `pyproject.toml` and a no-install `unittest` baseline covering auth path checks, query safety, and TWSE helper parsing.

## [2026-05-11] chat | Optimization pass
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Checked repo hot paths for low-risk optimization opportunities.
- Added HTTP session reuse in TWSE/TPEX fetches and cached repeated ticker-page build inputs.
- Updated [Architecture Review 2026-05-11](topics/architecture-review-2026-05-11.md).

## [2026-05-11] chat | Local check tooling
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Created local `.venv`, installed project dependencies plus `pytest` and `ruff`.
- `pytest -q` passes; focused Ruff checks on changed/new files pass.
- Full-repo `ruff check .` still fails on broad pre-existing lint debt, so full Ruff should be a separate cleanup.

## [2026-05-11] chat | Batched ticker page queries
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Optimized `src/dashboard/build_ticker_pages.py` so OHLCV, T86 flow, valuation, and latest signals load once per build for all target tickers.
- Kept news matching per ticker for now because matching depends on ticker/company text and needs a separate indexing design.
- Verified with focused Ruff and `pytest -q`.

## [2026-05-11] chat | Batched ticker page news
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Replaced per-ticker news SQL calls in `src/dashboard/build_ticker_pages.py` with one recent-news query and in-memory ticker/company title matching.
- Preserved the original 30-day window and 15-item per-ticker cap.
- Verified with focused Ruff, compileall, and `pytest -q`.

## [2026-05-11] chat | Removed Supabase CLI config
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User confirmed `supabase/` is not used.
- Deleted tracked `supabase/config.toml` and `supabase/.temp/cli-latest`; runtime code already uses Neon/Postgres directly.
- Updated [System Architecture](topics/system-architecture.md).

## [2026-05-11] chat | Local system smoke test
attributed_to: [antigravity-agent]   belongs_to: [system-architecture]
- Installed local server dependencies and ran FastAPI/MCP server on `127.0.0.1:8000`.
- Rebuilt dashboard artifacts from Neon; smoke-tested `/health`, dashboard, ticker page, graph, and invalid-token 404s.
- Noted local env quirk: Python entrypoints load `.env` correctly, but direct zsh `source .env` can fail if DB URLs contain unquoted `&`.

## [2026-05-11] chat | Web hub page
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User asked for one main page because dashboard, graph, and ticker pages were scattered.
- Added token-protected hub routes `/h/{token}/` and `/d/{token}/home`.
- Hub links dashboard, graph, graph PNG/JSON, health, MCP endpoint, and all generated ticker pages.

## [2026-05-11] chat | Bloomberg-lite frontend redesign
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User requested a systematic Bloomberg Terminal-lite frontend, not dark-only and mobile friendly.
- Added shared dense light/dark theme styling, theme persistence, hub/dashboard/ticker theme toggles, and mobile scrolling for dense tables/graphs.
- Graph page keeps Plotly panels readable on mobile through horizontal plot regions instead of compressing charts to phone width.

## [2026-05-11] chat | Graph discovery + tracked editor tabs
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User requested Discovery candidates as a top-level graph tab next to All/Cluster/Risk/Heatmap.
- Added a Tracked tickers tab with filterable inline pillar/node editing using the existing classify endpoint.
- Kept the tracked table client-rendered from the existing directory JSON so initial graph HTML stays performant.

## [2026-05-11] chat | Tracked tab lazy paging
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User requested lazy loading for the Tracked tickers tab: do not render all rows, show searched results only, 20 per page.
- Added search-only rendering with Prev/Next paging and preserved inline category/node editing.
- Moved the graph pan/zoom hint so it only appears on Plotly graph tabs, not table tabs.

## [2026-05-11] chat | Dedicated ticker directory
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User requested renaming tracked tickers to Tickers and giving them a Home-linked page.
- Added `/t/{token}/` as a dedicated ticker directory with default 20-row rendering, search, paging, inline pillar/node editing, and folder/list grouping stored in `dim_ticker.tags`.
- Removed the old Tracked tickers graph tab so graph navigation stays focused on charts and Discovery candidates.

## [2026-05-13] chat | ChatGPT MCP go-to-market constraint
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- User is evaluating selling the MCP tool and noted Claude Desktop/iOS has a simpler customer connection path than ChatGPT.
- ChatGPT requires a remote MCP/app deployment path with workspace/admin/developer-mode constraints, not a local desktop config flow.
- Product packaging should treat Claude as the lowest-friction initial channel and ChatGPT as an enterprise/API distribution path.

## [2026-05-17] decision | assistant-ui chat frontend in web/
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture, web-frontend]
- Scaffolded `web/` with `npx assistant-ui@latest create web --template mcp` on branch `feat/frontend`.
- Wired `/api/chat` to Anthropic (Sonnet, model overridable via `ANTHROPIC_MODEL`) and pointed the MCP client at the existing Python FastMCP via `MCP_SERVER_URL` (URL-as-secret, streamable HTTP — no Authorization header needed).
- Added generative UI for three MCP tools: `raw_flow_history` (Recharts), `sc_accumulation_screen` (TanStack Table), `sc_supply_chain_map` (grouped chips). Each renders `_source` / `_as_of` / `_freshness` provenance footer.
- Deferred from Gemini's spec: Clerk auth, Stripe metered billing, 20-prompt gatekeeper, PWA manifest, React Flow supply chain graph, chat persistence.
- Created [2026-05-17-assistant-ui-frontend](decisions/2026-05-17-assistant-ui-frontend.md) and topic [web-frontend](topics/web-frontend.md).

## [2026-05-17] decision | Add DeepSeek provider; env-driven model selection
attributed_to: [niko, antigravity-agent]   belongs_to: [web-frontend]
- User added a DeepSeek API key and asked for a DeepSeek "thinking" model.
- Refactored `web/app/api/chat/route.ts` to pick provider via `LLM_PROVIDER` (anthropic | deepseek) and `LLM_MODEL`.
- DeepSeek default is `deepseek-reasoner` (R1). Reasoner does NOT support tool/function calling — route strips MCP tools on reasoner turns to avoid request errors. For tool-using DeepSeek, use `deepseek-chat` (V3.2).
- Updated `.env.example` to document the trade-off and both API key slots.

## [2026-05-17] decision | Add Google Gemini provider
attributed_to: [niko, antigravity-agent]   belongs_to: [web-frontend]
- Added `@ai-sdk/google` as a third option in `web/app/api/chat/route.ts`. `LLM_PROVIDER=google` defaults to `gemini-2.5-flash`.
- All Gemini 2.5 models support tool calling, including the `-thinking` variant — unlike DeepSeek-R1. Free tier (Google AI Studio key, `GOOGLE_GENERATIVE_AI_API_KEY`) is rate-limited but usable for dev/POC.

## [2026-05-17] chat | Expanded chat frontend — starter prompts, 5 more tool UIs, clickable tickers, live watchlist
attributed_to: [niko, antigravity-agent]   belongs_to: [web-frontend]
- Added 6 TWSE-specific starter prompts on the empty thread state (chip flow 2330, accumulation screen, supply chain, q_indicators 6488, news 2454, regime).
- Added generative UI for 5 more MCP tools in `web/components/tools/`: `q_indicators` (KPI cards with RSI tinting), `sc_ticker_momentum` (streak chips + flow bars), `n_recent`/`n_for_ticker` (clickable news cards), `w_watchlist` (table), `q_regime` (label badge + vol/corr tiles with trend arrows).
- Cross-tool interactivity: `<TickerChip>` wraps any ticker_id in a `ThreadPrimitive.Suggestion` that sends a chip-flow follow-up prompt. Wired into screener-table, ticker-momentum, supply-chain-list, watchlist-table.
- Live watchlist sidebar: new `/api/watchlist` route calls `w_watchlist` server-side via the cached MCP client and returns `{watchlist, count}`. `<WatchlistPanel>` fetches on mount and renders ticker chips above the chat thread list. Verified 200 with real Neon data (3231/6488/3324).
- MCP server's watchlist row uses `company_name`, not `name` — defensive rendering in both panel and tool UI.

## [2026-05-17] decision | Enable multi-step assistant tool loops
attributed_to: [niko, antigravity-agent]   belongs_to: [web-frontend]
- User wanted the Assistant UI to support multiple reasoning and tool-calling rounds instead of stopping after one tool call.
- Added AI SDK `stopWhen: stepCountIs(5)` to `web/app/api/chat/route.ts`; this lifts the server-side default one-step limit while keeping a cost/runaway bound.
- Updated [2026-05-17-assistant-ui-frontend](decisions/2026-05-17-assistant-ui-frontend.md).

## [2026-05-17] decision | Tune assistant chat performance
attributed_to: [niko, antigravity-agent]   belongs_to: [web-frontend]
- User asked to improve chatbot performance through prompt and runtime changes.
- Changed the default tool loop cap to `MAX_TOOL_STEPS=3`, tightened the system prompt around narrow/sufficient tool use, and added `MCP_TOOL_CACHE_TTL_SECONDS=60` for common read-only MCP tool outputs.
- Updated [2026-05-17-assistant-ui-frontend](decisions/2026-05-17-assistant-ui-frontend.md).

## [2026-05-17] chat | Sidebar trigger placement and favicon
attributed_to: [niko, antigravity-agent]   belongs_to: [web-frontend]
- User requested the sidebar button at the top right of the side panel, with the top-bar button shown only while the side panel is collapsed.
- Added an editable SVG favicon using the sidebar brand mark.
- Updated [web-frontend](topics/web-frontend.md).

## [2026-05-27] decision | Disable scheduled harvest crons
attributed_to: [niko]   belongs_to: [system-architecture, infrastructure-accounts]
- User reported high Vercel CPU-hour usage from the running cron.
- Disabled scheduled triggers in `.github/workflows/daily_harvest.yml` and `.github/workflows/news_harvest.yml`; kept `workflow_dispatch` manual runs.
- Created [2026-05-27-disable-scheduled-harvest-crons](decisions/2026-05-27-disable-scheduled-harvest-crons.md) and updated [Infrastructure accounts](topics/infrastructure-accounts.md).

## [2026-06-03] decision | Re-enable scheduled harvest crons
attributed_to: [niko]   belongs_to: [system-architecture, infrastructure-accounts]
- APEX morning briefing for 2026-06-02 surfaced 8-day staleness (`latest_t86_date: 2026-05-25`), forcing TWSE-direct fallback and approximated D4 trailing averages.
- Source inspection confirmed the harvest runs on GitHub-hosted runners; Vercel coupling is only the post-step snapshot commit. User assessed the assumed CPU cost as not material and asked to restore the schedule.
- Restored `cron: '30 8 * * 1-5'` in `daily_harvest.yml` and all six Taiwan-market-aware crons in `news_harvest.yml`; `workflow_dispatch` retained.
- One-off `workflow_dispatch` of Daily TWSE Harvest still needed to backfill May 26 – Jun 2.
- Created [2026-06-03-reenable-scheduled-harvest-crons](decisions/2026-06-03-reenable-scheduled-harvest-crons.md); reverses [2026-05-27-disable-scheduled-harvest-crons](decisions/2026-05-27-disable-scheduled-harvest-crons.md).

## [2026-06-07] infra | Executed cron re-enable + backfill
attributed_to: [niko]   belongs_to: [system-architecture, infrastructure-accounts]
- Root cause of continued staleness: the 2026-06-03 re-enable edits were never committed/pushed — a stale `.git/index.lock` from a crashed Jun 3 `git commit` left the workflow changes and decision doc unstaged, so remote `main` GitHub Actions still ran the manual-only (disabled-schedule) workflows.
- Removed the stale lock, committed and pushed the re-enable (`29dc17d`); remote `main` now carries the weekday post-close schedule (daily) and the six Taiwan-market-aware slots (news).
- Ran the May 26 – Jun 2 backfill via `workflow_dispatch` of Daily TWSE Harvest (run 27089576787, success in 5m11s); snapshot commit-back pushed as `8a68da8`. Ingestion to Neon is live again.

## [2026-06-11] decision | Neon storage retention prune
attributed_to: [niko, codex-agent]   belongs_to: [system-architecture, infrastructure-accounts]
- Neon production reached the free-tier storage cap at 490 MB; largest tables were all-market `raw_twse_t86`, `raw_twse_holdings`, and `raw_twse_margin`.
- Pruned old bulk rows, kept bounded recent windows, and compacted affected tables with `VACUUM FULL`; database size dropped to 158 MB.
- Created [2026-06-11-neon-retention-prune](decisions/2026-06-11-neon-retention-prune.md); updated [Infrastructure accounts](topics/infrastructure-accounts.md) and [Historical Data Backfill](topics/historical-backfill.md).

## [2026-06-11] ingest | Neon usage banner interpretation
attributed_to: [codex-agent]   belongs_to: [infrastructure-accounts]
- Neon docs show console usage is split across root storage, child-branch storage, instant-restore/history storage, compute, and network transfer.
- If the top banner remains after DB compaction, inspect **Review usage** / org **Billing** before assuming the active branch's current table size is still over limit.
- Updated [Infrastructure accounts](topics/infrastructure-accounts.md).

## [2026-06-17] decision | Disable scheduled Telegram briefs
attributed_to: [niko]   belongs_to: [system-architecture, infrastructure-accounts]
- User surfaced a `claude-finbot` intraday Telegram alert and asked to turn off the automation.
- Traced the alert to scheduled `news_harvest.yml` brief mode mapping; scheduled runs now force `MODE='none'` while news harvesting and manual brief dispatch remain available.
- Created [2026-06-17-disable-scheduled-telegram-briefs](decisions/2026-06-17-disable-scheduled-telegram-briefs.md) and updated [Infrastructure accounts](topics/infrastructure-accounts.md).

## [2026-07-05] decision | Add full-market flow screener
attributed_to: [niko, codex-agent]   belongs_to: [system-architecture]
- User identified that AI-universe-only screening missed traditional-sector sleeper candidates.
- Added `market_flow_screener` over all TWSE/TPEX T86 flow rows and expanded `q_screener` below-threshold filters / `all_with_signals` mode, while noting all-market technical signals still depend on OHLCV coverage.
- Updated [System Architecture](topics/system-architecture.md).

## [2026-07-11] ingest | Weekly watch — 拓凱 / 晟田
attributed_to: [claude-cowork]   belongs_to: [topkey-4536]
- 拓凱 4536: 171.5 (Fri close, -2.0%) — BUYABLE BASE, sitting at top of 166–170 zone, holding >160 invalidation.
- 晟田 4541: 61.0 (Fri close, -8.5%) — EXTENDED, ~18% above 50–52 base; wait for pullback, don't chase.
- Flow: 4536 foreign net sellers last 2 sessions (7/8 -19k, 7/9 -95k張-equiv) after heavy mid-June accumulation — cooling. 4541 foreign flow whipsawing (7/7 +1.36M, 7/8 -1.34M, 7/9 +709k shares) — volatile, size small.
- Note: created data/watchlist.csv (did not previously exist in this repo layout); refreshed prices for 0050 105.8, 00662 120.9, 2330 2415.0.

## [2026-07-17] decision+ingest | scan_limit_board — EOD-only limit board scanner
attributed_to: [niko, antigravity-agent]   belongs_to: [limit-board-scanner, system-architecture]
- Built `scan_limit_board` from Niko's spec (`~/Downloads/scan_limit_board_spec.md`). Niko scoped it EOD-only: realtime MIS sweep (~3–4 min, ~40–60 batches) doesn't fit the stateless Vercel function, and `lock_time` needs cross-poll state. See [decision](decisions/2026-07-17-limit-board-scanner-eod-only.md).
- Board is fetched live from TWSE MI_INDEX (ALLBUT0999) + TPEX dailyQuotes — Neon can't serve it (`raw_twse_ohlcv` covers ~58 classified tickers, not the ~1,950-name market). First MCP tool here making outbound exchange calls.
- Validated before merge: `reference_price = close - change` matched TPEX's own 次日參考價 848/848; the §3 tick table matched the exchange's own limit prices 885/889.
- Three spec deviations, all forced by real data: EOD `is_locked` **is** knowable (both feeds publish the closing bid/ask); a null P/E must not imply `no_earnings` (BWIBBU has zero TPEX coverage, so §6 read literally labels the whole 上櫃 board `chase`); and `foreign_net_z20` must come from `raw_twse_t86` (12,791 tickers) not `signal_value` (58) — otherwise `accumulating` never fires and `triage="sleeper"` is unreachable. Details in [topic](topics/limit-board-scanner.md).
- Trap worth remembering: TWSE prints `'--'` for an exhausted book side, TPEX prints `'0.00'`. Parsed literally, every TPEX lock is silently missed (14 of 36 on 2026-07-16). Caught only by running the tool against a live session, not by unit tests.
- Post-review hardening (code-reviewer: 0 critical / 0 high / 2 medium, both real): TWSE's non-OK `stat` was folded into "holiday", so a TWSE outage + healthy TPEX would have returned half the market as a clean scan with an empty `errors[]`. Now only `沒有符合條件的資料` counts as a non-trading day; everything else is reported. Added a per-market coverage guard + `universe_by_market` because TPEX can never signal failure (`stat` is always `'ok'`).
- Also found while fixing: a malformed `date` makes TPEX return **today's** board instead of erroring — `date` is now strictly validated, or a typo answers about the wrong session under the requested label.
- Fetch budget cut 45s×3 → 10s×2 (endpoints measure 1–2.5s), ~42s worst case for both markets. This is the only tool here making outbound calls, so the only one with a real time budget.

## [2026-07-18] fix | Revert MCP-wide maxDuration override
attributed_to: [niko, antigravity-agent]   belongs_to: [limit-board-scanner, system-architecture]
- The 2026-07-17 scanner commit set `maxDuration: 60` on `api/index.py`. Niko flagged that this is per-*function*, not per-tool: all 35 MCP tools share the single `api/index.py` function, so the override capped every Neon-only tool at 60s too.
- Checked the platform default: under Fluid Compute (enabled by default, all plans) it is **300s**, ~7× `scan_limit_board`'s ~42s worst case — already sufficient. The override only *lowered* the ceiling for the other 34 tools; it fixed nothing.
- Reverted `mcp_server/vercel.json` to its pre-scanner state (no `functions` block). `scan_limit_board` still fits comfortably.

## [2026-07-21] decision | flow_leaders_scan (M2a) — the generative sleeper board
attributed_to: [niko, antigravity-agent]   belongs_to: [flow-leaders-scan, system-architecture]
- Niko handed over `CLAUDE_CODE_HANDOFF.md` + `scan_limit_board_spec_2.md`, asked to build all missing roadmap tools (M1 adopt / M2a flow / M3 session+quote), leaving the shipped `scan_limit_board` as-is. Broker for M4 positions is **not 永豐** → M4 skipped; realtime `quote` scoped to on-demand watchlist (persistent MIS poller doesn't fit Vercel serverless).
- Built `flow_leaders_scan`: `flow_leaders.py` (pure scorer) + `db_v2.query_flow_leaders`/`latest_flow_date` + `index.py` tool + 15 tests. Both non-negotiable acceptance tests pass live: 拓凱 4536 rank 9/1219 `sleeper` @ 2026-06-30; 日馳 1526 `chase` @ 2026-07-17.
- Key findings: price/flatness must come from `raw_twse_valuation.close` (ohlcv has 0 rows for both acceptance names); flatness must be **median-anchored** to survive a corrupt print (4536's 87.3 on 2026-05-13) — this took 拓凱 from rank 379→9; the spec's `min_foreign_z=1.0` default would exclude 拓凱 (multi-week grind, last-day z≈−0.4) so z is demoted to an optional off-by-default filter; `view_ticker_momentum.consecutive_foreign_buy_days` is as-of-now and useless for historical scans. Full rationale: [flow-leaders-scan decision](decisions/2026-07-21-flow-leaders-scan.md).

## [2026-07-21] decision | session_state (M3a) + market calendar
attributed_to: [antigravity-agent, niko]   belongs_to: [session-state, system-architecture]
- Built `session_state()` — Taipei market phase (pure, time-only) + trading-calendar. Kills the 試撮 error class: 08:30–09:00 pre_open_auction stamps `price_is_indicative=true` + a 試撮 warning so a simulated auction price is never read as a real quote. Regular 09:00–13:30.
- Calendar: new `market_holidays` table (`sql/015_market_calendar.sql`), harvested from the TWSE published holiday schedule (`fetch_twse_holidays`, ROC query year) and wired into `daily.py` step 5c (current+next year). Classifier: a schedule row is a **closure** unless its name contains `開始交易`/`最後交易` (those are open reference days the schedule also lists; `市場無交易` settlement-only days correctly stay closures). Manual typhoon closures = `source='manual'` inserts, which a TWSE re-harvest won't clobber (`upsert_market_holidays` guard).
- Gotcha fixed: the new table needed `GRANT SELECT` + RLS policy for the `mcp_viewer` read-only role (local `DATABASE_URL` is `neondb_owner` so tests passed, but the serverless MCP reads as `mcp_viewer` and got `permission denied`). Grant added to `015` (guarded) and applied live. Any future MCP-read table must repeat this.
- Verified live: CNY 2026-02-16 → closed (農曆除夕及春節); 2026-02-23 → open (resume day); weekends closed. Note the handoff's typhoon example 2026-07-10 **actually traded** in this DB (4742 t86 rows) — no manual closure inserted (would contradict the data).

## [2026-07-21] decision | quote (M3b) + dividend_calendar (M1 adopt)
attributed_to: [antigravity-agent, niko]   belongs_to: [realtime-quote, dividend-calendar, system-architecture]
- **quote (M3b)** — on-demand watchlist realtime via TWSE MIS (`mis.twse.com.tw`), ≤100 symbols/call, primes the `index.jsp` cookie, batches ≤50. Surfaces the authoritative pre-tick-rounded limit prices (`u`/`w`). Serverless-safe watchlist only; the market-wide persistent poller does NOT fit Vercel (same constraint as scan_limit_board). `z='-'` (no print) → `last_price: null`, never a fabricated price; pre-open (08:30–09:00) stamps `price_is_indicative` via session_state. `quote.py` + `db_v2.ticker_markets` (tse_/otc_ prefix) + tool. Broker for M4 positions is not 永豐 → M4 stays skipped.
- **dividend_calendar (M1)** — answers "does a buyer today still get the dividend?". Source discovery: `opendata/t187ap45_L` (股利分派情形) has the amount but **not the ex-date**; the ex trading date lives in **TWT49U** (除權除息計算結果表, actual) + **TWT48U** (預告表, upcoming). Built `raw_twse_dividend` (`sql/016`), `fetch_twse_ex_dividend`/`fetch_twse_ex_forecast` (ROC-Chinese date parser `_roc_cn_to_iso`), `upsert_dividends` (actual never overwritten by a later forecast), `db_v2.query_dividend`, tool, wired into `daily.py` step 5d (monthly chunks — TWT49U times out on wide ranges in peak season). Acceptance PASS: 華碩 2357 @ 2026-07-10 → ex 2026-07-01, cash 42.0, `already_ex=true`.
- Remaining M1 FinMind items NOT built (need a FinMind token + a separate integration): financial-statements deep-dive, TPEX-inclusive valuation (TaiwanStockPER for the 上櫃 gap), FinMind chips. Documented as follow-up; TWSE-native pieces (dividends, quote, session, flow) delivered without FinMind per "adopt before build".

## [2026-07-21] decision | route tw-equity-alpha skill to the new tools + version-control it
attributed_to: [niko, antigravity-agent]   belongs_to: [flow-leaders-scan, system-architecture]
- Updated the live Claude Desktop `tw-equity-alpha` skill so its four modes lead with the new automated tools: Mode 1 discovery → `flow_leaders_scan` (it IS the Sleeper Score automated), Mode 4 board triage → `scan_limit_board`, Mode 3 entry-timing → `quote`+`session_state`, and `dividend_calendar` gates any yield/ex-div claim. Staleness guardrail now points to `quote`/`session_state` instead of "use a screenshot".
- The skill lived only in Claude Desktop app-support (single uncommitted copy). Mirrored it into the repo at `skills/tw-equity-alpha/` for version control; the app copy stays the live one (Desktop reads that path), repo copy is source-of-truth — keep in sync manually. Note added to `skills/README.md`.
- MCP tool discovery is dynamic (`tools/list`): after the Vercel redeploy of the pushed commits, a Claude Desktop reconnect/restart surfaces the four tools automatically; skill files are re-read per invocation so no restart needed for the skill edits.

## [2026-07-21] decision | add Fugle as the preferred realtime quote source
attributed_to: [niko, antigravity-agent]   belongs_to: [realtime-quote, system-architecture]
- Niko supplied a Fugle Market Data API key. Added Fugle as the preferred `quote` source (the handoff's "upgrade" tier over MIS): `fugle.py` REST client (`X-API-KEY`, `intraday/quote/{symbol}`) + pure `parse_quote`, wired into the existing `quote` tool via a `source` param (`auto`|`fugle`|`mis`). Auto uses Fugle when `FUGLE_API_KEY` is set, else MIS, and falls back to MIS if Fugle returns nothing; `_quote_source` reports which answered. 7 new tests; suite 91 passing. Verified live (2330/4536/6488 with 5-level book).
- Fugle returns `referencePrice` but not the band, so limit-up/down are computed via `limit_board.limit_up/down` (same validated tick table) rather than left blank — Fugle quotes still carry authoritative limit prices.
- Still watchlist-only (Fugle quote is single-symbol → one call each, capped 40; WebSocket streaming doesn't fit the stateless serverless function). Key stored in gitignored `.env`; **must be added to Vercel env for production** or `quote` silently uses MIS there. Key was pasted in chat — rotate if that channel isn't trusted.

## [2026-07-21] external | Vercel deploy topology + Hobby-plan blocks org-repo auto-deploy
attributed_to: [antigravity-agent, niko]   belongs_to: [system-architecture, infrastructure-accounts]
- Diagnosed while wiring Fugle into production. **Two Vercel projects existed:** `alphatecx-v2-mcp` (the real live MCP, Root Directory = `mcp_server/`, serves `alphatecx-v2-mcp.vercel.app`) and a `alphatecx-2` duplicate (Root Directory = repo root) that Vercel git-auto-imported — every build failed (new Python builder can't pick one entrypoint among `api/index.py` + `api/bot.py`). Deleted the duplicate; its mis-placed `FUGLE_API_KEY` went with it.
- `FUGLE_API_KEY` must live on **`alphatecx-v2-mcp`** (added, production). Env-var changes need a fresh deploy to take effect.
- **Auto-deploy is broken because the repo was transferred to the `tecxmate` GitHub org.** Vercel Hobby does not support git-connecting a **private org-owned** repo (409: "Upgrade to Pro"). The transfer dropped Vercel's GitHub webhook and it can't be recreated on Hobby. So pushes no longer auto-deploy. Options: upgrade the Vercel account to Pro, make the repo public, move the project to a Pro team, or deploy manually.
- **Manual production deploy** (works today, no git needed): from the **repo root** (Root Directory = mcp_server handles the subdir) run `vercel --prod`. Do NOT run it from `mcp_server/` (rootDirectory nests → looks for `mcp_server/mcp_server`). `.vercelignore` files (root + mcp_server) keep `.env`/logs out of the bundle.
- Production verified healthy after the manual deploy (root 200, unknown path 404 = app booted).

## [2026-07-21] external | Repo moved back to personal — auto-deploy restored
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture, infrastructure-accounts]
- Resolution to the Hobby/org-repo block: Niko transferred the GitHub repo from the `tecxmate` org back to his personal account. It is now **`nikolasdoan/alphatecx`** (private, personal). Reconnected the Vercel git integration (`vercel git connect` now succeeds — no 409) and **verified push-to-deploy end to end**: a commit touching `mcp_server/` triggered a production build that went Ready in ~34s. Local `origin` repointed to the new URL. Only commits touching the `mcp_server/` build root auto-deploy; docs/sql/src-only commits don't.

## [2026-07-26] decision | Flow-leaders dividend enrichment — Tool Review v2 Phase 1 (TWSE-native)
attributed_to: [niko]   belongs_to: [flow-leaders-scan]
- Tool Review v2 flagged the `flow_leaders_scan` labelling layer (not the engine): #1 blended
  殖利率 overstated income (台中銀 5.18 vs ~1.9 cash), #3 no ex-div proximity, #6 no stale guard,
  #7 project-completion revenue noise. Review assumed FinMind was wired — it isn't.
- [niko] chose "TWSE-native now, FinMind next". Shipped: forward-cash `yield` flag
  (`cash_yield_fwd`), `ex_div_imminent`/`recently_ex` + `days_to/since_ex`, `stale_price_warning`,
  `|yoy|>=200` rev-guard. `score_row` gains a pure `as_of`; +2 LATERAL joins on `raw_twse_dividend`.
- Live-verified @2026-07-24: 2812 → cash_yield_fwd 1.91, no yield flag, ex_div_imminent; 2707 → no
  yield flag; 2357 → recently_ex @7/10. Tests 15→24, suite 100 green.
- Deferred (needs FinMind token): dividend_trap/填息 prob, governance news, adj-price flatness →
  docs/wiki/topics/finmind-phase2-plan.md.
- Pages: decisions/2026-07-26-flow-leaders-dividend-enrichment.md, topics/finmind-phase2-plan.md,
  updated topics/flow-leaders-scan.md.

## [2026-07-27] external | FinMind free tier confirmed — unblocks Phase 2 #1/#2/#4
attributed_to: [niko]   belongs_to: [finmind-phase2-plan]
- Verified FinMind tiers (finmind.github.io): anon 300/hr, free registered 600/hr, paid sponsor
  (2 tiers) higher + some paid-only datasets. A **free** token covers #1 (TaiwanStockDividend),
  #2 (TaiwanStockDividendResult/填息), #4 (TaiwanStockNews). Only #5 (TaiwanStockPriceAdj,
  taiwan_stock_daily_adj) is paid-only. Nightly ETL fits 600/hr; hits-only enrichment trivial.
- Updated topics/finmind-phase2-plan.md (tiers + free/paid split; resolved the adj-price question).

## [2026-07-27] decision | FinMind Phase 2 built — cash/stock split, honest dividend_trap, governance news
attributed_to: [niko]   belongs_to: [flow-leaders-scan]
- [niko] supplied a free-tier FinMind token (600/hr; TaiwanStockDividend/DividendResult/News OK,
  PriceAdj paid-blocked) and chose v2 #1+#2+#4. Wired a nightly FinMind ETL → Neon (sql/017: 4
  tables) joined into flow_leaders_scan. Read path never calls FinMind.
- KEY INTEGRITY FINDING: TaiwanStockDividendResult.max_price is the ex-DAY limit band, not a post-ex
  recovery high — a naive 填息 metric reads ~1.0 for everything (1.0 for 晶華, which the review said
  never fills). Real 5y 填息 needs paid adj-price. So did NOT fabricate fill_probability; reframed
  dividend_trap to honest ex-date logic: went ex within ~250d AND no upcoming → strip yield,
  sleeper→watch. FinMind's full ex-history catches 晶華's April ex that TWT49U lacked.
- Live-verified @2026-07-24: 晶華 2707 → dividend_trap → watch; 台中銀 2812 → no trap (upcoming 8/4),
  cash 0.39/stock 0.67; governance keyword flags real 違約交割 news (3037). Tests +18 → suite 117.
- FINMIND_TOKEN in .env + GH Actions secret (harvester runs in CI, not Vercel). daily.py step 5e.
- New: src/harvester/finmind.py, scripts/backfill_finmind.py, sql/017_finmind.sql,
  decisions/2026-07-27-finmind-phase2-build.md; updated finmind-phase2-plan + flow-leaders-scan.
- Still blocked (paid): true 5y 填息 + dividend-adjusted flatness (v2 #5) via TaiwanStockPriceAdj.

## [2026-07-31] ingest | CLAUDE.md rewritten as a real onboarding file
attributed_to: [niko]   belongs_to: [system-architecture]
- `/init` run. `CLAUDE.md` was an 11-byte `@AGENTS.md` import; rewrote it to carry commands +
  architecture while keeping the `@AGENTS.md` line so the wiki contract survives.
- Documented the facts that cost multiple files to derive: the Vercel Root Directory =
  `mcp_server/` deployment split (why `riskguard/` vs `mcp_server/api/rg/`, why `src/quant`
  is mirrored into `mcp_server/api/quant`), the two requirements files, the
  `pythonpath = [".", "mcp_server/api"]` bare-import convention, `apply_schema.py`'s
  hardcoded file list, and the two GH-Actions Neon quirks (`gssencmode=disable`, /etc/hosts
  IPv4 pin) that hang rather than error when dropped.
- Verified before writing: `pytest -q` → 112 passed / 5 skipped; the five `quant` mirror pairs
  differ by exactly one line (server adds an `MCP_DATABASE_URL` fallback).
- Noted root `README.md` is still the untouched `tecxproj` template — flagged as not project docs.
- Local-server line verified empirically, and it surfaced a live risk: `mcp_server/requirements.txt`
  pins `mcp>=1.2.0`, but mcp 2.0.0 dropped `mcp.server.fastmcp` — a fresh unpinned install cannot
  import `index.py`. `mcp<2` boots and `/health` returns 200. Worth pinning in the requirements file.
- Also confirmed `index.py` hard-refuses to start without `MCP_BEARER_TOKEN`, and that the working
  invocation is `cd mcp_server && uvicorn api.index:app` (uvicorn is in neither requirements file).

## [2026-07-31] decision | Postgres migrated from Neon to Zeabur
attributed_to: [niko]   belongs_to: [system-architecture]
- Niko deployed a Zeabur Postgres (18.4, `8.209.197.81:32046`) and asked to migrate off Neon (17.10).
  Audit found zero Neon lock-in: only `plpgsql` installed, `neon_auth` an empty scaffold, every caller
  reads `DATABASE_URL` from env. See [2026-07-31-migrate-neon-to-zeabur](decisions/2026-07-31-migrate-neon-to-zeabur.md).
- Dump/restore run inside a `postgres:18` container — local client is 14.19 and refuses a 17/18 server.
  26 of 27 relations match source `count(*)` exactly; indexes 56=56, policies 24=24, FK/PK/unique identical.
- Non-obvious: RLS roles are cluster-level and never travel in a dump. 24 policies bind to `mcp_viewer`,
  so the role had to be created on the target *before* `pg_restore` or every policy would have errored.
- Zeabur has TLS **disabled** (`sslmode=require` rejected outright), so the new URL must drop it and
  traffic is cleartext over a public IP. Flagged to Niko; unresolved.
- Cutover deliberately not performed — `.env`, the GH Actions secret, and the Vercel MCP deployment
  still point at Neon, which stays live as rollback.

## [2026-07-31] ingest | view_ticker_momentum can't refresh
attributed_to: [claude-agent]   belongs_to: [system-architecture]
- The migration's `REFRESH MATERIALIZED VIEW` failed on a real pre-existing bug, not a migration artifact:
  ETF 009805 renamed 新光美國電力基建 → 台新美國電力基建 on 2026-07-13, and the matview groups by
  `company_name` (from per-date `raw_twse_t86`) while `idx_vtm_ticker` is unique on `ticker_id` alone.
- Refreshing on Neon fails today too; Neon only looks healthy because it holds pre-rename stale rows.
  `continue-on-error: true` in `daily_harvest.yml` has been hiding it nightly.
- Fix direction (unapplied) in [view-ticker-momentum-refresh-break](topics/view-ticker-momentum-refresh-break.md).

## [2026-07-31] decision | Risk Guard Phase 1 implemented from RISK_GUARD_PRD.md v1.1
attributed_to: [niko, claude-agent]   belongs_to: [risk-guard, alphatecx]
- [niko] handed over `RISK_GUARD_PRD.md` v1.1 and asked for it to be implemented. Delivered
  **Phase 1 exactly as PRD §7 scopes it**: schema + M1 + M2 + M2b + Telegram bot + five `rg_*`
  MCP tools + held_pct snapshot. Phases 2–4 (M3 族群, M4 盤中, M5 intent, M6 公告, M7 節律) not built.
- **Checked before designing:** a TAIEX-only M1 provably fails the 7/07 acceptance row (−2.31%,
  below MA20 → score 2 = green, but §7 demands ≥yellow). Verified all three missing feeds are
  reachable first: TWSE `MI_INDEX?type=MS` 漲跌證券數合計 (7/07 = 128↑/892↓ on the 股票 column),
  TAIFEX `futContractsDateDown` Big5 CSV (7/30 外資 net OI = −81,017), and market margin as
  `SUM(margin_balance)` over existing `raw_twse_margin` — no new feed needed for the third.
- The light is a **state machine, not `f(score)`** — PRD v1.1 hysteresis. 7/30 and 7/31 are replay
  rows that exist to catch a stateless implementation; both are pinned in tests.
- **Deviation, deliberate:** code splits across `riskguard/` (cron, impure) and
  `mcp_server/api/rg/` (pure + read layer) rather than the single `/riskguard` folder PRD §2
  names — Vercel's Root Directory is `mcp_server/`, so a repo-root package cannot be imported
  by an MCP tool. `api/quant/` is the precedent.
- **Deviation, deliberate:** cron on GitHub Actions, not Vercel Cron (there is none in this repo).
  M1 lands ~16:40 Taipei instead of 15:30, inheriting the `/etc/hosts` IPv4 pin and
  `gssencmode=disable`. Pre-market gets its own workflow at 00:30 UTC. The Risk Guard step is
  **not** `continue-on-error` — a silent failure there is a stop-loss alert that never fired.
- PRD §5-M7 and §6 state review-only constraints (節律 veto and 兵法 quotes must never enter a
  scoring path). Turned into `inspect.getsource` assertions in `tests/test_rg_checklist.py`.
- Found but did not fix: `sql/003_rls.sql` places its final `REVOKE INSERT, UPDATE, DELETE ON ALL
  TABLES` **after** its own watchlist grant, so `apply_schema.py --rls` strips the write grant
  `w_add`/`w_remove` rely on. Noted in `sql/018_riskguard.sql`.
- Post-review fixes: (a) `flush_undelivered()` re-sends undelivered `critical` alerts at the end
  of both entry points — without it the new `(date, kind, dedup_key)` unique index turned a failed
  Telegram send into a permanently swallowed alert, since the next run's ON CONFLICT suppressed the
  re-record; (b) an active position with no `raw_twse_ohlcv` close now raises `stop_unchecked`
  instead of being silently skipped ("0 stop alerts" and "never checked" must not look alike).
- Verified: `raw_twse_index` holds 94 sessions back to 2026-02-25, so MA60 is computable across the
  replay range; and `daily.py` step 5b does upsert indices, so `last_trading_day()` advances daily.
- `pytest -q` → **202 passed, 5 skipped** (85 new). Source parsers tested against captured real
  2026-07-30 payloads.
- **Still unverified — needs [niko] with DB credentials:** no `.env` in this working copy, so
  `python -m riskguard.replay --start 2026-06-01 --end 2026-07-31` has never run against live
  data. `raw_twse_index` also has gaps (5/26–6/04, 7/10) and ends at 7/30, so MA60 may be short.

## [2026-07-31] lint | Documentation sweep — README, web README, alphatecx, system-architecture
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture, alphatecx]
- Root `README.md` was still the unmodified `tecxproj` template describing a project template.
  Rewrote as the real project README: layout, quick start, ingest cadence, MCP prefix taxonomy, auth.
- `web/README.md` was the untouched assistant-ui starter and stated two false things — that
  `OPENAI_API_KEY` is what you set (actual default provider is anthropic, via `LLM_PROVIDER`),
  and that the MCP client defaults to `localhost:8000` (actual: `MCP_SERVER_URL` required, throws
  if unset). Fixed both; left the accurate "How it's wired" section alone.
- [alphatecx](topics/alphatecx.md): page still called v2 "planning" and cited dead workspace paths
  12 weeks after v2 went live. Replaced Current State, closed the four answered Open Questions.
- [system-architecture](topics/system-architecture.md): listed 9 MCP tools against a live 44.
  Swapped enumeration for the prefix taxonomy + "sc_capabilities is the catalog" so it can't rot
  again. Diagram gained the Vercel/dashboard/web and Risk Guard branches; deployment-split rule
  (Vercel Root Directory = `mcp_server/`) recorded on the topic page for the first time.
- Wiki index verified complete — no orphan pages, no dead links.
- Concurrent session landed Risk Guard Phase 1 + the Zeabur migration mid-sweep; re-read the tree
  and folded both into README/CLAUDE.md rather than overwriting the newer risk-guard page.
- Left `BOOTSTRAP.md` alone — template artefact, its job is done, but removing it is [niko]'s call.

## [2026-07-31] lint | Dead-code sweep — unused imports and variables
attributed_to: [niko, antigravity-agent]   belongs_to: [system-architecture]
- Removed 13 unused imports (ruff F401) across 11 files and 3 assigned-never-read locals (F841):
  `counts` in both copies of `quant/regime.py`, `n_days` in `quant/leadlag.py`, and a
  function-local `plotly.graph_objects` in `correlation_snapshot.py:_fig_combined`.
- Scoped deliberately: `--select F401` on an explicit file list, not repo-wide `--fix`, so the
  configured `I`/`UP` rules could not rewrite unrelated files. `mcp_server/api/bot.py`,
  `riskguard/`, and `mcp_server/api/rg/` were skipped — concurrent session has them uncommitted.
- `src/quant/regime.py` and `mcp_server/api/quant/regime.py` edited together; the mirror pairs
  still differ by exactly one line each (the `MCP_DATABASE_URL` fallback), invariant intact.
- `pytest -q` unchanged at 191 passed / 5 skipped.
- Flagged, not removed: `src/seed_supply_chain.py` has no callers, but having none is normal for a
  one-shot seeding script. [niko]'s call.

## [2026-07-31] decision | Zeabur cutover executed; matview bug fixed on both hosts
attributed_to: [niko]   belongs_to: [system-architecture]
- Niko: "check and auto do all". Executed the pending list from the migration entry above.
- Fixed `view_ticker_momentum` in `sql/002_views.sql`: group by `ticker_id, ai_pillar, node` and take
  the latest `company_name`/`market` via `(ARRAY_AGG(... ORDER BY date DESC))[1]`. Applied to Zeabur
  **and Neon** — Neon had the same broken refresh, just masked by stale rows. 10,584 rows on both.
- `sql/003_rls.sql` no longer hardcodes `GRANT CONNECT ON DATABASE postgres`; resolved at runtime with
  `current_database()`. That literal was wrong on every host the project has ever used.
- `apply_schema.py` gained `014_dim_ticker_classify.sql` — in the `--rls` branch, not the default list,
  because it GRANTs to `mcp_viewer` and would fail wherever that role doesn't exist.
- `018_riskguard.sql` had never been applied to any database; its 10 `rg_*` tables now exist on Zeabur.
- Non-obvious, worth not re-learning: the `DATABASE_URL` secret **must** end with a query string. All
  three workflows build `${{ secrets.DATABASE_URL }}&gssencmode=disable`, so a bare URL would push
  `&gssencmode=disable` into the database name. The secret ends `?sslmode=disable` (Zeabur has no TLS).
- Removed the `/etc/hosts` "Pin Neon hostname to IPv4" step from all three workflows — Zeabur's host is
  already a literal IPv4, so the step would have written `8.209.197.81 8.209.197.81`.
- Verified by connecting *as* `mcp_viewer`, not just as root: matview, `dim_ticker`, `rg_positions` all
  readable. `pytest -q` 191 passed / 5 skipped.
- **Still open:** the Vercel deployment env still points at Neon (CLI has no credentials here), so the
  MCP server reads the old DB until Niko switches it. Neon left running as rollback.

## [2026-07-31] ingest | Zeabur CLI usable, but only the GitHub-release build
attributed_to: [niko]   belongs_to: [system-architecture]
- Niko supplied a Zeabur API token so the CLI could reach the account (the migration entry above
  closed with "CLI has no credentials here"). CLI now authenticates as `nguyenvanqui291`, plan
  DEVELOPER. Project `alphatecx` (`6a6c3c70c553a2bc513cf1ce`) holds one service, `postgresql`
  (`6a6c3e4d2e9443830f4905ae`), created the same day as the cutover.
- **The npm package is abandoned.** `@zeabur/cli` on npm is pinned at `0.2.9` (`dist-tags.latest`
  = 0.2.9); real releases ship as bare binaries on GitHub, currently `v0.21.0`. `npm i -g
  @zeabur/cli@latest` reinstalls 0.2.9 and looks like a no-op upgrade.
- 0.2.9 **cannot talk to Zeabur at all**: it targets `gateway.zeabur.com`, which now answers with a
  Traefik default self-signed cert on a Linode IP, so every call dies as
  `x509: certificate signed by unknown authority`. The live endpoint is `api.zeabur.com`
  (Cloudflare, valid `CN=zeabur.com`), which only 0.21.0 uses. Symptom looks like a local CA/proxy
  problem and is not one — don't go chasing trust stores.
- Release assets are **raw Mach-O/ELF binaries, not tarballs** (`zeabur_0.21.0_darwin_arm64`);
  `tar xzf` on them fails with "Unrecognized archive format".
- Token was pasted in cleartext into a chat transcript and lands in `~/.config/zeabur`; it should be
  rotated in the Zeabur dashboard once the remaining cutover work is done.
- The `zeabur variable` subcommand is the path to the still-open item from the cutover — the Vercel
  deployment env — but note Vercel env vars are set with the *Vercel* CLI; Zeabur's only covers
  Zeabur-hosted services.

## [2026-07-31] decision | Pre-commit lint gate adopted from Lucky_vibes
attributed_to: [niko]   belongs_to: [system-architecture]
- Niko: "add check lint python before commit, like lucky vibes". Copied that repo's pattern
  (`pre-commit` + `ruff-pre-commit`) into `.pre-commit-config.yaml`, with two deviations.
- **Dropped `ruff-format`.** It would reformat 66 of 84 files (~11k lines). Because pre-commit only
  hands hooks the *staged* files, that churn would arrive one file at a time forever, burying real
  diffs in style noise. Enabling it should follow a single repo-wide format commit, not precede one.
- **Kept the gate viable** only because pre-commit is staged-files-scoped: `ruff check .` reports 344
  pre-existing errors here, so a full-repo hook would reject every commit. This is the same reasoning
  already recorded in CLAUDE.md's lint convention.
- Added `pytest -q` as a local hook (`pass_filenames: false`, `always_run: true`) — the suite needs no
  network or DB and finishes in ~0.1s, so gating every commit on all of it is free.
- Used hook id `ruff-check`; plain `ruff` is now a legacy alias (Lucky_vibes still pins the old one).
- Verified by probe: a file with unused imports + an unused local is rejected, imports auto-fixed,
  F841 reported. `pre-commit install` is required once per clone — the hook lives in `.git/hooks/`.

## [2026-07-31] decision | Risk Guard M1 verified against live data — two calibration fixes, one harvester bug found
attributed_to: [niko, claude-agent]   belongs_to: [risk-guard, alphatecx]
- First replay against live Zeabur data passed 7/7 scorable acceptance rows — but the per-subitem
  table showed the pass was hollow, so the numbers were re-derived from measurement.
- **Subitem 4 was a constant.** Foreign futures net OI never left 65k–86k net short across
  2026-06/07 — on +4.20% days and the −6.47% crash alike — so the PRD's 淨空>20,000口 threshold
  fired on every session and added a flat +2 to every score. 🟢 became reachable only when all four
  other subitems were zero, and 7/15 (+2.00%) / 7/21 (+4.20%) both read 🔴. Now scores the
  5-session *change* in net OI (thresholds = p10 ≈ 8,000 added / median ≈ 4,000 of the observed
  distribution). Deliberate departure from PRD §5 #4.
- Honest limit, measured: the change barely separates either — 7/24 (−2.67%) saw foreigners *cut*
  net short ~9,900 while 6/30 (+2.50%) saw them add ~6,600. 5d/10d/20d/percentile all invert on
  the days that matter, so the subitem is capped small; the light rests on trend + breadth + day.
- **Bands moved 0–2 / 3 / ≥4** (PRD says ≥5). Removing the constant dropped every score ~2. At ≥4
  exactly the seven acceptance sessions plus 6/26 (−3.64%) are red and calm days land at 0–1; at
  ≥5 the 7/24 row fails. Re-verified: 7/7 PASS, honestly this time.
- **Stale margin was being scored as current** — `margin_totals` returns rows on-or-before the
  session, so a stalled feed handed June's balance to a July session silently. Now requires an
  exact date match, else `data_missing`.
- **Pre-existing harvester bug, NOT fixed:** the margin feed has been dead since ~1 July —
  `ingestion_log` shows `twse_margin` `status='empty'`, 0 rows every trading day while `twse_t86`
  ingested 5,000+/day. Endpoint and parser are both fine (20260730 returns 1,873 rows by hand).
  The trap is `loader.get_ingested_dates`, which treats `status IN ('ok','empty')` as skip-forever,
  reading a transient failure as a confirmed holiday — so `--only margin` reports "29 skipped,
  0 rows" while the table stays empty. Repaired 2026-06-30→07-30 by hand (22 sessions, 41,081 rows)
  by bypassing the guard; **the bug will re-open on the next nightly run.**
- Even repaired, subitem 3 stays quiet through July and correctly so: margin balance *fell* 0.2%
  → 9.7%, i.e. retail deleveraging, not the "leverage rising into a falling tape" the rule seeks.
- `pytest -q` → **206 passed, 5 skipped**.

## [2026-07-31] decision | MCP server moved Vercel → Zeabur; DB link now private
attributed_to: [niko]   belongs_to: [mcp-server, system-architecture]
- Niko: "maybe host another in my zebuar no need in vercel anymore", then "impement". The pending
  "switch Vercel's env off Neon" item was **dropped, not done** — the server moved instead.
- The point isn't convenience. Co-locating with `postgresql` puts the read path on
  `postgresql.zeabur.internal:5432`, so the cleartext-credentials exposure flagged in the DB
  migration is *removed* from that path, not mitigated. **Still live for the harvesters**, which
  reach `8.209.197.81:32046` from GitHub Actions and remain in cleartext.
- Live: <https://alphatecx-mcp.zeabur.app>, service `6a6c4b0ed3dbd8abbc44eebb` in project
  `alphatecx`. Vercel + Neon both left running as rollback.
- `mcp<2` pinned in `mcp_server/requirements.txt` **before** first deploy: PyPI `mcp` is now 2.0.0
  and dropped `mcp.server.fastmcp`, so a fresh container build would have died at import where
  Vercel's older build never noticed. `uvicorn` added for the same reason — the image can't rely on
  whatever happened to be installed.
- New `mcp_server/api/app.py` merges bot routes into the MCP app; one uvicorn process can't do what
  `vercel.json` rewrites did. `index.py`/`bot.py` untouched on purpose so Vercel still works.
- `security.py` exempts `/bot/*` from the URL-secret gate — not a weakening, since on Vercel those
  routes were a separate function the middleware never saw. Webhook keeps its own header secret +
  owner chat_id gate. Tested: right secret 200, wrong 403, none 403, `/botevil` 404.
- Secrets: `mcp_viewer` password rotated (old value unrecoverable from Zeabur vars) and root `.env`
  re-synced for `apply_schema.py --rls`. **`MCP_BEARER_TOKEN` and the Telegram webhook secret are
  both new** — the originals lived only in Vercel's env. Telegram webhook re-registered.
- Non-obvious, cost me time: `zeabur variable create` hangs without `-i=false`; CLI-deployed
  services reject `service redeploy` with `CANNOT_REDEPLOY_INPLACE` (needs a bound GitHub repo);
  and the first boot's 1m46s image pull makes early health checks read 502 like a crash loop.
- Corrected a real doc bug found by probing: the MCP endpoint is `/mcp/<token>/` with the trailing
  slash. `web/README.md` documented `/mcp/<token>/mcp`, which 404s.
- Explicitly **not** done: de-duplicating `src/quant/` ↔ `mcp_server/api/quant/`. That mirroring
  existed only because Vercel's Root Directory was `mcp_server/`; containers dissolve the
  constraint, so it's now removable — as its own piece of work, not a side effect of this one.
- `pytest -q` 211 passed; focused `ruff check` clean; 44 tools verified live over MCP with
  `sc_data_status` reading 608,082 `raw_twse_t86` rows.

## [2026-07-31] lint | Replay harness was lying without --write; M1 acceptance is 5/7, not 7/7
attributed_to: [claude-agent]   belongs_to: [risk-guard]
- Correction to the two entries above. `store.build_metrics` read breadth history from
  `rg_market_daily`; run without `--write` that table was empty, so the 5-day breadth mean
  collapsed to today's single ratio — far more bearish, and inflating precisely the down days the
  acceptance table checks. Report-only and `--write` scored the same session differently, and both
  earlier "7/7 PASS" claims were artefacts of it.
- Fixed: `build_metrics` takes `breadth_prior`; the replay carries breadth in memory. The two modes
  now agree exactly.
- **Honest result: 5/7 pass. 7/07 and 7/24 fail.** A single-day breadth collapse barely moves a
  5-day mean — 7/07 printed 128↑/892↓ (0.126) but its 5-day mean was 0.517 because 7/01–7/06 were
  strong; 7/24's was 0.500. Both score 2 against a required yellow/red.
- Closing those two means changing PRD §5's 5日均 wording (same-day breadth term, or a shorter
  window), not tuning a threshold. Not done unilaterally — left for [niko].
- 36 sessions persisted to `rg_market_daily` (2026-06-01 → 07-30), so the light now has state and
  tomorrow's cron has a `prev_light` to reason from. All other rg_* tables remain empty by design
  (no positions, no trades, no alerts yet).

## [2026-07-31] decision | Near-real-time news = polling worker + Telegram, not SSE/WebSocket
attributed_to: [niko]   belongs_to: [alphatecx, system-architecture]
- Niko asked if the system needs Redis, then whether real-time news/signals need SSE or WebSocket. Neither was the binding constraint. No Redis anywhere in the repo and nothing wants it (materialized views, Actions-as-scheduler, clock-pure `session_state`, no limiter, no fan-out). Transport was the wrong layer: `news_harvest.yml` fires 6×/day, so a perfect WebSocket still delivers 4-hour-old news.
- GitHub Actions cannot close that gap — scheduled workflows floor at 5 min and are routinely queue-delayed past it. Closing it needs a long-running process, which the Zeabur move now permits.
- Built `src/news/watch.py` + `Dockerfile.newswatch`: its own Zeabur container, polls every feed on `NEWS_POLL_SECONDS` (default 180), pushes matches to Telegram. Reuses `harvest._fetch_feed` / `_upsert` so dedup + upsert SQL stay single-sourced; `_upsert` now returns the inserted rows rather than a count, since a fresh insert is the only reliable "never seen this article" signal.
- Telegram is the only consumer (Niko's call), so the browser half — SSE over `LISTEN`/`NOTIFY` for `web/` — is deliberately not built. Noted for whoever does: `security.py` gates only `/mcp`, `/g`, `/d`, `/h`, `/t`, so a new `/events` route ships unauthenticated by default.
- Non-obvious, and each would have shipped a quiet bug: (1) `raise_for_status()` does **not** raise on 304 and the body is empty, so an unchecked conditional GET hands `b""` to feedparser and logs the healthy path as an unparseable feed; (2) "fresh DB insert" ≠ "new news" — cold start makes every article fresh, hence a priming cycle that ingests without announcing, plus a 6h recency gate for feeds re-surfacing old items; (3) `watchlist.company_name` is English (bot-written) while `dim_ticker.company_name` is TWSE's Chinese name — half the feeds are zh-Hant, so matching on one alone silently under-alerts.
- Conditional GET is load-bearing, not politeness: at 480 cycles/day an unconditional fetch re-upserts every unchanged row and `ON CONFLICT DO UPDATE` writes a new row version regardless, churning dead tuples all day. Cache is in-memory by choice — a restart costs one full fetch.
- Structural ceiling worth restating: this speeds up **news only**. Risk Guard and flow leaders derive from T86, which TWSE publishes once a day near 15:00. No transport makes institutional-flow signals intraday.
- Deploy inside the Zeabur project against `postgresql.zeabur.internal:5432` — this service carries *write* credentials and that Postgres has TLS disabled outright.
- Environment quirk found while testing: bare `pytest -q` no longer collects the suite. The new test imports `src/news/harvest.py`, which needs feedparser and (via `harvester/loader`) polars; Homebrew python is PEP-668 externally-managed so neither installs there. Bare `python3` only ever worked because nothing under `src/` had tests. `.pre-commit-config.yaml` now prefers `.venv/bin/python`, falling back to `python3`.
- `.venv/bin/python -m pytest -q` 326 passed (26 new); focused `ruff check` clean on the three touched files.
- Verified live, not just unit-tested: one `--once` cycle loaded 3 watchlist tickers, fetched 776 items across 12 feeds in ~54s, upserted 5 new rows, sent nothing (priming). A second `poll_once` sharing the cache dropped to 677 fetched with 3 feeds answering 304.
- That measurement changed the design: **only 5 of 12 feeds send ETag/Last-Modified**, so conditional GET can't carry the load alone. `_upsert`'s `DO UPDATE` now carries `WHERE raw_news.published_at IS NULL` — same intent (backfill a null date), but an unchanged conflict updates nothing and returns no row, so `fetchone()` yields `None` and the existing logic counts it as a duplicate. Without it, ~600 no-op row versions per cycle × 480 cycles/day.
- Still Niko's to do: create the Zeabur service, set `DATABASE_URL` (internal host), `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `NEWS_POLL_SECONDS`. Code and `Dockerfile.newswatch` are committed; nothing is deployed.

## [2026-07-31] decision | Fixed the margin harvest bug — `empty` meant two different things
attributed_to: [niko, claude-agent]   belongs_to: [alphatecx, risk-guard]
- Root cause: TWSE publishes 融資融券彙總 **after** the 16:30 harvest window, so the nightly
  `fetch_all_margin(target)` legitimately returns nothing. That was logged `status='empty'`, and
  `loader.get_ingested_dates` treated `empty` as "confirmed holiday — skip forever". The day could
  then never be retried: `--only margin` reported "29 skipped, 0 rows" against an empty table while
  the endpoint served the data fine. Every session ~2026-07-01→07-30 was lost this way while
  `twse_t86` ingested 5,000+ rows a day, and Risk Guard's M1 margin subitem scored blind for a
  month with nothing surfacing it. A failure that records itself as a success is the worst kind.
- Fix is two independent guards, because there are two failure modes:
  1. **`get_ingested_dates` is calendar-aware.** `empty` is only skippable when the date is a
     weekend or a `market_holidays.is_closed` day; an `empty` on a real trading day is retryable.
     Re-fetching a genuinely dead day costs one request that returns nothing.
  2. **`daily.py` sweeps recent gaps.** Each run re-attempts up to 3 sessions that still have no
     rows in `raw_twse_margin` (`loader.margin_sessions_missing`, keyed off the *data* not the log,
     so it repairs the gap whatever caused it — including a log row that lied). A late publish now
     lands on the next run instead of being lost. Longer outages remain a `src.backfill.run` job.
- Verified live: `2026-07-30` holds both an `empty` and the repaired `ok` → correctly skipped;
  `2026-07-31` holds only an `empty` on a trading day → **retryable**, where before it was dead.
  `margin_sessions_missing` reports none outstanding.
- 9 new tests (`tests/test_margin_catchup.py`); suite 336 passed.

## [2026-07-31] decision | Scheduled work moved onto Zeabur as the `cron` service
attributed_to: [niko]   belongs_to: [system-architecture]
- Niko: "run everything on zeabur now" + "do not replace old one", then "auto fix all". GitHub
  Actions stays enabled and runs the same schedules in parallel; double runs are safe because
  every writer upserts on composite PKs.
- New service `cron` (`6a6c5695c553a2bc513cfdef`) from the repo-root `Dockerfile`, supercronic as
  PID 1. Project is now four services: `postgresql`, `mcp`, `cron`, `worker` (news poller).
- Crontab is written in **Taipei local time** with `TZ=Asia/Taipei` in the image, not UTC. The
  workflows only use UTC because GH runners are UTC-only, and that conversion is a standing
  source of "fixed" schedules that fire eight hours wrong.
- **Telegram deliberately unset on `cron`.** Everything about a double run is idempotent except
  the message layer — setting `TELEGRAM_TOKEN` makes every brief and Risk Guard alert arrive
  twice. Accepted consequence: a `cron` failure is currently silent; GH Actions still notifies.
- Chain omits `dashboard.build` / `build_ticker_pages` / `correlation_snapshot` — their only
  output is static files that get committed back to main, and this service does not commit.
- Two real bugs caught while building, both silent-failure shaped:
  - `riskguard/pipeline.py` imports `mcp_server.api.rg` (the purity split), so excluding
    `mcp_server/` from the build context broke the image outright. Needs `mcp_server/api/`
    minus `static/`; they're PEP 420 namespace packages resolved via `/app` on `sys.path`.
  - `docs/theses/` is a **runtime input** — `brief.py:180` and `thesis_status.py` read thesis
    frontmatter. Excluding it as "docs" makes both report zero active theses rather than fail.
- Zeabur trap worth not re-learning: `zbpack-v2` pre-processes the Dockerfile, and one early
  build yielded a container whose PID 1 was an auto-detected `python -m src.news.watch` with no
  `/app/deploy` at all. Always check `cat /proc/1/cmdline` after deploying; don't assume the
  Dockerfile was honoured. Image pulls also run 6–8 min, so a redeploy straddling a scheduled
  slot silently eats it — that is how today's 16:30 Zeabur run was lost (GH Actions covered it).
- **Not yet verified:** the post-close chain firing on Zeabur. First real run is the next
  weekday 16:30 Taipei. `FINMIND_TOKEN` is also unset on `cron` (it lives only in GH secrets),
  so the nightly FinMind enrichment step self-skips there.

## [2026-07-31] decision | Mobile MCP access needs OAuth; plan written, build deferred
attributed_to: [niko]   belongs_to: [alphatecx, system-architecture]
- Niko needs the MCP server reachable from mobile. Only cloud connectors serve mobile, and Anthropic's connector flow now requires OAuth — it probes `/.well-known/oauth-protected-resource`, gets the blanket 404 `security.py` returns for unknown paths, falls back to Dynamic Client Registration at `/register`, gets 404 again, and fails with "Couldn't register with Alphatecx's sign-in service". Nothing is broken server-side; URL-as-secret simply isn't an auth scheme the connector can negotiate.
- Working today without OAuth: Claude Code (`claude mcp add`, verified connected) and Claude Desktop via an `mcp-remote` stdio bridge in `~/Library/Application Support/Claude/claude_desktop_config.json` (verified: "Proxy established successfully"). Both are local-only — neither helps mobile.
- Plan written to `docs/OAUTH-PLAN.md`; **implementation deliberately not started.** Two prerequisites block it, and both are recorded there.
- Correction to something claimed earlier in the session: the existing `Alpha`/`Alphatecx` cloud connectors were described as "grandfathered", implying editing their URL would preserve mobile access. That was a guess stated as fact — no evidence either way about edit-vs-create behaviour in the connector flow. Cheap to try, but don't plan around it.
- Design decision recorded up front so it isn't relitigated: keep URL-as-secret alive at `/mcp/<token>/` and add bearer auth at bare `/mcp/`. Additive, independently revertable, and it stops an auth rewrite from taking out the two surfaces that currently work.

## [2026-07-31] lint | Two instances answer as "the" database; /status silence traced to it
attributed_to: [claude-agent]   belongs_to: [alphatecx]
- `postgresql.zeabur.internal:5432` and `8.209.197.81:32046` present the same user (`root`) and database name (`zeabur`) but return **different rows**: `rg_positions` active-watch is 7 rows via `.env` (`2327 2338 2344 2408 3374 6239 8299`) and 4 via the deployed bot (`2324 2344 2408 8299`). `2324` exists in one and not the other, so this is not caching. An earlier note in this session calling them "the same database, different route" was wrong; the row sets disprove it.
- Best explanation for the `/status` silence: `cmd_status` reads `rg_market_daily`, which has rows on the `.env`-reachable instance — run locally it returned a full 232-char reply — and evidently not on the one the bot reads. `if reply:` then skips the send, so no message, no error, no log. `/help` (no DB) replied fine throughout, which is what isolated it.
- Open and load-bearing: the harvesters use `DATABASE_URL`, the `mcp` service uses `BOT_DATABASE_URL`/`MCP_DATABASE_URL`. If those resolve to different instances, writes and reads have been diverging. Settle which is authoritative before applying any further migration — `apply_schema.py` is manual and migrates whatever `DATABASE_URL` happens to point at.
- Contributing factor worth fixing on its own: `bot.py:_send` never checks Telegram's response — no `raise_for_status()`, no status check — so a rejected reply disappears without a trace. Two config bugs found earlier today (token pointing at bot `7984740171`, `TELEGRAM_CHAT_ID` set to a chat that doesn't exist) were slow to find for exactly that reason.

## [2026-07-31] decision | OAuth shipped stateless; mobile MCP access works
attributed_to: [niko]   belongs_to: [alphatecx, system-architecture]
- Reverses the "build deferred" entry above. Every cheaper path was tried and failed empirically: a new cloud connector 404s through discovery into DCR, and **editing an existing connector's URL fails the same way** — so the "grandfathered connector" hope recorded earlier is now disproven, not just unverified. Repointing the shared Vercel deployment was ruled out: that project belongs to another branch's work.
- Shipped `23f1bc1` + `af4c8c6`. Live and confirmed working on mobile by [niko].
- **The design change is what dissolved the blocker.** The plan called for `oauth_clients`/`oauth_tokens` tables; the build is stateless — HMAC-signed tokens carrying their own claims, `client_id` derived from the registered redirect URIs, nothing written to Postgres. So the unresolved question of which instance is authoritative stopped being load-bearing. Only `_CONSUMED` holds state (process-local, code ids), because a signature cannot make an authorization code single-use.
- Additive on purpose: `/mcp/<token>/` still serves with no bearer header, and bare `/mcp` is the OAuth mount and the only path answering 401 instead of 404. Mount order matters — the token prefix registers first or it gets swallowed. The regression guard (`/mcp/<token>/` returns 200 with no `Authorization`) was checked at every step; it is what keeps Claude Code and the Desktop `mcp-remote` bridge alive.
- Two failures worth not repeating. **(1)** `zeabur deploy` from the repo root built the root `Dockerfile` — the supercronic worker — so the `mcp` service booted running cron and the server was down ~10 minutes. Deploy `mcp` from `cd mcp_server`, always. **(2)** Starlette's mount answers `/mcp` with a 307 to `/mcp/`, and a connector that has just authorized does not reliably re-issue its POST (body + `Authorization`) against the redirect target. That reads as "your account was authorized, but the server returned an error when connecting" — OAuth fine, handshake after it broken. Fixed by rewriting the request scope rather than advertising the slash and trusting clients.
- Also scoped an `E402` per-file-ignore to `index.py` in `pyproject.toml`: its imports sit below a deliberate `sys.path.insert`, and the file had never been staged since the pre-commit gate landed, so structural warnings surfaced as a blocker.
- `docs/OAUTH-PLAN.md` updated to record the divergence — it described a token table nobody should now build.
- 364 tests pass; focused `ruff check` clean. Verified in production: register → authorize → token → bearer `initialize`, wrong password 401s, replayed code 400s.

## [2026-07-31] lint | Phase 1 acceptance round 2 — stale closes, a revoked grant, and a spec that breaks the green light
attributed_to: [niko]   belongs_to: [risk-guard]
- **P0-1 settlement -2,101,795 was test data, cleared.** It came from the `/trade buy 2330 1050 x2` typed at 16:45 Taipei while the bot was silently failing to reply — the write succeeded, the reply did not, so it looked like a no-op. Amount was arithmetically correct (1050 x 2 lots x 1000 + 1,795 fee at the 6折 rate), units were right, parser was right. Third distinct injury from `bot.py:_send` not checking Telegram's response.
- **P0-2 stale closes — real, and the worst bug found today.** `_rg_closes` took each ticker's newest `raw_twse_ohlcv` row *whatever its date* and rendered it as today's price. That table does not cover every watchlist name: of 2324/2303/3374/2344 only 2344 had a 7/31 row. So 2324 displayed 29.65 against a real 36.0, and 2303 displayed 91.3 against a real 121.0 (limit up), with no marker. The stop engine reads that number. Fixed by measuring staleness against the table's own max date (no calendar, so weekends/holidays need no case) and **dropping** stale entries — `rg_stops.distances` already degrades safely on a missing close, so a wrong price can no longer reach a stop decision at all. Both renderers now say so out loud.
- **P0-3 `rg_journal_add` permission denied — an ordering bug in `apply_schema.py`.** `018_riskguard.sql` grants the INSERT and its own comment says "run this file after any --rls run", but the script appended `003_rls.sql` *afterwards*, and 003 ends with a blanket `REVOKE INSERT, UPDATE, DELETE ON ALL TABLES`. So every `--rls` run silently took back the grant the same run had just made. Re-appended 018; grant also applied live.
- **P1 futures scoring — implemented to spec, then reverted, and the revert is the finding.** PRD §5 scores the absolute net-short level (≥20,000 口 → +2). Measured first: across all 37 recorded sessions the foreign net OI ran -63,168 to -86,189, i.e. the threshold is crossed on **100% of days**. Implementing it made the subitem a constant +2, pinning the floor score at 2 against a green band of ≤2 — and the suite caught it, `test_calm_market_scores_zero_and_is_green` failing along with three tests whose names (`test_futures_scores_added_net_short_not_the_level`, `test_a_deep_but_unchanged_net_short_scores_nothing`) show the change-based design was deliberate and regression-locked. **A quiet market would stop being green.** Reverted. The spec is what needs amending — same class as the §5 5日均 breadth wording already logged. Reinstating the level needs a threshold the data crosses (rolling percentile, or ~80,000) *and* recalibrated `SCORE_YELLOW`/`SCORE_RED`.
- **P1 alerts baseline — no change made, the stated rationale does not hold.** Light-change detection compares `store.prev_market_day()`, i.e. `rg_market_daily`, which has 37 rows; it is not reading `rg_alerts`. Monday's run will see `prev_light='red'` from 7/31. `rg_alerts` is empty because the history was written by `riskguard.replay --write`, which deliberately does not emit alerts. Design, not defect.
- Untouched and still open: the margin fetcher gap, and `/balance` (only [niko] can report it, M2b has no baseline until then).

## [2026-08-08] decision | Commercialization direction — MCP connector first, headless Claude app second (proposed)
attributed_to: [niko, brian, antigravity-agent]   belongs_to: [alphatecx]
[niko] and [brian] want to sell alphatecx to funded, finance-averse investors who consult Claude for decisions — the tool giving Claude a strong Taiwan-equity ground truth. Two surfaces proposed: [niko] a remote **MCP connector** (Apollo.io / WordPress.com model), [brian] a **native mobile app** on safety grounds. Reframed the choice: "sell credit through the connector" conflates (A) a connector where the customer's own Claude sub pays and you sell a data subscription — ~80% built, since OAuth 2.1+PKCE already shipped — vs (B) a headless web app embedding Claude via the Agent SDK where you resell the AI and own the guardrails. Recommendation logged as **Phase 1 = model A (Stripe-gated connector), Phase 2 = model B for [brian]'s safety requirement, mobile deferred to a thin shell.** [brian]'s safety concern is valid but mobile is the wrong lever — guardrails come from owning the AI surface, and the "can't keep up with Claude" fear applies only to apps replicating the consumer chat UI, not the stable Messages/Agent SDK API. Open gate: **regulated-investment-advice / licensing exposure (RIA / SFC-type) — needs a lawyer before taking money**; connector framing (data provider, not advisor) is the lower-liability posture; add disclaimers to `_stamp()`. Status `proposed`, not finalized. New stakeholder page: [brian].

## [2026-08-08] decision | Productization plan — MoR payments, multi-tenant OAuth, metering, disclaimer
attributed_to: [niko, antigravity-agent]   belongs_to: [alphatecx]
Model settled: sell a **subscription to data + tools** via the connector ([niko]'s call; [brian] still app-first). **Payments:** Stripe cannot be the merchant from Vietnam or Taiwan (neither is a self-serve payout country; TW cards can still *pay*). Chosen route = **Merchant of Record** (Lemon Squeezy / Paddle) — legal seller, handles tax, pays out to VN/TW via wire/Payoneer, sidesteps the block. SG/HK Stripe entity later if volume justifies; local TW rails (Line Pay/ATM) not needed for the funded-investor segment. **Phase 0 = sell private with no payment code** (invoice + wire, hand-provision). **Finding that reshapes metering:** the server is single-tenant — `oauth.py` hardcodes `sub="owner"` on one shared `OAUTH_PASSWORD`, so per-customer metering needs multi-tenancy first. The stateless-OAuth "no DB" decision is now safe to reverse (Zeabur collapsed the split database). Plan: Layer 0 multi-tenant identity (`customers` + `usage_monthly` tables, `sub=customer.id`), Layer 1 metering (ContextVar in middleware → count in `_stamp()`, enforce at session gate + soft flip), Layer 2 `_disclaimer` on every `_stamp()` response. Sequence L0+L2 first (unblocks private sales), L1 before charging, MoR webhook last. Detail in [commercial-productization](topics/commercial-productization.md).

## [2026-08-08] decision | Built Layer 0 (multi-tenant identity) + Layer 2 (disclaimer)
attributed_to: [niko, antigravity-agent]   belongs_to: [alphatecx]
Implemented the Phase-0-unblocking slice of the productization plan (uncommitted). **Layer 0:** `sql/019_customers.sql` adds a `customers` table (app-generated non-enumerable `cust_…` id, sha256 `secret_hash`, status, monthly_quota) with a role-guarded `mcp_viewer` SELECT+RLS grant — re-appended after 003 in `apply_schema.py` since SELECT survives 003's blanket REVOKE (no INSERT re-grant needed, unlike 018). `mcp_server/api/customers.py` holds pure secret helpers + a **fail-closed** `authenticate` (DB error ⇒ None, never mints a token) + an owner-only `provision` (writes as DATABASE_URL owner, secret shown once). `scripts/provision_customer.py` is the hand-provisioning CLI. `oauth.py` now threads `sub` through code→access/refresh (defaults to `"owner"` for back-compat; refresh preserves sub so a customer isn't downgraded). Multi-tenancy resolution lives in `index.py::_resolve_subject` (owner OAUTH_PASSWORD checked first — needs no DB, survives a customers-table outage — else per-customer secret), **kept out of oauth.py so it stays DB-free and its stateless tests are unaffected**. **Layer 2:** a constant, env-overridable `_disclaimer` on every `_stamp()` response. Known gap deferred to Layer 1: suspending a customer only blocks *new* logins; an issued token lives up to its TTL because `oauth.refresh` doesn't re-check DB status — the Layer-1 middleware session gate closes it. Tests: 20 new, all green; full suite 385 pass / 1 **pre-existing unrelated** failure (`test_news_watch::…second_cycle_alerts…`, date-dependent — fails identically on clean HEAD, may block the pre-commit pytest gate until fixed). Not committed; awaiting connector-vs-app lock before Layer 1 metering.

## [2026-08-08] observation | Repo moved to the tecxmate GitHub org; local remote still on the old URL
attributed_to: [antigravity-agent]   belongs_to: [infrastructure-accounts]
Pushing the L0+L2 connector work to `main` surfaced `remote: This repository moved. Please use the new location: https://github.com/tecxmate/alphatecx.git`. The push succeeded via GitHub's redirect, but the local clone's `origin` still points at `github.com/nikolasdoan/alphatecx` — should be `git remote set-url origin https://github.com/tecxmate/alphatecx.git`. **Caution recorded:** this reverses commit `75e40b7` ("repo moved back to personal"), and the Neon DB was migrated *off* a Tecxmate-affiliated account in 2026-05-08 because [niko] couldn't log into it — so confirm durable access to the tecxmate GitHub org before depending on it. Recorded in [infrastructure-accounts](topics/infrastructure-accounts.md) with a **Handoff** section added to [commercial-productization](topics/commercial-productization.md) so another agent (e.g. [brian]'s) can continue: repo remote fix, the two manual deploy steps (`zeabur deploy` then `apply_schema.py`), `provision_customer.py`, the still-open connector-vs-app decision, and Layer 1 metering left unbuilt. Open: who moved the repo and why; whether it affects GitHub Actions secrets or any future Zeabur repo binding.

## [2026-08-08] observation | Repo move to tecxmate was deliberate — [niko] is CEO, for [brian]'s access
attributed_to: [niko]   belongs_to: [infrastructure-accounts]
Resolved the previous turn's open question: [niko] (Nikolas) moved the repo to the tecxmate org himself. **He is the CEO of Tecxmate**, and the move was to give co-founder [brian] access as the project goes commercial. This is NOT the access trap that forced the 2026-05-08 Neon migration (an orphaned Tecxmate Neon login Niko couldn't reach) — the GitHub org is under his control. Caution in [infrastructure-accounts](topics/infrastructure-accounts.md) downgraded to a plain fact; local `origin` updated to `github.com/tecxmate/alphatecx`. [niko] stakeholder page now records the CEO/Tecxmate role.

## [2026-08-08] lint | Security scan of the L0 connector code — 1 HIGH (refresh doesn't re-check status)
attributed_to: [antigravity-agent]   belongs_to: [commercial-productization]
Ran `/security-scan`: AgentShield (deterministic, agent-config scope) graded the repo **A (98/100)**, 0 crit/high — only 2 low-confidence skill-health notes on `skills/README.md`. Because AgentShield doesn't scan application code, the `security-reviewer` agent reviewed the new auth diff. **1 HIGH:** `oauth.refresh()` re-mints a 1h access token *and a fresh 90-day refresh token* with no DB status check, so a suspended customer who keeps refreshing (normal connector behaviour) stays authenticated **indefinitely** — broader than the commit's "lives to its TTL" note. `status="suspended"` isn't a real kill switch yet. Fix before provisioning any suspended customer: re-check status at the `/token` refresh boundary in `index.py` (keeps `oauth.py` DB-free) and/or pull Layer-1's session gate forward. Runtime exposure today = nil (multi-tenancy undeployed, no customers). **Everything else verified clean:** parameterized queries (no SQLi), genuinely fail-closed `authenticate`, correct SHA-256 + `hmac.compare_digest` on high-entropy secrets, generic errors (no enumeration), `sub` HMAC-bound so no forge/escalate to owner, no secret leakage in logs/CLI, `mcp_viewer` SELECT-only + RLS correct, provisioning import-isolated to the owner path. Dead code: `customers.secret_matches()` unused. Not fixed this turn (no `--fix`, and it's committed on main) — corrected the understated gap in [commercial-productization](topics/commercial-productization.md) Status.

## [2026-08-09] fix | Closed the HIGH — refresh now re-checks customer status
attributed_to: [niko, antigravity-agent]   belongs_to: [commercial-productization]
Fixed the security-reviewer HIGH from 2026-08-08. The `/token` refresh grant in `index.py` now gates on `_subject_still_valid(sub)` before re-minting: owner always passes (no DB — revoked by rotating `OAUTH_PASSWORD`), a customer subject must still exist and be `active`, and it **fails closed** (deleted/suspended/DB error ⇒ refused). Kept in the HTTP layer so `oauth.py` stays DB-free (`verify` is pure; the status lookup is the only DB hit). Effect: a suspended customer is now bounded to ≤ the 1h access-token TTL instead of an unbounded 90-day refresh chain; the residual ≤1h window on an already-issued access token closes with Layer-1's per-session gate. 4 new tests (`SubjectStillValidTests`): owner skips the DB, active passes, suspended refused, unresolvable fails closed. Full suite 389 pass / 1 pre-existing unrelated failure; focused ruff clean.

## [2026-08-09] feat | Layer 1 metering — per-customer counts, quota gate; + news_watch fixture fix
attributed_to: [niko, antigravity-agent]   belongs_to: [commercial-productization]
Built Layer 1. `sql/020_usage.sql`: `usage_monthly(customer_id, yyyymm, calls)` with a narrow `mcp_viewer` SELECT/INSERT/UPDATE grant, re-appended after 003 (the write grant is stripped by 003's blanket REVOKE, same trap as 018). `mcp_server/api/usage.py`: `record()` best-effort upsert (never raises into a tool response) + `calls_this_month()` fails **open** to 0 (a read blip must not lock a customer out). `index.py`: a `current_customer` ContextVar set in `auth_gate` after bearer verify (FastMCP runs the tool in the same asyncio task, so `_stamp` reads it — no 45-tool signature change); `_stamp` meters the call (owner + anonymous skipped); `_customer_gate` per-session check returns **402** if the account isn't active and **429** once `monthly_quota` is reached. The gate **also closes the ≤1h residual** from the 2026-08-09 refresh fix — a suspended customer is now blocked at the read path each session, not only at refresh. Middleware now verifies claims directly (`_access_claims`) instead of the bool `bearer_token_valid`, so it learns `sub`. Activation: provision customers with a `monthly_quota`; counting + enforcement are automatic. 16 new tests; suite 405 pass, ruff clean. **Also fixed** the pre-existing date-dependent `test_news_watch` failure — the `_row` fixture hardcoded `published_at=2026-07-31`, which `run()` drops as stale via `is_recent` once past `MAX_ALERT_AGE` (6h); defaulted it to a recent timestamp (production was correct, fixture rotted). **Found, not fixed:** the `watchlist` INSERT/UPDATE grant (003:119) is stripped by 003's REVOKE (003:154) with no re-append, so `w_add`/`w_remove` break after `--rls` — separate fix needed.

## [2026-08-09] fix | Watchlist write grant restored — w_add/w_remove survive an --rls run
attributed_to: [niko, antigravity-agent]   belongs_to: [commercial-productization, system-architecture]
Fixed the pre-existing bug found while building Layer 1: `003_rls.sql` grants `mcp_viewer` INSERT+UPDATE on `watchlist` (line 119) then strips it with the blanket `REVOKE INSERT, UPDATE, DELETE ON ALL TABLES` (line 154), with no re-append — so after any `apply_schema.py --rls` run, `w_add`/`w_remove` failed `permission denied for table watchlist` (same class as 018/rg_journal and 020/usage). New `sql/021_watchlist_grant.sql` re-issues the grant (grant-only — the RLS policies from 003 survive the REVOKE since policies aren't privileges — role/table-guarded, idempotent), re-appended after 003 in `apply_schema.py`. Re-running 003 itself couldn't fix it because 003 ends with the REVOKE, hence a separate file. Deploy-only SQL, no pytest impact; suite 405 pass, ruff clean.

## [2026-08-09] decision+feat | Connector-first settled (private, no lawyer); MoR billing webhook built
attributed_to: [niko, antigravity-agent]   belongs_to: [commercial-productization]
[niko] (CEO) settled the direction: **connector-first**, and current use framed as **private, not a commercial sale**, so the investment-advice-licensing lawyer step is **set aside** as an explicit risk call (reopens if it goes public/commercial). Direction doc → `active`. **Built the Merchant-of-Record webhook (Lemon Squeezy):** `POST /billing/lemonsqueezy` verifies the HMAC signature over the raw body (`LEMONSQUEEZY_WEBHOOK_SECRET`), maps the LS subscription status (active/on_trial → active; cancelled/past_due/unpaid/paused/expired → suspended), resolves the customer by `custom_data.customer_id` (email fallback), and flips `customers.status`. New `mcp_server/api/billing.py` (pure verify + mapping), `customers.set_status`/`get_by_email`, and `sql/022_customers_status_grant.sql` — a **column-scoped** `GRANT UPDATE (status, updated_at) ON customers` (never INSERT/DELETE or other columns; provision stays owner-only), re-appended after 003 like 018/020/021. `security.py` exempts `/billing/*` from the URL-secret gate (the HMAC signature is the credential), with segment-aware guarding. The write runs through the read pool via that narrow grant — no owner DSN on the server. Webhook returns 401 bad-sig, 400 bad-json, 200 ack (incl. unknown customer, to stop retries), 500 on write failure (so LS retries). 20 new tests (billing verify/map, set_status/get_by_email, _apply_billing glue, /billing gate exemption). Suite 427 pass, ruff clean. Dormant until `LEMONSQUEEZY_WEBHOOK_SECRET` is set + the LS webhook is pointed at the host; hand-provisioning still works while private.

## [2026-08-09] docs | Deploy checklist for the paid connector
attributed_to: [antigravity-agent]   belongs_to: [paid-connector-deploy]
Wrote [paid-connector-deploy](topics/paid-connector-deploy.md) so [niko] or [brian] can take Layers 0–2 + metering + billing live cleanly. Ordered runbook: (1) `apply_schema.py --rls` to land the 019/020/021/022 tables+grants (re-appended after 003), with a `\dp` verify; (2) set `ALPHATECX_DISCLAIMER`/`LEMONSQUEEZY_WEBHOOK_SECRET` on the Zeabur mcp service (`-i=false` or it hangs); (3) `zeabur deploy --service-id …` (CLI-uploaded → no in-place redeploy); (4) `provision_customer.py`; (5) end-to-end verify of sub/metering/suspend-402/quota-429; (6) optional Lemon Squeezy billing wiring; rollback + gotchas (trailing-slash `/mcp/<token>/`, the REVOKE-strip ordering, column-scoped status write). Linked from the productization Handoff and the index.

## [2026-08-09] feat+docs | Admin CLI (list/suspend/activate) + client connect guide for the manual flow
attributed_to: [niko, antigravity-agent]   belongs_to: [commercial-productization, paid-connector-deploy]
Rounded out the private/manual flow ([niko]: give access manually, clients wire money manually — no MoR). `scripts/manage_customer.py`: `list` (all customers + this-month usage), `suspend`/`activate` by email or `cust_` id — reuses `customers.set_status`/`get_by_email`/`get` + new `customers.list_all()`, so revoke/reactivate needs no raw SQL. Runs locally as owner via root `.env`. `docs/CLIENT-CONNECT.md`: client-facing 2-minute connect guide (connector URL + `atx_` key → Settings → Connectors → paste key on the authorize screen), plus "data not advice" note and troubleshooting. The money stays entirely off-system (bank/Wise); the operator flips `status` when it arrives. Deploy checklist updated to use the CLI instead of raw SQL. 2 new tests (`list_all`); suite 431 pass, ruff clean.

## [2026-08-09] decision+feat | Connector teaching UX — persona in server instructions + start_here tool
attributed_to: [niko, antigravity-agent]   belongs_to: [mcp-server, commercial-productization]
[niko] asked if 44 tools is too many (clients on Opus 5 / 1M) and whether to bake teacher/consultant language into tools. **Decision:** keep the ~44 tools — context is a non-issue (~8–15k tokens of schema on 1M); the real cost is *selection accuracy*, and teaching belongs in layers, not tool count. **Built steps 1+3:** (1) server `instructions` (`CONSULTANT_INSTRUCTIONS` in `index.py`, was `None`) — the whole-connector persona: advise a non-expert, define jargon plainly, start from the question, chain simplest-first, never buy/sell, cite `_as_of`; (3) a `start_here` tool (first tool) returning a plain-language menu (what to ask → which tool) + beginner glossary, complementing the technical `sc_capabilities`. Both go through `_stamp` (start_here carries `_disclaimer`). Drafted the step-2 **description template** ([tool-description-style](topics/tool-description-style.md)) with a before/after on `q_valuation` and the top-10 rewrite priority. Deferred: step 2 (top-10 pass), step 4 (selective `_glossary`, consolidating the 5 overlapping screeners). Layer map recorded so "act like a teacher" lives ONCE in instructions, not in 44 descriptions. 5 new tests (`test_onboarding`); suite 436 pass, ruff clean. Decision doc: [2026-08-09-connector-teaching-ux](decisions/2026-08-09-connector-teaching-ux.md). Dormant until next `zeabur deploy`.

## [2026-08-09] feat | Step 2 — top-10 tool descriptions rewritten for the model-as-consultant
attributed_to: [niko, antigravity-agent]   belongs_to: [mcp-server, tool-description-style]
Rewrote the 10 beginner-facing tool docstrings per the template: each now leads with a plain-language question ("Is a stock cheap or expensive?", "Who is buying or selling a stock?", "Is the Taiwan market risky right now?"), adds a "When to use" line, an inline jargon gloss (P/E, P/B, ex-dividend date, OHLCV, flow, limit up/down, sleeper), and key fields where useful. Docstrings only — no logic changed; Args preserved. Tools: beginner_stock_card, quote, q_valuation, dividend_calendar, flow_leaders_scan, rg_status, price_history, n_for_ticker, sc_ticker_momentum, ticker_lookup. Suite 436 pass, ruff clean. Remaining from the plan: step 4 (selective `_glossary` in responses; consolidate the 5 overlapping screeners with when-NOT-to-use lines).

## [2026-08-09] feat | Risk-profile personalization — per-user investment style, established at onboarding
attributed_to: [niko, antigravity-agent]   belongs_to: [mcp-server, commercial-productization]
[niko] (conservative) vs [brian] (aggressive): the AI should adapt investment style to each user's risk tolerance and establish it during onboarding. Built a **per-customer** risk profile — fixed tiers `conservative | balanced | aggressive` + optional `risk_note` — stored on the customer so it persists across every conversation. `sql/023` adds the columns and extends the column-scoped `mcp_viewer` UPDATE grant (from 022) to them, re-appended after 003. `customers.py`: `VALID_RISK`, `get_risk` (fails soft — {} if columns absent pre-migration), `set_risk_profile` (writes via the read pool + grant); `list_all` now returns risk. `index.py`: `my_profile` (returns tier + `how_to_adapt`) and `set_my_risk_profile` tools, `_RISK_GUIDANCE`, a risk paragraph in `CONSULTANT_INSTRUCTIONS` (call my_profile early; if unset ask + save; conservative→preservation/dividends/downside, aggressive→growth/momentum/higher risk-reward, balanced→both), and a `personalize` nudge in `start_here`. Set via the tool, `provision_customer.py --risk`, or `manage_customer.py set-risk`. Owner sessions have no stored profile (tools say so). **Latent trap handled:** stamped tools meter via `usage.record`, so tests that set `current_customer` must patch it or they hit the live DB (one test stalled ~120s before this fix). 12 new tests; suite 448 pass, ruff clean. Dormant until next deploy + apply_schema (023). Decision: [2026-08-09-risk-profile-personalization](decisions/2026-08-09-risk-profile-personalization.md).

## [2026-08-09] feat | Step 4 — response glossaries + screener disambiguation
attributed_to: [niko, antigravity-agent]   belongs_to: [mcp-server, tool-description-style]
Finished the teaching-UX plan. `_stamp` gained an optional `glossary` → attaches `_glossary` to a response so the model labels metrics correctly; wired to the 3 beginner tools with the most jargon (beginner_stock_card, q_valuation, rg_status) via `_GLOSS_*` constants. The 5 overlapping screeners each got a "Which screener?" line pointing to the right sibling (flow_leaders_scan = pre-move cheap sleepers; market_flow_screener = whole-market flow ranking; sc_accumulation_screen = simple foreign streak in AI names; q_screener = technical setups; q_factor_screen = statistical alpha, advanced). Kept all 5 — disambiguation, not a risky merge (true consolidation would change the API for little gain). 1 new test; suite 449 pass, ruff clean. Teaching-UX plan (steps 1–4) complete.

## [2026-08-09] feat | Investing-principles layer — school-neutral universals, kept out of the data tools
attributed_to: [niko, antigravity-agent]   belongs_to: [mcp-server, commercial-productization]
[niko] asked whether to fold his investing-books shelf into the tools. Built a reasoning layer with [niko]'s constraint "only principles that are universally true": the `investing_principles` tool returns 9 cross-school universals — margin of safety (Graham/Housel), know what you own (Lynch/Fisher), survival first (Housel/Douglas), master your psychology (Douglas/Graham), price≠value (Graham), beware manias (Kindleberger/Dalio), time & compounding (Bogle), costs compound against you (Bogle), humility/process-over-outcome (Douglas). **Contested doctrine excluded** (index-vs-pick, technical analysis, any single strategy). **Distilled in our own words + attributed, NOT ingested** — the books are in copyright, so serving their text would be redistribution; ideas aren't copyrightable, expression is. Kept SEPARATE from the clean data tools (no philosophy baked into what q_valuation/flow/rg_status return). Tier-aware *emphasis* only (reads the customer's stored risk profile): conservative → margin of safety/diversification/preservation; aggressive → the guardrails matter most; principles themselves never change. Server instructions now tell the AI to ground reasoning in it (cite, apply, don't preach, don't push one strategy). Note: Horowitz's Hard Thing is a company-building book, not investing — for the founders, not the tool. 4 new tests; suite 453 pass, ruff clean. Topic: [investing-principles](topics/investing-principles.md).

## [2026-08-09] fix+ops | Deploy blockers found: .env→Neon, apply_schema not delta-safe; built apply_delta.py
attributed_to: [niko, antigravity-agent]   belongs_to: [paid-connector-deploy, system-architecture]
Starting the live deploy surfaced two blockers. (1) **Local `.env` points at Neon, not Zeabur** — both root `DATABASE_URL` and `mcp_server/.env` `MCP_DATABASE_URL` resolve to `ep-cold-lab…neon.tech` (legacy rollback). The live mcp service reads the **Zeabur** Postgres via env vars set *in Zeabur* (`postgresql.zeabur.internal`), so migrations run off local `.env` hit the wrong DB. A first `apply_schema.py --rls` attempt went to Neon and also printed a Neon owner credential to the terminal (apply_schema echoes the DSN prefix) — rotate/decommission Neon when convenient. (2) **`apply_schema.py` is not delta-safe on a populated DB:** it re-runs from 001 and `sql/004_quant.sql` dropped `view_latest_signals` without CASCADE, dying on the dependent `view_universe`. **Fixes:** added `CASCADE` to 004's DROP (008 recreates view_universe, so idempotent now); wrote **`apply_delta.py`** which applies only the connector migrations 019–023 against a given DSN (`ZEABUR_DATABASE_URL`/`--dsn`), prints only the HOST (no creds — unlike apply_schema), warns if the DSN is Neon, confirms, applies, and verifies the tables/columns. Zeabur mcp service id confirmed = `6a6c4b0ed3dbd8abbc44eebb`; project `6a6c3c70c553a2bc513cf1ce`. Deploy runbook updated with the Neon-in-.env gotcha and the apply_delta path. **Blocked on:** the Zeabur owner public DSN (the postgresql service Connection String) to actually migrate + provision against production. Suite 453 pass, ruff clean.

## [2026-08-09] ops | Paid connector is LIVE — auto-deploy discovered; migrations applied to Zeabur; first customer provisioned
attributed_to: [niko, antigravity-agent]   belongs_to: [paid-connector-deploy, system-architecture]
Went to deploy and found the **`mcp` Zeabur service auto-deploys from `main`** — `zeabur deployment list --service-id 6a6c4b0ed3dbd8abbc44eebb` shows one RUNNING deployment per commit (source `refs/heads/main`, plan docker), currently `aabfed6`. So **every push today already shipped to production**; the "CLI-uploaded / manual deploy / CANNOT_REDEPLOY_INPLACE" note (2026-07-31) is outdated — the repo was git-connected since. The only missing piece was the DB: applied `019–023` to the Zeabur public owner endpoint (`8.209.197.81:32046/zeabur`) via `apply_delta.py` — `customers` + `usage_monthly` now exist with all columns. Live health `{"ok":true,"server":"alphatecx-v2"}`. Provisioned the first customer end-to-end against Zeabur: **[niko]** = `cust_6waRdgqBr-AJ`, conservative, unlimited quota (secret handed over out of band). `manage_customer.py list` confirms the read path (status/risk/usage). **Correction:** my repeated "dormant until deploy" was wrong — code auto-deployed on push; it was dormant only until the migrations landed, which is now done. Runbook + infra page corrected. Reminder still open: a Neon owner credential leaked to the terminal earlier (apply_schema echoes the DSN) — rotate/decommission the legacy Neon project.

## [2026-08-10] fix | Six defects from [niko]'s live connector test — grants, owner identity, alert delivery, margin freshness
attributed_to: [niko, claude-agent]   belongs_to: [mcp-server, paid-connector-deploy, risk-guard]
[niko] ran the first end-to-end test against production (every read tool, both watchlist writes, journal write, profile loop) and reported six failures the 453-test suite could not catch. **Two shared one root cause:** `003_rls.sql` grants `mcp_viewer` an *enumerated* table list, so `010`/`011` (no grant block at all) and `015`/`016`/`017` (role-guarded grants that run in the BASE pass, before 003 creates the role → silent no-op, never re-appended) left `raw_twse_valuation`, `raw_twse_index`, `market_holidays`, `raw_twse_dividend`, `raw_finmind_*` and `lead_lag` unreadable — killing 5 valuation/dividend tools and degrading `session_state` to weekend-only. This is a **different trap** from the known 003-blanket-REVOKE one: that strips *write* grants, this is about role *creation* order and costs *read* grants. Fixed by `sql/024` (single backfill, re-appended after 003, absent from the base list on purpose) + `apply_delta.py` now **reads privileges back** and fails the run if they didn't land. **Owner identity:** `set_my_risk_profile` was inert because the URL-secret mount never set `current_customer` and the OAuth `"owner"` subject was special-cased out — `sql/025` reserves `owner` as a `customers` id (secret_hash `'-'`, never a valid sha256, so `authenticate()` can't match it) and the auth gate names the subject; metering unchanged. **Alerts all `pushed:false`:** the token-less Zeabur `cron` (deliberate, anti-double-buzz) records the row first, then the token-holding GH Actions run hits the same-day de-dup and returns without sending — `flush_undelivered` only sweeps `critical`, so softer alerts were lost outright; `_emit` now retries when the colliding row is unpushed. **Margin blind every day:** `build_metrics` demanded a balance dated exactly `as_of`, but TWSE publishes 融資融券 *after* the 16:30 harvest, so the condition was unsatisfiable — now bounded to `MARGIN_MAX_LAG_SESSIONS=3` counted in *trading sessions* (weekends/CNY aren't stalls), `_session_lag` returns None not 0 when unmeasurable, `margin_as_of` surfaced in the subitem inputs. **`w_remove`** now distinguishes already-archived (`ok:true`) from never-listed (`ok:false`), matching its docstring. 19 new tests; suite 472 pass, focused ruff clean (db_v2's 48 are pre-existing, unchanged). **Blocked:** #1/#2/#5 need `apply_delta.py` run against the Zeabur owner DSN — code alone changes nothing. Decision: [2026-08-10-live-connector-defects](decisions/2026-08-10-live-connector-defects.md).

## [2026-08-10] fix | The three deferred review items — trial lockout, 402-on-blip, billing retry storm
attributed_to: [niko, claude-agent]   belongs_to: [mcp-server, commercial-productization]
[niko] cleared the three items the six-defect pass deliberately left open. **`trial` was a lockout:** `VALID_STATUSES` advertised it while `authenticate`, the read gate and the refresh check all compared against `STATUS_ACTIVE` alone, so setting it denied everything with 402 — a status that reads as valid and behaves as suspended. New `USABLE_STATUSES = {active, trial}` is the single thing all three consult; `manage_customer.py trial <ref>` makes it settable so the status is real rather than decorative; a test asserts every member of `VALID_STATUSES` is classified, which is exactly the drift that caused it. **A DB blip read as an unpaid account:** `customers.get`/`get_by_email` swallowed exceptions into `None`, which also means "no such customer", so a Postgres hiccup made the gate answer 402 `account_inactive` — telling a paying customer their subscription had lapsed. Both now raise `LookupUnavailable` and each caller chooses: read gate → **503** (transient to every client's retry logic), refresh → still **closed** (a refresh mints a fresh 90-day credential, so declining costs a retry while issuing wrongly costs three months; live sessions keep an access token that outlives a short outage). **Billing retried forever on a bogus id:** `_apply_billing` read `custom_data.customer_id` without confirming it, so a stale/typo'd value skipped the email fallback, updated zero rows and returned 500 — which Lemon Squeezy retries indefinitely while the customer the email *would* have matched is never activated. Resolution now confirms the id and treats an unconfirmable one as no id; the three outcomes are separated (resolved → write, unknown → 200 ack once, store unreachable → 500 retry). Also caught a pre-existing test asserting 500 via the wrong path once `get` began raising. 14 new tests; suite 486 pass, focused ruff clean. **Still open by choice:** LS checkout custom fields are URL-settable, so a known `cust_…` id could be used to suspend someone else — hard to reach (non-enumerable ids), and binding to subscriber email would break mismatched-email checkouts. Decision: [2026-08-10-live-connector-defects](decisions/2026-08-10-live-connector-defects.md#follow-up-same-day-the-three-deferred-items).

## [2026-08-10] fix+audit | System sweep: sc_capabilities had silently dropped 15 of 48 tools; stale counts corrected
attributed_to: [niko, claude-agent]   belongs_to: [mcp-server, system-architecture]
[niko] asked for a full check-and-complete pass after the nine defect fixes. **Audited the invariants CLAUDE.md calls load-bearing, and they hold:** the `src/quant` ↔ `mcp_server/api/quant` mirrors differ by exactly the one documented `MCP_DATABASE_URL` line (no drift); nothing under `mcp_server/` imports polars; every external import in the deployed tree is declared in `mcp_server/requirements.txt`; the root image still carries `mcp_server/api/` and `docs/theses/`; every deployed module imports cleanly; no orphan `sql/` file is missing from `apply_schema.py`; and — the point of the exercise — **all 32 relations the server reads are now granted**, confirming `sql/024` closed the gap completely rather than partially. **One real defect found:** `sc_capabilities` listed only **33 of 48** registered tools, having never been updated as tools were added — missing every quant tool past `q_backtest_compound` (`q_valuation`, `q_regime`, `q_lead_lag`, `q_factor_*`, `q_pca_decompose`, `q_cointegration_pair`, `q_quality_score`, `q_index_history`), the whole onboarding/profile layer (`start_here`, `my_profile`, `set_my_risk_profile`, `investing_principles`), `ticker_lookup` (the usual first step in any chain) and `sc_capabilities` itself. Since the server `instructions` call it "the full technical map", a tool absent from it is one the model has been told does not exist — a silent capability loss with no error anywhere. All 15 added, and `tests/test_capabilities.py` now asserts the map and the live FastMCP registry match **in both directions** (a stale entry sends the model at a name that will fail). **Also fixed a bug introduced in the previous commit:** `apply_delta.py`'s new privilege read-back called `has_table_privilege`, which *raises* on an unknown role or table rather than returning false — so verifying a database missing any 024 table (which 024 itself skips) would crash the script instead of reporting; now guarded by `pg_roles` and `to_regclass` checks. Corrected stale figures across CLAUDE.md/README/wiki: tool count 44/~45 → **48**, test count 211/326 → **489**, index.py ~2200 → ~2900 lines, repo-wide ruff debt 344 → **188**. CLAUDE.md now states the two-edit rule for adding a tool. Suite 489 pass, focused ruff clean.

## [2026-08-11] ops | Production hardening: CI gate, nightly DB backup + restore runbook, Telegram token preflight
attributed_to: [niko, claude-agent]   belongs_to: [system-architecture, infrastructure-accounts]
[niko] gave a free mandate to "make this a complete production system". Live-verified production first via the connected MCP: `q_valuation` still `permission denied`, `session_state` still `weekend_only`, `my_profile` still identity-less — confirming migrations 024/025 are NOT yet applied and PR #1 is unmerged; today's risk light computed green with margin still data_missing (old code), as predicted. Three gaps closed, all in `.github/workflows/`: **(1) CI existed nowhere** — the 489-test suite ran only on developer machines while `main` auto-deploys to the Zeabur `mcp` service on every push, so an untested commit was an untested production deploy. New `ci.yml` runs pytest on every PR and main push + changed-files-only ruff (repo convention: the 188-error debt in db_v2.py must not block unrelated work). Limit stated in the file: Zeabur deploys regardless — CI only gates a MERGE, and only once branch protection on main requires the `test` check; [niko] must flip that switch. **(2) No database backup existed** — Zeabur's prebuilt Postgres ships none, and the Neon "rollback" froze at the 2026-07-31 cutover; with customers/billing now in this DB, volume loss = total loss. New `db_backup.yml`: nightly 18:30 Taipei pg_dump (custom format, `--no-owner --no-privileges` because grants are code here — `apply_schema.py --rls` + 024 recreate them deterministically), TOC verified with `pg_restore --list` incl. key tables, 5-day artifact retention (Actions quota is 500MB free-tier; longer retention → object storage, not bigger artifacts), Telegram failure alert. Restore runbook in [db-backups](topics/db-backups.md) — including the note that grants/ownership deliberately do NOT restore from the dump. **(3) A bad TELEGRAM_TOKEN was invisible** — send() fails soft, and the notify-on-failure steps depend on the same token, so the channel that would report the breakage IS the broken channel; this was the one branch of the pushed:false incident unverifiable from code. `getMe` preflight added to daily_harvest + riskguard_premarket (continue-on-error: a Telegram blip must not cost the harvest; the warning annotation is the deliverable). Stacked PR off the defect-fix branch; PR #1 marked ready for review.

## [2026-08-11] feat | /health?deep=1 — the DB probe the permission-denied outage needed
attributed_to: [claude-agent]   belongs_to: [mcp-server, system-architecture]
The 2026-08-10 outage was invisible from outside: `/health` answered ok while every valuation/dividend tool failed. `/health?deep=1` now proves the database answers (503 when it doesn't), with a 10s result cache because the endpoint is PUBLIC — N requests per window cost one query, so it can't be used as a query amplifier against the max-3 pool. Deliberate split: Zeabur's restart-on-unhealthy probe should keep using the shallow form (restarting the server doesn't fix a down Postgres, it just flaps); an uptime monitor should watch `?deep=1`. 4 tests; suite 493 pass.

## [2026-08-11] feat | Operator console — one nav frame over five orphaned web surfaces; system map generated from the live registry
attributed_to: [niko, claude-agent]   belongs_to: [mcp-server, system-architecture]
[niko]: "the dashboard now is hard to navigate and find. make it like a saas system." Root cause was structural, not cosmetic: the web surfaces were **five unrelated full HTML documents at three path prefixes** (`/d/` dashboard, `/g/` 3D graph, `/t/` tickers, `/h/` home, `/d/…/t/<ticker>`), each with its own header and **no links to the others** — so reaching any of them meant already knowing its URL, and no page existed that said what the system contained. Fixed with a console shell rather than a redesign: `console.py` holds `NAV` as the single source of information architecture, `shell()` for pages the console owns, and `inject_nav()` to retrofit the same bar onto documents `src.dashboard.*` pre-renders on the harvester side (which cannot import server-side modules — the deployment split). **Load-bearing detail: every nav link is relative** (`./graph`, not `/d/<token>/graph`) — that is what lets a static file generated hours earlier by a process with no knowledge of the bearer token link correctly once served under the token prefix; the alternative was threading the token through every generator and rebuilding on rotation. Two new pages built from live state: `/d/<token>/` **overview** (pipeline health, row counts, latest session per table, plus a tile per surface — the page that was missing) and `/d/<token>/system` **system map**, whose tool families are generated from the **same registry the MCP server serves**, so it cannot drift the way the hand-maintained `sc_capabilities` silently did to 33 of 48. Overview fails soft to "pipeline unreachable" rather than 500 — a console that dies when Postgres blinks is worse than one that says so. Old prefixes still resolve for bookmarks and the Telegram bot's links; `/d/<token>/home` 307s to the new overview. Palette follows the Taiwan exchange convention (red up, green down) — a Western scheme reads inverted to this system's only audience. Verified end-to-end through the real ASGI stack: all six routes render, nav injects into the pre-rendered flow dashboard and the 1.4MB 3D graph alike, and a wrong token still 404s. 13 new tests; suite 506 pass, focused ruff clean.
