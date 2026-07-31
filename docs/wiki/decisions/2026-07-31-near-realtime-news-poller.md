---
title: Near-real-time news via a polling worker, not SSE or WebSocket
type: decision
slug: 2026-07-31-near-realtime-news-poller
date: 2026-07-31
updated: 2026-07-31
attributed_to: [niko]
belongs_to: [alphatecx, system-architecture]
source: chat
status: active
tags: [news, telegram, realtime, zeabur, ingestion]
related: [system-architecture, infrastructure-accounts, web-frontend]
---

# Near-real-time news via a polling worker, not SSE or WebSocket

## Context

Niko asked whether the system needs Redis, then whether real-time news and
signals need SSE or WebSocket. Neither question was the real one.

There is no Redis anywhere in the repo and nothing wants it: reads hit
pre-computed materialized views, GitHub Actions is the scheduler, `session_state`
is a pure function of the Taipei clock, and there is no rate limiter or pub/sub
fan-out. Adding it would buy nothing for a pipeline whose data changes once a day.

Transport was the wrong layer too. The binding constraint is **ingestion
cadence**: `news_harvest.yml` fires six times a day, so a headline can sit unseen
for four hours. A perfect WebSocket still delivers four-hour-old news. And
GitHub Actions cannot close the gap — scheduled workflows floor at five minutes
and are routinely queue-delayed well past that.

## Decision

Build a **long-running poller as its own Zeabur service**, pushing to Telegram.
No SSE, no WebSocket, no new HTTP surface.

Niko confirmed Telegram is the only consumer, so the browser-facing half — SSE
off Postgres `LISTEN`/`NOTIFY` for `web/` — is explicitly **not** built.

`src/news/watch.py` polls every feed on `NEWS_POLL_SECONDS` (default 180),
reusing `harvest._fetch_feed` / `harvest._upsert` so the dedup rules and upsert
SQL stay single-sourced. `.github/workflows/news_harvest.yml` stays as the
backstop; both paths are idempotent on the canonical-URL PK, so overlap is free.

## Rationale

- Telegram already **is** the push channel (`src/alerts/telegram.py`, `bot.py`
  webhook). The missing piece was only how fast news reaches the DB.
- The poller writes to `raw_news` and fetches the public internet, so it does not
  belong in the `mcp_server/` image — that one is the read-only side, ships
  without polars or feedparser, and holds read credentials. Separate container,
  separate env. [claude-agent]
- WebSocket would buy nothing even if a browser surface existed: the traffic is
  one-way server→client. SSE would be the right shape there, and token-in-path
  auth suits it because `EventSource` cannot set headers. Any such endpoint would
  also need adding to `security.py`'s whitelist — it gates only `/mcp`, `/g`,
  `/d`, `/h`, `/t`, so a new `/events` route would ship unauthenticated.

## Consequences

- **A ceiling remains, and it is structural.** "Signals" are not news. Risk Guard
  and flow leaders derive from T86, which TWSE publishes once a day around 15:00.
  No poller, no transport, no cache makes institutional-flow signals intraday.
  Only news and price can be near-real-time.
- Conditional GET (ETag / `If-Modified-Since`, cached in memory per feed) is
  load-bearing rather than merely polite. At 480 cycles a day an unconditional
  fetch would re-upsert every unchanged row, and `ON CONFLICT DO UPDATE` writes a
  new row version even when the value is identical — dead tuples and index churn
  all day. A 304 means zero writes. The cache is not persisted; a restart costs
  exactly one full fetch.
- **Measured live: only 5 of the 12 feeds send ETag / Last-Modified at all**
  (3 answered 304 on an immediate re-poll). Conditional GET therefore cannot be
  the whole defence, so `_upsert`'s `DO UPDATE` gained
  `WHERE raw_news.published_at IS NULL`. It preserves the original intent —
  backfill a null date — while making a genuinely-unchanged conflict update
  nothing and return no row. `fetchone()` then yields `None`, which the existing
  count logic already reads as a duplicate. [claude-agent]
- Two guards exist because "fresh DB insert" is **not** the same as "new news":
  a **priming cycle** (first pass ingests, announces nothing — on a cold start
  every article in every feed is a fresh insert) and a **6-hour recency gate**
  (feeds constantly re-surface old items). Undated items count as recent;
  `_parse_published` returns `None` for feeds with no parseable date, and the
  priming cycle already covers the flood case.
- Alert matching needs **both** name sources, and they are in different
  languages: `watchlist.company_name` is English because the bot writes it
  ('GlobalWafers'), while `dim_ticker.company_name` is what TWSE publishes and is
  Chinese ('環球晶'). Half the feeds are zh-Hant. Keeping only one would leave
  half the corpus matching on the ticker code alone, and Chinese headlines often
  omit the code.
- The poller logs to `ingestion_log` under `source='news_watch'`, distinct from
  the cron's `'news_harvest'`, and only when rows actually landed. Interleaving
  480 rows a day would make `n_source_status`'s staleness signal for the cron
  unreadable.
- **Deploy it inside the Zeabur project, pointed at
  `postgresql.zeabur.internal:5432`.** This service holds *write* credentials and
  Postgres has TLS disabled outright — the private path is the only thing making
  that tolerable. See [the migration decision](2026-07-31-migrate-neon-to-zeabur.md).
- **`pytest -q` under a bare Homebrew `python3` no longer collects the suite.**
  `tests/test_news_watch.py` imports `src/news/harvest.py`, which needs feedparser
  and — via `harvester/loader` — polars, and a Homebrew python is PEP-668
  externally-managed so neither can be installed into it. Bare `python3` only ever
  worked because nothing under `src/` had tests. The pre-commit hook now prefers
  `.venv/bin/python` and falls back to `python3`. [claude-agent]

## Non-goal, enforced

The poller never emits a trading signal. It forwards headlines that mention a
name already on the watchlist. Same discipline as [risk-guard](../topics/risk-guard.md).
