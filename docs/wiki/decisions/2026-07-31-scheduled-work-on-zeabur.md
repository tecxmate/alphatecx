---
title: Scheduled work runs on Zeabur too — the `cron` service
type: decision
slug: 2026-07-31-scheduled-work-on-zeabur
date: 2026-07-31
attributed_to: [niko]
belongs_to: [system-architecture, infrastructure-accounts]
source: chat
status: active
tags: [deploy, zeabur, cron, harvester, riskguard]
related: [2026-07-31-mcp-server-vercel-to-zeabur, 2026-07-31-migrate-neon-to-zeabur, 2026-07-31-near-realtime-news-poller]
---

## Context

After the MCP server moved to Zeabur, [niko] asked to "run everything on zeabur now",
with the explicit constraint "do not replace old one" — GitHub Actions stays enabled.

## Decision

A fourth Zeabur service, `cron` (`6a6c5695c553a2bc513cfdef`), runs the scheduled half of the
system from the repo-root `Dockerfile`. The project now holds four services:

| Service | Runs | Built from |
|---|---|---|
| `postgresql` | the database | Zeabur prebuilt |
| `mcp` | FastMCP + Telegram bot webhook | `mcp_server/Dockerfile` |
| `cron` | post-close chain + Risk Guard pre-market | `Dockerfile` (repo root) |
| `worker` | `src/news/watch.py` continuous poller | `Dockerfile.newswatch` |

GitHub Actions keeps running the same schedules, by choice. Double runs are safe because
every writer upserts on composite primary keys.

## Rationale for the awkward parts

**There is no cron service type on Zeabur.** Scheduled work means a long-lived container
running its own scheduler. supercronic over Debian cron: it logs to stdout where
`zeabur deployment log` can see it, needs no root, and does not silently discard the
environment the way crond does.

**Schedules are written in Taipei time, not UTC.** The workflows use UTC only because GH
runners are UTC-only. `TZ=Asia/Taipei` in the image plus local-time crontab entries removes
the standing conversion bug where someone "fixes" 08:30 UTC thinking it is the morning slot.

**Telegram credentials are deliberately unset on `cron`.** Everything else about a double
run is idempotent; the message layer is not. Setting `TELEGRAM_TOKEN` here makes every brief
and every Risk Guard alert arrive twice. The consequence to accept: while Telegram is unset,
a `cron` failure is silent — GitHub Actions is still the path that notifies on failure.

**No `gssencmode=disable` on this service.** That suffix is a GitHub-runner libpq quirk. The
worker reaches Postgres at `postgresql.zeabur.internal:5432`, so it neither needs the
workaround nor crosses the public internet.

## What the worker deliberately does NOT do

- **No commit-back.** `dashboard.build`, `build_ticker_pages` and `correlation_snapshot` are
  absent from the chain: their only output is static files that get committed to main, and
  this service does not commit. Running them here would burn minutes on artifacts nobody
  reads. Dashboard regeneration stays on GitHub Actions.
- **No news harvest.** Removed once `worker` began polling the same feeds every 180s. The
  `news_harvest.yml` backstop still covers the container being down.

## Gotchas

- `riskguard/pipeline.py` imports `mcp_server.api.rg` — the deliberate purity split. Excluding
  `mcp_server/` from the build context breaks the image with `ModuleNotFoundError`. It needs
  `mcp_server/api/` minus `static/`. `mcp_server` and `mcp_server.api` are PEP 420 namespace
  packages, so `/app` on `sys.path` is what makes the import resolve.
- `docs/theses/` is a runtime input, not documentation: `brief.py:180` and `thesis_status.py`
  read thesis frontmatter. Excluding it makes both report zero active theses rather than fail.
- `zeabur variable create` hangs without `-i=false`.
- Image pulls run 6–8 minutes. A redeploy straddling a scheduled slot **misses that slot** —
  which is what happened on 2026-07-31, when a redeploy at 16:29 swallowed the 16:30 run.
  GitHub Actions covered it.
- `zbpack-v2` pre-processes the Dockerfile. One early build produced a container whose PID 1
  was an auto-detected `python -m src.news.watch` with no `/app/deploy` at all. Verify
  `cat /proc/1/cmdline` after deploying rather than assuming the Dockerfile was honoured.

## Provenance

- Executed 2026-07-31 by [claude-agent] on [niko]'s instruction.
- Verified: PID 1 is `supercronic -passthrough-logs deploy/worker-crontab`; container clock is
  CST; DB reachable over the internal hostname (`raw_twse_t86` = 608,082 rows); a real
  `src.news.harvest` run wrote 68 new rows before the news slots were removed.
- **Unverified:** the post-close chain has not yet been observed firing on Zeabur — the
  16:30 slot on the day of the change was lost to a redeploy. First real run is the next
  weekday 16:30 Taipei.
