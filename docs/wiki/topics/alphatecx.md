---
title: alphatecx
type: topic
slug: alphatecx
date: 2026-05-07
updated: 2026-07-31
belongs_to: [niko]
source: synthesis
status: active
tags: [product, trading, taiwan, ai]
related: [taiwan-ai-supply-chain, system-architecture, alphatecx-v1, risk-guard, web-frontend]
---

## Summary

alphatecx is a Taiwan stock market analysis and trading support system focused on the AI supply chain. It combines TWSE/TPEX institutional flow data with strategic sector mapping to produce actionable next-day and 3-month investment intelligence.

## Sub-areas

- **[alphatecx-v1](alphatecx-v1.md)** — the existing system (workspace `alphatecx`): APEX TW strategy, TWSE MCP server, yfinance integration, Telegram alerts
- **[system-architecture](system-architecture.md)** — the v2 "stateful upgrade": Neon-centered pipeline with scheduled ingestion, materialized views, and enhanced MCP
- **[taiwan-ai-supply-chain](taiwan-ai-supply-chain.md)** — the strategic supply chain map that drives the investment thesis

## Current State

v2 is live and running daily. This repo is the v2 system, not a plan for one.

- **Ingest** — `.github/workflows/daily_harvest.yml` at 16:30 Taipei, weekdays: T86 flow, foreign holdings, margin, monthly revenue, OHLCV, news, FinMind enrichment → Neon, then matview refresh + quant signal compute.
- **Serve** — FastMCP on Zeabur, 48 tools, mounted at `/mcp/<token>` (and OAuth-gated at bare `/mcp`). `sc_capabilities` is the live catalog, and a test asserts it lists every registered tool.
- **Surfaces** — Telegram alerts; static dashboards at `/d/<token>/`; correlation graph at `/g/<token>/`; [web-frontend](web-frontend.md) Next.js chat client; `skills/` for agent-driven research.
- **Risk** — [risk-guard](risk-guard.md) Phase 1 (market light, stop alerts, settlement check) is built; later phases pending.
- **In flight** — Postgres migrating Neon → self-hosted Zeabur, cutover not yet done.

v1 (the separate `alphatecx` workspace) remains its own system; v2 did not fold it in.

## Open Questions

The 2026-05-07 open questions are resolved: v2 runs alongside v1 rather than replacing it; the Polars/SQL layer shipped (`sql/001`–`018`, `src/harvester/`); ingest extends well past T86 to holdings, margin, revenue, OHLCV, news, and FinMind. The "handover to tech team" question was answered by the working model itself — LLM agents are the tech team, with [niko](../stakeholders/niko.md) directing.

Current open threads live on their own pages: true 5y 填息 and dividend-adjusted flatness remain blocked behind FinMind's paid tier ([finmind-phase2-plan](finmind-phase2-plan.md)).

## History

- 2026-05-07: Wiki bootstrapped from Gemini chat transcript. See [2026-05-07-stateful-upgrade](../decisions/2026-05-07-stateful-upgrade.md).
- 2026-07-31: Refreshed after 12 weeks of drift — page still described v2 as "planning" and cited workspace paths that no longer apply. Replaced Current State with the live system, closed out the answered Open Questions, linked risk-guard and web-frontend. [niko, antigravity-agent]
