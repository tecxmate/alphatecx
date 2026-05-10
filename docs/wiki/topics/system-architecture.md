---
title: System Architecture (v2 Stateful Upgrade)
type: topic
slug: system-architecture
date: 2026-05-07
updated: 2026-05-11
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
TWSE/TPEX APIs ──→ GitHub Actions (Python + Polars) ──→ Neon (PostgreSQL)
                         (daily @ 16:30 CST)                    │
                                                                 ├─ dim_supply_chain (static)
                                                                 ├─ raw_twse_t86, holdings, margin, revenue, ohlcv
                                                                 └─ view_sector_momentum / view_ticker_momentum
                                                                          │
                                              Telegram Alert ─────────────┤
                                              (daily summary)             │
                                                                          │
                                              Claude ←── FastMCP (v2) ────┘
```

## Tech Stack

| Layer | Tool | Rationale |
|-------|------|-----------|
| Data Ingestion | GitHub Actions + Python (Polars) | Scheduled via `daily_harvest.yml`, idempotent upserts |
| Storage | Neon (PostgreSQL) | Chosen over Supabase to reuse v1 pooler string and reduce friction |
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

The `alphatecx-v2` server exposes 7 tools:
1. `sc_capabilities`: System metadata and AI pillar/node definitions.
2. `sc_sector_momentum`: Sector-level capital flows across pillars.
3. `sc_ticker_momentum`: Per-ticker flow with consecutive buy streak tracking.
4. `sc_compare_nodes`: Side-by-side node flow comparison (detects "trickle-down").
5. `sc_accumulation_screen`: Finds tickers with sustained FINI buying (e.g., min streak).
6. `sc_supply_chain_map`: Look up ticker → pillar/node/US partner.
7. `raw_flow_history`: Daily flow time series for any ticker.

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
