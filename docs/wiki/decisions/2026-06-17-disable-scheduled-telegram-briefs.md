---
title: Disable scheduled Telegram briefs
type: decision
slug: 2026-06-17-disable-scheduled-telegram-briefs
date: 2026-06-17
attributed_to: [niko]
belongs_to: [system-architecture, infrastructure-accounts]
source: chat
status: active
tags: [infra, cron, github-actions, telegram]
related: [2026-06-03-reenable-scheduled-harvest-crons, infrastructure-accounts, system-architecture]
---

## Context
Niko surfaced a Telegram screenshot from `claude-finbot` showing an `Intraday alert 15:04 Taipei`. Source inspection traced the message to `.github/workflows/news_harvest.yml`, where scheduled news harvest slots mapped the 10:00, 12:00, and 14:30 Taipei cron runs to `python -m src.cron.brief --mode intraday`; `src/cron/brief.py` then sends the alert through `src.alerts.telegram.send`.

## Decision
Disable scheduled Telegram brief delivery from `news_harvest.yml` by forcing scheduled runs to use `MODE='none'`. Keep the news harvest schedule active, and keep `workflow_dispatch` brief mode inputs available for explicit manual sends.

## Rationale
The user asked to turn off this Telegram automation, and the screenshot matched the scheduled intraday brief path rather than the underlying news harvester. Disabling only scheduled brief delivery stops the unwanted bot messages while preserving data freshness from scheduled news ingestion. [niko]

## Consequences
- Scheduled `news_harvest.yml` runs still harvest news at the existing Taiwan-market-aware slots.
- Scheduled pre-market and intraday Telegram briefs from `news_harvest.yml` no longer send.
- Manual dispatch can still send `pre_market`, `intraday`, or `post_close` when deliberately selected.
- Other Telegram paths, including `daily_harvest.yml` post-close/heartbeat/failure notifications, are unchanged by this decision.

## Provenance
- Discussed on 2026-06-17 between [niko] (owner) and [codex-agent] (agent).
- Trigger context: Telegram screenshot of `claude-finbot` intraday alert.
