---
title: alphatecx
type: topic
slug: alphatecx
date: 2026-05-07
updated: 2026-05-07
belongs_to: [niko]
source: synthesis
status: active
tags: [product, trading, taiwan, ai]
related: [taiwan-ai-supply-chain, system-architecture, alphatecx-v1]
---

## Summary

alphatecx is a Taiwan stock market analysis and trading support system focused on the AI supply chain. It combines TWSE/TPEX institutional flow data with strategic sector mapping to produce actionable next-day and 3-month investment intelligence.

## Sub-areas

- **[alphatecx-v1](alphatecx-v1.md)** — the existing system (workspace `alphatecx`): APEX TW strategy, TWSE MCP server, yfinance integration, Telegram alerts
- **[system-architecture](system-architecture.md)** — the v2 "stateful upgrade": Neon-centered pipeline with scheduled ingestion, materialized views, and enhanced MCP
- **[taiwan-ai-supply-chain](taiwan-ai-supply-chain.md)** — the strategic supply chain map that drives the investment thesis

## Current State

Two workspaces exist:
- `/Users/niko/antigravity/alphatecx` — v1 (running): hourly screening via APScheduler, yfinance + TWSE data, Telegram notifications, MCP server deployed on Vercel
- `/Users/niko/antigravity/alphatecx-2` — v2 (this repo, planning): wiki-first project template, architecture being defined

## Open Questions

- Will v2 replace v1 entirely, or run alongside it?
- Polars extraction logic and SQL schema refinement
- Handover timeline to tech team?
- Exact TWSE endpoints to ingest beyond T86 (MI_QFIIS, BFI82U, margin data)?

## History

- 2026-05-07: Wiki bootstrapped from Gemini chat transcript. See [2026-05-07-stateful-upgrade](../decisions/2026-05-07-stateful-upgrade.md).
