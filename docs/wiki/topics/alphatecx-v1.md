---
title: alphatecx v1 (Existing System)
type: topic
slug: alphatecx-v1
date: 2026-05-07
updated: 2026-05-07
belongs_to: [niko]
source: code
status: active
tags: [implementation, mcp, twse, trading]
related: [alphatecx, system-architecture]
---

## Summary

The currently-running alphatecx system in workspace `/Users/niko/antigravity/alphatecx`. A Python-based trading support tool with hourly TWSE screening, Telegram notifications, and an MCP server for Claude integration.

## Current State

### Strategy Engine (`main.py` + `strategies/apex_tw.py`)
- **Screening**: hourly during TW session (09:00–13:30 Taipei)
- **Monitoring**: 5-minute intervals for fill/TP/SL detection
- **Params**: small-cap (≤50th pctile market cap), 30-day volatility, limit orders at current − 0.5×vol
- **Risk**: 10% per position, max 5 positions
- **Delivery**: Telegram bot notifications (decision support, not auto-execution)

### MCP Server (`mcp_server/`)
- Deployed on Vercel (FastAPI + FastMCP)
- **10 tools** exposed to Claude:
  - `yf_quote`, `yf_history`, `yf_volatility` — Yahoo Finance (intraday)
  - `twse_inst_flow`, `twse_daily_close`, `twse_daily_history`, `twse_margin_balance`, `twse_foreign_holdings` — TWSE/TPEX (T+1)
  - `monthly_revenue` — MOPS
  - `db_positions`, `db_signals`, `db_universe`, `db_journal` — bot state (Postgres)
  - `db_add_universe_symbol`, `db_log_decision` — write tools
- Auth: URL-as-secret (`/mcp/<token>/`)
- Every response stamped with `_source`, `_as_of`, `_freshness`

### Data Layer (`data/`)
- `twse_src.py`: fetches T86 (TWSE) + dailyTrade (TPEX) institutional flow, 6hr cache, 7-day fallback
- `yfinance_src.py`: intraday low/high for fill monitoring

### Limitations (motivating v2)
- **Stateless**: each Claude query re-fetches from TWSE API — no historical accumulation
- **No sector aggregation**: can query individual tickers but no supply-chain-level views
- **No scheduled ingestion**: data pulled on-demand, not systematically stored
- **Rate-limit risk**: heavy usage hits TWSE/Yahoo rate limits

## Open Questions

- Which v1 MCP tools carry forward into v2?
- Does v1 stay running during v2 development?
