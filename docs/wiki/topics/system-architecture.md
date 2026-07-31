---
title: System Architecture (v2 Stateful Upgrade)
type: topic
slug: system-architecture
date: 2026-05-07
updated: 2026-07-31
belongs_to: [niko]
source: chat
status: active
tags: [architecture, neon, mcp, pipeline, github-actions]
related: [alphatecx, alphatecx-v1, taiwan-ai-supply-chain]
---

## Summary

The v2 architecture upgrades alphatecx from stateless per-query TWSE API calls to a systematic, scheduled data pipeline with a Neon (Postgres) backend. Claude's MCP reads pre-processed materialized views instead of raw APIs, enabling instant sector-level trend analysis.

## Architecture Overview

```
TWSE/TPEX/MOPS/FinMind ──→ GitHub Actions (Python + Polars) ──→ Neon (PostgreSQL)
                                (daily @ 16:30 CST)                   │
                                        │                             ├─ dim_supply_chain (static)
                                        │                             ├─ raw_twse_t86, holdings, margin,
                                        │                             │  revenue, ohlcv, news, finmind_*
                                        │                             ├─ rg_* (Risk Guard)
                                        │                             └─ view_sector_momentum /
                                        │                                view_ticker_momentum /
                                        │                                view_latest_signals
                                        │                                       │
                            Telegram ←──┤ (briefs, risk alerts)                  │
                            static/  ←──┘ (dashboard, graph, ticker pages,       │
                              │            committed back to main)               │
                              │                                                  │
                              └──→ Vercel (Root Directory = mcp_server/) ←────────┘
                                          │
                          ┌───────────────┼────────────────┐
                    FastMCP /mcp/<token>  │          /d/ /g/ /h/ /t/
                          │               │           (token-gated HTML)
                    Claude Desktop    web/ (Next.js chat)
```

**Deployment split.** Vercel's Root Directory is `mcp_server/`, so nothing at the repo root is in the deployed bundle. Code is therefore placed by *reachability*, not by taste: `src/` and `riskguard/` run on GitHub Actions (network + DB writes); `mcp_server/api/` runs on Vercel and in tests (DB reads + pure logic). `src/quant/` is mirrored into `mcp_server/api/quant/` for the same reason. See [risk-guard](risk-guard.md) for the case that forced this to be written down.

## Tech Stack

| Layer | Tool | Rationale |
|-------|------|-----------|
| Data Ingestion | GitHub Actions + Python (Polars) | Scheduled via `daily_harvest.yml`, idempotent upserts |
| Storage | Neon (PostgreSQL) — **migrating to self-hosted Zeabur** | Chosen over Supabase to reuse v1 pooler string and reduce friction. Data is restored and verified on Zeabur; cutover is pending, Neon remains the live store and the rollback. See [2026-07-31-migrate-neon-to-zeabur](../decisions/2026-07-31-migrate-neon-to-zeabur.md) |
| AI Bridge | Custom FastMCP Server (Python) | 7 specialized tools mounted at `/mcp/<secret>` endpoint |
| Alerting | Python `src/alerts/telegram.py` | Daily sector momentum summaries |

## Data Scope & Normalization

The system filters the massive TWSE/TPEX firehose down to **5 core datasets** that matter for the AI supply chain strategy:

1. **T86 (Institutional Flow)**: Daily net buying/selling by Foreign Investors (FINI), Investment Trusts, and Dealers.
2. **Holdings (MI_QFIIS)**: Foreign ownership percentages and shares outstanding.
3. **Margin**: Retail margin and short-selling balances.
4. **Monthly Revenue (MOPS)**: Standard MoM/YoY revenue growth.
5. **OHLCV**: Basic daily price and volume.

**Key Insight: Relative Accumulation Intensity**
Absolute volume (e.g., FINI buying 210M shares of Foxconn) shows where the weight of capital is moving, but normalizing it against the company's size (shares outstanding from the Holdings table) reveals the *relative intensity* of accumulation. For example, Foxconn seeing a 1.52% float accumulation vs Wistron seeing 1.40% shows similar intensity despite different absolute sizes.

## MCP Tools (v2)

The `alphatecx-v2` server exposes **44 tools** (as of 2026-07-31), organised by prefix:

| Prefix | Domain |
|---|---|
| `sc_` | Supply chain — sector/ticker momentum, node comparison, accumulation screen, the pillar map, capabilities, data status |
| `raw_` | Raw drill-down into historical flow/holdings |
| `q_` | Quant — screener, indicators, valuation, backtest, regime, quality, cointegration, PCA, factor alpha, lead-lag |
| `n_` | News — recent, per-ticker, source status |
| `d_` | Daily digests |
| `w_` / `u_` | Watchlist and universe |
| `rg_` | Risk Guard — status, positions, alerts, checklist, journal |
| *(unprefixed)* | `quote`, `ticker_lookup`, `price_history`, `session_state`, `scan_limit_board`, `flow_leaders_scan`, `dividend_calendar`, `market_flow_screener`, `beginner_stock_card` |

**Do not maintain a tool-by-tool list here** — it goes stale within weeks. `sc_capabilities` returns the live catalog and is the source of truth. Every tool response is wrapped by `_stamp()` with `_source` / `_as_of` / `_freshness`.

## Daily Systematic Workflow

| Time (CST) | Step | Actor |
|------------|------|-------|
| 15:30 | TWSE publishes T86 + MI_QFIIS | TWSE |
| 16:30 | Python harvester pulls APIs, cleans with Polars, upserts to Neon | GitHub Actions |
| 16:35 | Materialized views auto-refresh | Python loader |
| 16:40 | Telegram summary alert sent | Python bot |
| Anytime | Query pre-processed views via MCP tools in Claude | Niko + Claude |

## History

- 2026-05-07: Upgraded architecture to Neon Postgres & FastMCP. Documented 5-tier data scope and relative accumulation insight. [antigravity-agent]
- 2026-05-07: Architecture ingested from Gemini chat. Proposed by [gemini-agent], requirements from [niko].
- 2026-05-11: Removed the unused tracked `supabase/` CLI config directory after confirming runtime code uses Neon/Postgres directly. [niko, antigravity-agent]
- 2026-05-11: Local smoke testing verified `/health`, dashboard, ticker pages, graph rendering, and invalid-token rejection. Environment quirk: avoid `source .env` in zsh unless values are shell-quoted; Python entrypoints already load `.env` via `python-dotenv`. [antigravity-agent]
- 2026-05-11: Added a token-protected web hub at `/h/{token}/` and `/d/{token}/home` so dashboard, graph, graph artifacts, health, MCP endpoint, and ticker pages are linked from one entrypoint. [niko, antigravity-agent]
- 2026-05-11: Began Bloomberg-lite frontend redesign with a shared dense terminal-style design system, light/dark theme toggle, and mobile handling for tabs, tables, ticker charts, and graph panels. [niko, antigravity-agent]
- 2026-05-11: Graph viewer navigation now treats Discovery candidates as a first-level tab and adds a Tracked tickers tab with client-rendered inline classification editing, preserving initial page weight. [niko, antigravity-agent]
- 2026-05-11: Tracked tickers tab changed to lazy search-only rendering with 20 rows per page, and graph interaction hints now display only on Plotly graph tabs. [niko, antigravity-agent]
- 2026-05-11: Ticker management moved from the graph viewer to a dedicated Home-linked `/t/{token}/` directory. The page renders 20 rows by default, supports search/paging, keeps inline pillar/node edits, and stores user folders/lists in `dim_ticker.tags`. [niko, antigravity-agent]
- 2026-05-13: Go-to-market note: Claude Desktop/iOS remains the simplest MCP customer install path, while ChatGPT distribution should be planned as a remote MCP/app integration with workspace/admin/developer-mode requirements or via a custom OpenAI API chat product. [niko, antigravity-agent]
- 2026-07-05: Added `market_flow_screener` for all-market TWSE/TPEX institutional-flow discovery outside the AI classification, and expanded `q_screener` with below-threshold filters plus an `all_with_signals` mode. Full-market technical screening remains bounded by which tickers have OHLCV-derived signal rows. [niko, codex-agent]
- 2026-07-31: Doc sweep. The MCP tool section still listed 9 tools against a live surface of 44 — replaced with the prefix taxonomy and a standing instruction to treat `sc_capabilities` as the catalog rather than re-enumerating here. Diagram extended with the Vercel/dashboard/web-frontend and Risk Guard branches, and the deployment-split rule (Vercel Root Directory = `mcp_server/`) written down explicitly for the first time. Storage row flagged for the in-progress Neon → Zeabur migration. [niko, antigravity-agent]
