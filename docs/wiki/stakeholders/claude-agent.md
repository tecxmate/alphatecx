---
title: Claude Agent
type: stakeholder
slug: claude-agent
date: 2026-07-31
updated: 2026-07-31
role: agent
source: observation
status: active
tags: [agent, claude, implementation]
related: [alphatecx, system-architecture, risk-guard]
---

## Summary

Claude Code agent operating in this repo. Responsible for implementation work, infrastructure operations, and wiki maintenance during Claude sessions.

## Areas of Responsibility

- Code and infrastructure changes in `alphatecx`
- Database operations and migrations
- Wiki curation per `AGENTS.md`

## Contributions

- 2026-07-31 — Migrated the Postgres warehouse from Neon to Zeabur; diagnosed the `view_ticker_momentum` refresh break.
- 2026-07-31 — Built [[risk-guard]] Phase 1 from `RISK_GUARD_PRD.md` v1.1: `sql/018_riskguard.sql`, the `riskguard/` cron package, the pure `mcp_server/api/rg/` decision core, five `rg_*` MCP tools, seven Telegram commands, 74 tests. Established the deployment-split rationale for where Risk Guard code lives. See [[2026-07-31-risk-guard-phase1]].
