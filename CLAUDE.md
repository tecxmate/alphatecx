# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent contract

@AGENTS.md

The wiki under `docs/wiki/` is the project's memory (decisions, stakeholders, topics). `AGENTS.md` above is binding — maintain it on every meaningful turn.

## What this is

**alphatecx v2** — Taiwan equity (TWSE/TPEX) supply-chain & flow intelligence. A scheduled Python harvester writes TWSE/MOPS/FinMind data into a self-hosted Zeabur Postgres (was Neon until 2026-07-31); a FastMCP server on Zeabur (was Vercel until 2026-07-31) exposes ~45 read-only MCP tools over pre-computed views; Telegram carries alerts; a Next.js chat app and static dashboards are the human surfaces.

`README.md` is the human-facing overview; this file is the agent-facing one.

## Commands

```bash
.venv/bin/python -m pytest -q               # full suite (326 tests, no network/DB needed)
pytest tests/test_flow_leaders.py::test_x   # single test
ruff check <changed files>                  # see lint convention below

python -m src.harvester.daily               # nightly pipeline (what CI runs)
python -m src.news.harvest                  # news feeds only, one batch
python -m src.news.watch --once             # news poller, one cycle (loops without --once)
python -m src.cron.brief --mode post_close  # pre_market | intraday | post_close
python -m src.backfill.run --days 90 --only t86
python -m src.dashboard.build               # regenerates static/ dashboard
python -m riskguard.pipeline --mode post_close
python apply_schema.py [--rls]              # apply sql/ to whatever DATABASE_URL points at

# local MCP server — run from mcp_server/, NOT mcp_server/api/
# api.app = MCP + Telegram bot composed (what Zeabur runs); api.index = MCP only
cd mcp_server && MCP_BEARER_TOKEN=devtoken uvicorn api.app:app --port 8787
docker build -t alphatecx-mcp . && docker run -p 8080:8080 -e MCP_BEARER_TOKEN=devtoken alphatecx-mcp

# news poller image — build context is the REPO ROOT, not mcp_server/
docker build -f Dockerfile.newswatch -t alphatecx-news-watch . && docker run --env-file .env alphatecx-news-watch
cd web && pnpm dev                          # Next.js chat (pnpm lint = biome)
```

**`pytest` needs the venv.** `tests/test_news_watch.py` imports `src/news/harvest.py`, which pulls in feedparser and — via `harvester/loader` — polars. A Homebrew `python3` is PEP-668 externally-managed, so neither installs there and bare `pytest -q` fails at collection. Bare `python3` only ever worked because nothing under `src/` had tests. `.pre-commit-config.yaml` prefers `.venv/bin/python` and falls back to `python3`.

Local-server gotchas, all verified by hitting `/health`:
- `uvicorn` and the `mcp<2` ceiling are now both in `mcp_server/requirements.txt` — the Zeabur image builds from that file, so it had to stop depending on what happened to be installed. Root `requirements.txt` still has neither.
- **mcp 2.0.0 removed `mcp.server.fastmcp`**, which `index.py` imports; that is what the ceiling is defending. Lift it only when the server is ported.
- The MCP endpoint is `/mcp/<token>/` **with the trailing slash** — `/mcp/<token>` 307-redirects and `/mcp/<token>/mcp` is a 404.
- `index.py` refuses to start without `MCP_BEARER_TOKEN` (an empty token would make the URL-as-secret mount path silently 404 everything).

**Lint convention:** full-repo `ruff check .` fails on pre-existing debt (344 errors). The working gate is focused ruff on files you touched, plus `pytest -q`. Don't open a repo-wide lint cleanup unless asked.

`.pre-commit-config.yaml` enforces exactly that gate — `pre-commit` passes the ruff hook only *staged* files, so the debt never blocks you. Run `pre-commit install` once per clone. `ruff-format` is deliberately absent: it would reformat 66 of 84 files, arriving one file at a time and burying real diffs. Enabling it needs a repo-wide format commit first.

## Architecture

### The deployment split (read this before moving any file)

The Docker build context is `mcp_server/` (it was Vercel's Root Directory before the 2026-07-31 move, and the `Dockerfile` deliberately kept the same boundary). Only what lives under that folder is in the deployed image — a repo-root package **cannot** be imported by an MCP tool. Every apparent duplication follows from that:

| Runs where | Path | Contains |
|---|---|---|
| GitHub Actions (network, DB writes) | `src/`, `riskguard/`, `scripts/` | harvesters, quant compute, cron, dashboards |
| Zeabur + local pytest (DB reads, pure logic) | `mcp_server/api/` | MCP tools, `quant/`, `rg/` |

- `src/quant/*.py` and `mcp_server/api/quant/*.py` are **mirrored copies**, currently differing only in one line (server side adds an `MCP_DATABASE_URL` fallback). Edit both or they drift. Container hosting means this constraint is now self-imposed rather than forced — de-duplicating is possible but is its own piece of work, not a side effect of the move.
- `riskguard/` = impure (fetch, write, cron). `mcp_server/api/rg/` = pure decision functions over plain dicts + the read layer. The purity split exists so `riskguard.replay` can re-derive historical risk lights deterministically.
- **Two requirements files:** root `requirements.txt` (polars, feedparser, plotly) is harvester-only. `mcp_server/requirements.txt` (mcp, fastapi, uvicorn, psycopg, numpy — no polars) is what ships. Importing polars from an MCP tool breaks the deploy.
- `api/app.py` is the **deployed entrypoint** and exists only because Zeabur runs one process: Vercel served `api/index.py` and `api/bot.py` as two functions with `vercel.json` rewrites steering `/bot/*`. `app.py` merges the bot's routes into the MCP app. `index.py` and `bot.py` stay independently runnable so the Vercel project remains a rollback target — don't collapse them.

### Import paths

`pyproject.toml` sets `pythonpath = [".", "mcp_server/api"]`. That's why `mcp_server/api/index.py` does bare `import db_v2`, and why several modules carry:

```python
try:
    from security import ...
except ModuleNotFoundError:      # package import path used by local tests
    from .security import ...
```

Deliberate — don't "fix" it into one form.

### MCP server (`mcp_server/api/index.py`, ~2200 lines)

FastMCP instance mounted at `/mcp/{MCP_BEARER_TOKEN}` inside a FastAPI app. Tool prefixes: `sc_` supply chain, `raw_` raw drill-down, `q_` quant, `n_` news, `d_` digests, `w_` watchlist, `u_` universe, `rg_` risk guard. Every tool response goes through `_stamp()` adding `_source` / `_as_of` / `_freshness`; keep that.

**Auth is URL-as-secret.** `security.py` gates `/mcp`, `/g`, `/d`, `/h`, `/t` on the token path segment; only `/` and `/health` are public. Any SQL identifier interpolation must go through `query_safety.safe_flow_col` — the whitelist is the injection defense.

Dates are `Asia/Taipei`, not UTC. TWSE publishes on Taipei wall-clock; UTC mislabels `_as_of` for ~8h/day.

### Zeabur services (all four in project `alphatecx`)

| Service | Runs | Built from | Notes |
|---|---|---|---|
| `postgresql` | the database | Zeabur prebuilt | reachable internally at `postgresql.zeabur.internal:5432` |
| `mcp` | FastMCP + bot webhook | `mcp_server/Dockerfile` | `alphatecx-mcp.zeabur.app` |
| `cron` | post-close chain, Risk Guard pre-market | `Dockerfile` (repo root) | supercronic, `TZ=Asia/Taipei` |
| `worker` | `src/news/watch.py` poller | `Dockerfile.newswatch` | continuous, 180s |

GitHub Actions still runs the same schedules in parallel — deliberate, and safe because every
writer upserts on composite PKs. **`TELEGRAM_TOKEN` is intentionally unset on `cron`**: the
message layer is the one thing a double run duplicates. The cost is that a `cron` failure is
silent, so GH Actions remains the path that alerts on failure. See
[`docs/wiki/decisions/2026-07-31-scheduled-work-on-zeabur.md`](docs/wiki/decisions/2026-07-31-scheduled-work-on-zeabur.md).

Two non-obvious build inputs, both of which fail *silently* if dropped: `riskguard/` imports
`mcp_server.api.rg`, so the root image must carry `mcp_server/api/`; and `docs/theses/` is a
runtime input read by `brief.py` and `thesis_status.py`, not documentation.

`zbpack-v2` pre-processes the Dockerfile and has been observed replacing the entrypoint with an
auto-detected one. After any deploy, check `zeabur service exec ... -- cat /proc/1/cmdline`
rather than assuming your `CMD` survived.

### Data layer

- `sql/NNN_*.sql` migrations applied by `apply_schema.py`, which has a **hardcoded file list**. A new `sql/` file does nothing until you add it there. `003` and `014` sit in the `--rls` branch, not the default list, because they GRANT to `mcp_viewer` and fail where that role doesn't exist.
- `db_v2.py` uses a psycopg3 `ConnectionPool` with a per-connection `SET search_path`. The rationale was Neon's pooler (it clears session settings on reset and rejects `options=-csearch_path` at startup); harmless against Zeabur, left in place.
- Reads target materialized views (`view_sector_momentum`, `view_ticker_momentum`, `view_latest_signals`). New MCP-read tables need a `mcp_viewer` GRANT + RLS policy (see `sql/003_rls.sql`).
- **Two independent grant traps, both silent.** (1) 003 *ends* with a blanket `REVOKE INSERT, UPDATE, DELETE`, so any **write** grant made before it is stripped — that's why 018/020/021/022/023 are re-appended after 003. (2) 003 grants SELECT on an **enumerated list**, and a later migration's own grant is typically wrapped in `IF EXISTS (… rolname = 'mcp_viewer')` — which is *false* during the base pass, before 003 creates the role, so it no-ops and, not being re-appended, never lands. That cost **read** access to everything 010/011/015/016/017 created until `sql/024` backfilled it (2026-08-10). Both traps look identical live: a fully-populated table the server answers `permission denied` on. Put new read grants in `024`, not in the feature migration, and confirm with `apply_delta.py`, which now reads the privileges back and fails if they didn't land.

### News ingestion runs on two cadences

`news_harvest.yml` (6 slots/day) is the backstop. `src/news/watch.py` is a long-running poller — its own Zeabur service, built from `Dockerfile.newswatch`, polling every feed on `NEWS_POLL_SECONDS` (default 180) and pushing watchlist matches to Telegram. GitHub Actions cannot do this job: scheduled workflows floor at 5 minutes and are routinely queue-delayed past it. Both paths share `harvest._fetch_feed` / `_upsert` and are idempotent on the canonical-URL PK, so the overlap is free.

Things that look like details but are load-bearing — see [`docs/wiki/decisions/2026-07-31-near-realtime-news-poller.md`](docs/wiki/decisions/2026-07-31-near-realtime-news-poller.md):
- **Conditional GET is not politeness.** Without a 304 the poller re-upserts every unchanged row 480×/day, and `ON CONFLICT DO UPDATE` writes a new row version even when the value is identical. The ETag cache is in-memory on purpose; a restart costs one full fetch.
- `_fetch_feed` returns `None` for 304, `[]` for failure. `raise_for_status()` does **not** raise on 3xx and a 304 body is empty, so dropping that check logs the healthy path as an unparseable feed.
- **A fresh DB insert is not new news.** The first cycle primes (ingests, announces nothing) because on cold start every article is a fresh insert, and a 6h recency gate drops items feeds re-surface.
- Alert matching needs `watchlist.company_name` (English, bot-written) **and** `dim_ticker.company_name` (Chinese, TWSE's). Half the feeds are zh-Hant; one alone silently under-alerts.
- It writes `ingestion_log` under `source='news_watch'`, never `'news_harvest'` — sharing the key would bury the cron's own staleness signal in `n_source_status`.
- Point it at `postgresql.zeabur.internal:5432`. It holds **write** credentials and that Postgres has TLS disabled.

Deliberate non-goal, same as Risk Guard: it never emits a buy signal. And it speeds up news only — T86 publishes once a day near 15:00, so institutional-flow signals are structurally end-of-day no matter what transport is used.

### Scheduling (GitHub Actions, not Vercel Cron)

`daily_harvest.yml` (16:30 Taipei, weekdays) runs the harvest then a chain of `continue-on-error: true` steps — brief, lead-lag, thesis heartbeat, dashboards, correlation snapshot. Failure isolation is intentional: data is already in the DB, the downstream steps are presentation.

`riskguard_premarket.yml` (08:30 Taipei) restates the risk light. The Risk Guard post-close step inside `daily_harvest.yml` is deliberately **not** `continue-on-error` — a silent failure there is a stop-loss alert that never fired.

One non-obvious workflow requirement, which produces a **hang rather than an error** if dropped: all three workflows append `&gssencmode=disable` to `DATABASE_URL` (runner libpq stalls on GSS negotiation). Note the `&` — **the `DATABASE_URL` secret must carry a query string** or the suffix lands inside the database name. It currently ends `?sslmode=disable`, which is also what Zeabur requires: that server has no TLS at all.

The `/etc/hosts` IPv4-pin step was removed at the Zeabur cutover — it existed because the runner's IPv6 path to Neon was dead, and Zeabur's host is already a literal IPv4.

`mcp_server/api/static/*` (dashboard HTML/JS, `graph_snapshot.json`, `ticker/`) is **generated and committed back to main** by that job as `chore(graph): daily refresh [skip ci]`. Never hand-edit; regenerate via the `src.dashboard.*` / `src.quant.correlation_snapshot` entrypoints.

### Other surfaces

- `web/` — separate Next.js 16 + assistant-ui app, pnpm, **biome** (not eslint), outside the Python test suite. Talks to the MCP over `MCP_SERVER_URL` including the secret token.
- `skills/tw-equity-alpha/` — version-controlled mirror of a live Claude Desktop skill; the app reads its own copy, so edits must be copied across.
- `docs/theses/`, `docs/digests/`, `docs/journals/` — agent-written analysis output, not code.

## In flight

Both of these are uncommitted working-tree state. Check `git status` before assuming.

**Risk Guard Phase 1 — built.** `RISK_GUARD_PRD.md` (Chinese, v1.1) is the spec; M1 risk light, M2 stop alerts, M2b settlement check are implemented across `riskguard/` + `mcp_server/api/rg/` + `sql/018_riskguard.sql`, with 5 `rg_` MCP tools, a Telegram bot command surface in `bot.py`, and `tests/test_rg_*.py`. Enforced non-goal: it never emits a buy signal — the checklist's best verdict is "no reason stopping you." See [`docs/wiki/topics/risk-guard.md`](docs/wiki/topics/risk-guard.md) and the Phase 1 decision page.

**Postgres migrated Neon → self-hosted Zeabur (2026-07-31), then the MCP server followed it (same day).** Data restored and verified; `.env` and the GitHub Actions `DATABASE_URL` secret point at Zeabur. The old "switch Vercel's env off Neon" step was **dropped rather than done** — the server moved to Zeabur instead, so it now reaches Postgres at `postgresql.zeabur.internal:5432` over the project's private network. Read [`docs/wiki/decisions/2026-07-31-migrate-neon-to-zeabur.md`](docs/wiki/decisions/2026-07-31-migrate-neon-to-zeabur.md) and [`2026-07-31-mcp-server-vercel-to-zeabur.md`](docs/wiki/decisions/2026-07-31-mcp-server-vercel-to-zeabur.md) before touching anything DB- or deploy-shaped.

Live at `https://alphatecx-mcp.zeabur.app`; Vercel and Neon both stay up as rollback. Consequence worth knowing: **that private path is the only reason the missing TLS is tolerable.** Zeabur's Postgres has TLS disabled outright (`sslmode=require` is rejected), so any client reaching it over `8.209.197.81:32046` — the GitHub Actions harvesters still do — sends credentials across the public internet in cleartext. Collation also changed `C.UTF-8` → `en_US.utf8`, so text `ORDER BY` shifts (not corruption).
