"""Continuous news poller — the near-real-time half of news ingestion.

`news_harvest.yml` fires six times a day, so a headline could sit unseen for
four hours. GitHub Actions cannot close that gap: scheduled workflows floor at
five minutes and are routinely queue-delayed far past it. This module is the
long-running service that does, deployed as its own Zeabur container:

    python -m src.news.watch                # NEWS_POLL_SECONDS, default 180
    python -m src.news.watch --once         # one cycle, for smoke tests

It reuses `harvest._fetch_feed` / `harvest._upsert`, so the dedup rules and
the upsert SQL stay single-sourced. Two things it adds:

* **Conditional GET.** Per-feed ETag / Last-Modified held in memory. Load-
  bearing, not politeness: at 480 cycles a day an unconditional fetch would
  re-upsert every unchanged row, and `ON CONFLICT DO UPDATE` writes a new row
  version even when the value is identical. A 304 means zero writes. The cache
  is deliberately not persisted — a restart costs exactly one full fetch.
* **Telegram alerts** on watchlist names, batched one message per cycle.

The cron workflow stays as the backstop. Both paths are idempotent (canonical
URL is the PK), so overlap costs nothing.

Deliberate non-goal: this never emits a trading signal. It forwards headlines
that mention a name already on the watchlist, nothing more.
"""
from __future__ import annotations

import argparse
import html
import logging
import os
import random
import re
import time
from datetime import UTC, datetime, timedelta

from src.alerts import telegram
from src.harvester.loader import atomic, cur, log_ingestion
from src.news.harvest import _fetch_feed, _upsert
from src.news.sources import all_sources

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("news.watch")

# Default cadence. Below ~60s the conditional GETs start looking like a scrape
# to publishers without buying anything: RSS files regenerate on the order of
# minutes.
DEFAULT_POLL_SECONDS = int(os.getenv("NEWS_POLL_SECONDS", "180"))

# Spread requests so every feed isn't hit on the same wall-clock second across
# restarts. Fraction of the poll interval.
JITTER_FRACTION = 0.1

# An article older than this is not news, however fresh its DB row is. Feeds
# re-surface old items constantly — a newly added source, a missed cron slot,
# Google News re-wrapping a URL it already gave us.
MAX_ALERT_AGE = timedelta(hours=6)

# Telegram hard-rejects messages over 4096 chars with a 400, and `send()`
# swallows that into one log line — the alert would just vanish.
TELEGRAM_MAX_CHARS = 4096
MAX_ALERT_ITEMS = 8

# Watchlist membership changes through the Telegram bot, not on restart.
TERMS_REFRESH_CYCLES = 20


# ── Alert targets ─────────────────────────────────────────────────────────

def load_alert_terms() -> dict[str, list[str]]:
    """`{ticker_id: [name, ...]}` for every active watchlist row.

    Both name sources matter and they are in different languages:
    `watchlist.company_name` is English ('GlobalWafers') because the bot
    writes it, while `dim_ticker.company_name` is what TWSE publishes, which
    is Chinese ('環球晶'). Half the feeds are zh-Hant. Keeping only one of the
    two would leave the other half of the corpus matching on the ticker code
    alone — and Chinese headlines often omit the code.
    """
    sql = """
        SELECT w.ticker_id, w.company_name AS watch_name, t.company_name AS twse_name
        FROM watchlist w
        LEFT JOIN dim_ticker t ON t.ticker_id = w.ticker_id
        WHERE w.status = 'active'
    """
    terms: dict[str, list[str]] = {}
    with cur() as c:      # pure read; `atomic()` would open a transaction to commit nothing
        c.execute(sql)
        for ticker_id, watch_name, twse_name in c.fetchall():
            names = [n.strip() for n in (watch_name, twse_name) if n and n.strip()]
            terms[ticker_id] = sorted(set(names))
    log.info("Watching %d ticker(s)", len(terms))
    return terms


def match_terms(row: dict, terms: dict[str, list[str]]) -> str | None:
    """Ticker whose code or name appears in the row, or None.

    Mirrors `db_v2.query_news_for_ticker`: the code must be a standalone
    token, so '6488' doesn't fire on '64880', while names match as
    case-insensitive substrings. First hit wins — one alert per article is
    enough to make the reader go look.
    """
    haystack = f"{row.get('title') or ''}\n{row.get('raw_summary') or ''}"
    folded = haystack.casefold()
    for ticker_id, names in terms.items():
        if re.search(rf"(^|[^0-9]){re.escape(ticker_id)}([^0-9]|$)", haystack):
            return ticker_id
        if any(name.casefold() in folded for name in names):
            return ticker_id
    return None


def is_recent(row: dict, now: datetime) -> bool:
    """Whether the article is new enough to be worth pushing.

    A missing `published_at` counts as recent: `_parse_published` returns None
    for feeds that expose no parseable date, and the item did just appear in
    the feed. The cold-start case this would otherwise flood — every article
    in every feed being a fresh insert — is handled by the priming cycle in
    `run()`, not by dropping undated items here.
    """
    published_at = row.get("published_at")
    if published_at is None:
        return True
    return published_at >= now - MAX_ALERT_AGE


def format_alert(hits: list[tuple[str, dict]]) -> str:
    """One HTML message for a cycle's worth of matches.

    Titles are escaped because `telegram.send` posts with parse_mode=HTML;
    a bare '<' or '&' in a headline would 400 the whole batch.
    """
    shown, overflow = hits[:MAX_ALERT_ITEMS], len(hits) - MAX_ALERT_ITEMS
    lines = [f"📰 <b>Watchlist news</b> ({len(hits)})", ""]
    for ticker_id, row in shown:
        title = html.escape(row.get("title") or "")
        url = html.escape(row.get("url") or "", quote=True)
        feed = html.escape(row.get("feed_name") or row.get("source") or "")
        lines.append(f'• <b>{ticker_id}</b> — <a href="{url}">{title}</a>')
        lines.append(f"  <i>{feed}</i>")
    if overflow > 0:
        lines.append(f"\n…+{overflow} more")

    msg = "\n".join(lines)
    if len(msg) > TELEGRAM_MAX_CHARS:
        msg = msg[:TELEGRAM_MAX_CHARS - 1] + "…"
    return msg


# ── Poll cycle ────────────────────────────────────────────────────────────

def poll_once(cache: dict) -> list[dict]:
    """Fetch every feed, upsert what's new, return the fresh rows.

    Every fetch happens before the transaction opens. `harvest()` writes
    inside one because at six runs a day it doesn't matter; here it would
    hold a snapshot open for the length of a dozen HTTP round-trips, 480
    times a day, blocking vacuum the whole time.
    """
    rows: list[dict] = []
    unchanged = 0
    for source in all_sources():
        fetched = _fetch_feed(source, cache=cache)
        if fetched is None:      # 304 — nothing to do for this feed
            unchanged += 1
            continue
        rows.extend(fetched)

    if not rows:
        log.debug("Nothing to write (%d feed(s) unchanged)", unchanged)
        return []

    with atomic() as c:
        c.execute("SET search_path TO public, neon_auth")
        inserted, skipped = _upsert(c, rows)
        if inserted:
            # A distinct source key: `n_source_status` reads ingestion_log, and
            # interleaving 480 poller rows a day with the cron's would make the
            # cron's own staleness signal unreadable. Only written when
            # something landed, for the same reason.
            log_ingestion(
                "news_watch",
                datetime.now(UTC).date().isoformat(),
                len(inserted),
                "ok",
                f"new={len(inserted)} dup={skipped} unchanged_feeds={unchanged}",
                c=c,
            )

    log.info("%d fetched, %d new, %d dup, %d feed(s) unchanged",
             len(rows), len(inserted), skipped, unchanged)
    return inserted


def run(poll_seconds: int = DEFAULT_POLL_SECONDS,
        max_cycles: int | None = None) -> None:
    """Poll forever (or `max_cycles` times, which is how the tests drive it).

    The first cycle primes: on a cold start every article in every feed is a
    fresh insert, and alerting on that batch would fire hundreds of headlines
    at once. It is ingested, just not announced.

    No cycle may kill the loop. A feed 500ing or the DB blinking has to be
    survivable, or the service needs a restart to resume.
    """
    cache: dict = {}
    terms = load_alert_terms()
    priming = True
    cycle = 0

    while max_cycles is None or cycle < max_cycles:
        cycle += 1
        try:
            if cycle > 1 and cycle % TERMS_REFRESH_CYCLES == 1:
                terms = load_alert_terms()

            fresh = poll_once(cache)

            if priming:
                priming = False
                log.info("Priming cycle — %d row(s) ingested, no alert sent",
                         len(fresh))
            else:
                now = datetime.now(UTC)
                hits = [
                    (ticker_id, row)
                    for row in fresh
                    if is_recent(row, now)
                    and (ticker_id := match_terms(row, terms)) is not None
                ]
                if hits:
                    telegram.send(format_alert(hits))
                    log.info("Alerted on %d article(s)", len(hits))
        except Exception:
            log.exception("Poll cycle %d failed — continuing", cycle)

        if max_cycles is None or cycle < max_cycles:
            time.sleep(poll_seconds * (1 + random.uniform(0, JITTER_FRACTION)))


def main():
    parser = argparse.ArgumentParser(description="Continuous RSS news poller")
    parser.add_argument("--once", action="store_true",
                        help="Run a single cycle and exit (smoke test)")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_SECONDS,
                        help=f"Seconds between cycles (default {DEFAULT_POLL_SECONDS})")
    args = parser.parse_args()
    run(poll_seconds=args.interval, max_cycles=1 if args.once else None)


if __name__ == "__main__":
    main()
