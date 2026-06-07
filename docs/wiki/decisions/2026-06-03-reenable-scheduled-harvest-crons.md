---
title: Re-enable scheduled harvest crons
type: decision
slug: 2026-06-03-reenable-scheduled-harvest-crons
date: 2026-06-03
attributed_to: [niko]
belongs_to: [system-architecture, infrastructure-accounts]
source: chat
status: active
tags: [infra, cron, vercel, github-actions, reversal]
related: [2026-05-27-disable-scheduled-harvest-crons, system-architecture, infrastructure-accounts]
---

## Context
Eight days after the 2026-05-27 pause, the staleness surfaced in the APEX morning flow briefing for 2026-06-02: `sc_data_status` reported `latest_t86_date: 2026-05-25`, forcing the briefing to fall back on direct TWSE-API calls and to approximate trailing 20-day D4 ratios from a windowed slice (Apr 9 – May 25). The Hantang rotation-vs-abandonment classification, the Wistron blow-off-top read, and every MGX climax-check that depends on a per-name trailing average degrades while ingestion is off.

Inspection on 2026-06-03 confirmed the architecture: the daily harvester runs on **GitHub-hosted runners** (`actions/setup-python@v5`, Neon over libpq with `gssencmode=disable`), not on Vercel. The only path by which the daily workflow touches Vercel is the post-step commit-back of `graph_snapshot.json` + dashboard HTML to `main`, which triggers a Vercel redeploy. The news workflow does not commit anything back. `mcp_server/vercel.json` defines no `crons` block — Vercel itself is not scheduling work.

## Decision
Reverse [2026-05-27-disable-scheduled-harvest-crons]. Restore the original schedule blocks in both workflows:

- `.github/workflows/daily_harvest.yml`: `cron: '30 8 * * 1-5'` (16:30 Taipei, Mon-Fri)
- `.github/workflows/news_harvest.yml`: all six prior triggers (07:30 / 10:00 / 12:00 / 14:30 Taipei weekdays, plus 21:00 / 06:00 Taipei daily)

`workflow_dispatch` remains alongside the schedule for manual runs.

## Rationale
The user explicitly determined the assumed CPU cost is not material in practice ("I don't think it takes much CPU"). The freshness penalty of the manual-only mode is concrete and recurring — every APEX morning briefing degrades until a human remembers to re-trigger the pipeline. The original schedule already reflected the Taiwan-market clock; reinstating it is the lowest-friction restoration. [niko]

## Consequences
- T86, holdings, margin, OHLCV, monthly revenue, news, sector/ticker matviews, quant signals, lead-lag, thesis heartbeat, and the static dashboard refresh nightly on weekdays again.
- Vercel will see one redeploy per weekday from the snapshot commit-back step. If billing trends justify it, a future change can decouple the snapshot commit from the data ingest (e.g., write to object storage instead of git) without disturbing the cron.
- The May 26 – Jun 2 backfill is not covered by the resumed cron. A one-off `workflow_dispatch` of `Daily TWSE Harvest` is required to fill the gap before the next morning briefing has a clean trailing-average window. The harvester is idempotent — re-running over Jun 2 a second time when the cron fires today is a no-op.

## Provenance
- Discussed on 2026-06-03 between [niko] (owner) and [antigravity-agent] (agent).
- Trigger context: APEX morning flow briefing for 2026-06-02 had to fall back to TWSE-direct because Alpha v2 returned stale data; user inspected `alphatecx-2` source and Vercel-side architecture, and asked to restore the cron.
