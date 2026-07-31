# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent contract

@AGENTS.md

The wiki under `docs/wiki/` is the project's memory (decisions, stakeholders, topics). `AGENTS.md` above is binding — maintain it on every meaningful turn.

## What this is

**alphatecx v2** — Taiwan equity (TWSE/TPEX) supply-chain & flow intelligence. A scheduled Python harvester writes TWSE/MOPS/FinMind data into a self-hosted Zeabur Postgres (was Neon until 2026-07-31); a FastMCP server on Vercel exposes ~45 read-only MCP tools over pre-computed views; Telegram carries alerts; a Next.js chat app and static dashboards are the human surfaces.

`README.md` is the human-facing overview; this file is the agent-facing one.

## Commands

```bash
pytest -q                                   # full suite (191 tests, no network/DB needed)
pytest tests/test_flow_leaders.py::test_x   # single test
ruff check <changed files>                  # see lint convention below

python -m src.harvester.daily               # nightly pipeline (what CI runs)
python -m src.news.harvest                  # news feeds only
python -m src.cron.brief --mode post_close  # pre_market | intraday | post_close
python -m src.backfill.run --days 90 --only t86
python -m src.dashboard.build               # regenerates static/ dashboard
python -m riskguard.pipeline --mode post_close
python apply_schema.py [--rls]              # apply sql/ to whatever DATABASE_URL points at

# local MCP server — run from mcp_server/, NOT mcp_server/api/
cd mcp_server && MCP_BEARER_TOKEN=devtoken uvicorn api.index:app --port 8787
cd web && pnpm dev                          # Next.js chat (pnpm lint = biome)
```

Local-server gotchas, all verified by hitting `/health`:
- `uvicorn` is in neither requirements file — install it separately.
- `requirements.txt` pins `mcp>=1.2.0`, but **mcp 2.0.0 removed `mcp.server.fastmcp`**. A fresh unpinned install fails at import. Use `mcp<2` until the server is ported.
- `index.py` refuses to start without `MCP_BEARER_TOKEN` (an empty token would make the URL-as-secret mount path silently 404 everything).

**Lint convention:** full-repo `ruff check .` fails on pre-existing debt (344 errors). The working gate is focused ruff on files you touched, plus `pytest -q`. Don't open a repo-wide lint cleanup unless asked.

`.pre-commit-config.yaml` enforces exactly that gate — `pre-commit` passes the ruff hook only *staged* files, so the debt never blocks you. Run `pre-commit install` once per clone. `ruff-format` is deliberately absent: it would reformat 66 of 84 files, arriving one file at a time and burying real diffs. Enabling it needs a repo-wide format commit first.

## Architecture

### The deployment split (read this before moving any file)

Vercel's Root Directory is `mcp_server/`. Only what lives under that folder is in the deployed bundle — a repo-root package **cannot** be imported by an MCP tool. Every apparent duplication follows from that:

| Runs where | Path | Contains |
|---|---|---|
| GitHub Actions (network, DB writes) | `src/`, `riskguard/`, `scripts/` | harvesters, quant compute, cron, dashboards |
| Vercel + local pytest (DB reads, pure logic) | `mcp_server/api/` | MCP tools, `quant/`, `rg/` |

- `src/quant/*.py` and `mcp_server/api/quant/*.py` are **mirrored copies**, currently differing only in one line (server side adds an `MCP_DATABASE_URL` fallback). Edit both or they drift.
- `riskguard/` = impure (fetch, write, cron). `mcp_server/api/rg/` = pure decision functions over plain dicts + the read layer. The purity split exists so `riskguard.replay` can re-derive historical risk lights deterministically.
- **Two requirements files:** root `requirements.txt` (polars, feedparser, plotly) is harvester-only. `mcp_server/requirements.txt` (mcp, fastapi, psycopg, numpy — no polars) is what ships. Importing polars from an MCP tool breaks the deploy.

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

### Data layer

- `sql/NNN_*.sql` migrations applied by `apply_schema.py`, which has a **hardcoded file list**. A new `sql/` file does nothing until you add it there. `003` and `014` sit in the `--rls` branch, not the default list, because they GRANT to `mcp_viewer` and fail where that role doesn't exist.
- `db_v2.py` uses a psycopg3 `ConnectionPool` with a per-connection `SET search_path`. The rationale was Neon's pooler (it clears session settings on reset and rejects `options=-csearch_path` at startup); harmless against Zeabur, left in place.
- Reads target materialized views (`view_sector_momentum`, `view_ticker_momentum`, `view_latest_signals`). New MCP-read tables need a `mcp_viewer` GRANT + RLS policy (see `sql/003_rls.sql`).

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

**Postgres migrated Neon → self-hosted Zeabur (2026-07-31).** Data restored and verified; `.env` and the GitHub Actions `DATABASE_URL` secret now point at Zeabur. **One cutover step remains: the Vercel deployment's env vars still point at Neon** — the MCP server keeps reading the old database until they're switched. Neon stays live as rollback. Read [`docs/wiki/decisions/2026-07-31-migrate-neon-to-zeabur.md`](docs/wiki/decisions/2026-07-31-migrate-neon-to-zeabur.md) before touching anything DB-shaped. Still open: Zeabur has **TLS disabled** (`sslmode=require` is rejected, so credentials cross the public internet in cleartext — unmitigated), and collation changed `C.UTF-8` → `en_US.utf8`, so text `ORDER BY` shifts (not corruption).
