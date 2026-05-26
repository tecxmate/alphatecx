---
title: Disable scheduled harvest crons
type: decision
slug: 2026-05-27-disable-scheduled-harvest-crons
date: 2026-05-27
attributed_to: [niko]
belongs_to: [system-architecture, infrastructure-accounts]
source: chat
status: active
tags: [infra, cron, vercel, github-actions]
related: [system-architecture, infrastructure-accounts]
---

## Context
Vercel usage showed the `app` project consuming a large share of CPU hours over the last 30 days. The repository did not define Vercel Cron in `mcp_server/vercel.json`, but it did have GitHub Actions schedules for the daily TWSE harvest and frequent news harvest/brief jobs. The daily workflow also committed refreshed static assets back to `main`, which can trigger Vercel redeploys.

## Decision
Disable the scheduled triggers for `.github/workflows/daily_harvest.yml` and `.github/workflows/news_harvest.yml`, while keeping `workflow_dispatch` so the harvest and brief workflows remain available for manual runs.

## Rationale
The user explicitly asked to turn off the running cron because it was taking too many Vercel CPU hours. Keeping manual dispatch preserves operational access without unattended compute churn. [niko]

## Consequences
Automated TWSE/news refreshes, Telegram briefs, lead-lag recomputes, thesis heartbeats, and generated static dashboard/ticker/graph refreshes no longer run on a schedule. Data freshness now depends on manual workflow runs or a future lower-cost schedule.

## Provenance
- Discussed on 2026-05-27 between [niko] (owner) and [antigravity-agent] (agent).
