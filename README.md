# alphatecx v2

Taiwan equity (TWSE/TPEX) supply-chain and institutional-flow intelligence.

A scheduled Python harvester pulls TWSE, MOPS, and FinMind data into Neon Postgres. A FastMCP server on Vercel exposes 44 read-only MCP tools over pre-computed materialized views, so a Claude agent queries a warm database instead of rate-limited exchange APIs. Telegram carries alerts; static dashboards and a Next.js chat app are the human surfaces.

The investment frame is a 4-pillar Taiwan AI supply chain map (semiconductor, equipment, infrastructure, energy) — see [`docs/wiki/topics/taiwan-ai-supply-chain.md`](docs/wiki/topics/taiwan-ai-supply-chain.md).

---

## Layout

| Path | What runs there |
|---|---|
| `src/` | Harvesters, quant compute, cron briefs, dashboard builders — GitHub Actions |
| `mcp_server/api/` | FastMCP tools + FastAPI routes — Vercel (Root Directory is `mcp_server/`) |
| `riskguard/` | Risk Guard fetch/write/cron half — GitHub Actions |
| `sql/` | Numbered migrations, applied by `apply_schema.py` |
| `web/` | Next.js 16 + assistant-ui chat client (separate app, pnpm + biome) |
| `skills/` | Claude Skills for ticker research and entry timing |
| `docs/wiki/` | Project memory — decisions, stakeholders, topics. See `AGENTS.md` |
| `docs/theses/`, `docs/journals/`, `docs/digests/` | Agent-written analysis output |

`CLAUDE.md` is the working guide for agents: commands, architecture, and the non-obvious constraints (deployment split, import paths, Neon/CI quirks).

## Quick start

```bash
pip install -r requirements.txt        # harvester deps
pytest -q                              # 191 tests, no network or DB needed

# local MCP server (needs mcp_server/requirements.txt + uvicorn; pin mcp<2)
cd mcp_server && MCP_BEARER_TOKEN=devtoken uvicorn api.index:app --port 8787
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL` at minimum. `TELEGRAM_*` enables alerts; `FUGLE_API_KEY` and `FINMIND_TOKEN` are optional — the code self-skips when they're absent.

## How data gets in

`.github/workflows/daily_harvest.yml` runs at 16:30 Taipei on weekdays: TWSE institutional flow (T86), foreign holdings, margin balance, monthly revenue, OHLCV, news, FinMind enrichment, then matview refresh and quant signal compute. Downstream steps (briefs, dashboards, correlation snapshot) are `continue-on-error` — the data is already committed, the rest is presentation.

`news_harvest.yml` runs the news feeds on a separate, more frequent cadence.

## MCP surface

Tools are prefixed by domain: `sc_` supply chain, `raw_` raw drill-down, `q_` quant, `n_` news, `d_` digests, `w_` watchlist, `u_` universe, `rg_` risk guard. Call `sc_capabilities` for the live catalog — it is the source of truth, not this file.

Auth is URL-as-secret: the server mounts at `/mcp/<MCP_BEARER_TOKEN>`, and the same token gates the graph (`/g/`), dashboard (`/d/`), hub (`/h/`), and ticker (`/t/`) routes. Only `/` and `/health` are public.

## Status

Live and running daily.

**Risk Guard Phase 1** is built — a post-close risk system (market risk light, stop-loss alerts, T+2 settlement check) whose enforced non-goal is that it never emits a buy signal. See [`docs/wiki/topics/risk-guard.md`](docs/wiki/topics/risk-guard.md).

**Postgres is migrating** from Neon to a self-hosted Zeabur instance. Data is restored and verified; cutover is not complete, so `.env`, CI secrets, and the deployment still point at Neon. See [`docs/wiki/decisions/2026-07-31-migrate-neon-to-zeabur.md`](docs/wiki/decisions/2026-07-31-migrate-neon-to-zeabur.md) — it also records the open TLS exposure on the Zeabur endpoint.
