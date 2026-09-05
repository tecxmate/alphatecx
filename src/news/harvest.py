"""RSS harvester — fetch every configured feed, dedup, upsert into raw_news.

Run:
    python -m src.news.harvest                # all configured sources
    python -m src.news.harvest --source digitimes  # one source

Idempotent: PRIMARY KEY on canonicalised URL means re-runs are no-ops on
unchanged items. Title-hash matching catches the case where Google News
points back to a different URL than the original publisher's RSS — only
one row per article ends up in the DB.

No LLM calls in this stage. Sentiment + entity columns stay null; the
Phase 2b classifier fills them in place.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import requests

from src.harvester.loader import atomic, log_ingestion
from src.news.sources import all_sources

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("news.harvest")

# raw_news.url is the PRIMARY KEY, so every URL becomes a btree index row.
# Postgres caps those at 2704 bytes ("index row size N exceeds btree version 4
# maximum 2704"). 2000 leaves headroom for index overhead and is far above any
# real article URL — the only things near the cap are Google News redirect URLs,
# which carry a base64 payload rather than a readable path. Dropping one costs a
# single article; letting it raise costs the entire run (see _upsert).
MAX_URL_BYTES = 2000

# Reasonable timeouts — feeds take seconds, not minutes. Network hangs are
# the most common failure mode when running daily.
HTTP_TIMEOUT = 20.0

# A sane User-Agent. Some publishers (Bloomberg in particular) 403 obvious
# bot UAs but accept browser-like ones. feedparser on its own sometimes
# trips this, so we fetch with requests then hand bytes to feedparser.
UA = "alphatecx-news-harvester/1.0 (+https://alphatecx-v2-mcp.vercel.app)"

# URL params that carry tracking, not content identity. Strip during dedup.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid",
    # Google News wraps real URLs and adds noise; safe to drop.
    "oc", "hl", "gl", "ceid",
}


def _canonical_url(url: str) -> str:
    """Strip tracking params + fragment + trailing slash; lowercase host.

    Same article from "url?utm_source=rss" and "url?utm_source=newsletter"
    becomes one canonical key.
    """
    p = urlparse(url.strip())
    if not p.scheme or not p.netloc:
        return url.strip()
    netloc = p.netloc.lower()
    qs_pairs = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in _TRACKING_PARAMS]
    query = urlencode(qs_pairs)
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), netloc, path, "", query, ""))


_TITLE_NORMALISE = re.compile(r"\s+")
_PUNCT_STRIP = re.compile(r"[^\w\s]")


def _title_hash(title: str) -> str:
    """sha256 first 16 chars of normalised title — case+punct insensitive."""
    norm = _PUNCT_STRIP.sub("", title.lower())
    norm = _TITLE_NORMALISE.sub(" ", norm).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _parse_published(entry) -> datetime | None:
    """Extract a UTC-aware datetime from a feedparser entry. Returns None
    if the feed doesn't expose a parseable date.

    RSS 1.0 (e.g. Nikkei Asia) and some Atom feeds put the date in
    `dc_date` / `dcterms_modified` — feedparser exposes those as flat
    string attributes that need separate parsing. Try every known field
    before giving up."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=UTC)
    # Fallback: dc_date / dcterms_modified come through as strings.
    for attr in ("dc_date", "dcterms_modified", "date"):
        s = getattr(entry, attr, None)
        if s:
            try:
                # ISO 8601 with optional Z. dateutil would be nicer but
                # avoiding the dep — fromisoformat handles "2026-05-07T08:30:00+00:00".
                s = s.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
                return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def _summary(entry) -> str | None:
    """Best-effort extraction of a description string. Strip HTML tags
    crudely — content sanitisation is downstream's job."""
    raw = getattr(entry, "summary", None) or getattr(entry, "description", None)
    if not raw:
        return None
    text = re.sub(r"<[^>]+>", " ", raw)
    text = _TITLE_NORMALISE.sub(" ", text).strip()
    return text[:2000] if text else None  # cap to avoid huge rows


def _fetch_feed(source: dict, cache: dict | None = None) -> list[dict] | None:
    """Fetch a single source. Returns a list of (already-shaped) row dicts.

    Network errors are caught and logged — one bad source shouldn't stop
    the whole harvester. The empty list propagates and the source's
    counter goes to zero, which downstream `n_*` tools will surface.

    Pass `cache` — a `{source_key: {"etag", "last_modified"}}` dict — to do a
    conditional GET. Returns **None**, distinct from `[]`, when the server
    answers 304: nothing changed, so there is nothing to upsert. That
    distinction is what makes minute-scale polling viable; without it every
    cycle re-upserts every unchanged row. `src.news.watch` owns such a cache.
    `harvest()` passes none and behaves exactly as it always did.
    """
    url = source["url"]
    headers = {"User-Agent": UA}
    validators = (cache or {}).get(source["key"], {})
    if validators.get("etag"):
        headers["If-None-Match"] = validators["etag"]
    if validators.get("last_modified"):
        headers["If-Modified-Since"] = validators["last_modified"]

    try:
        r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        # 304 must be checked before raise_for_status(), which does not raise
        # on 3xx. The body is empty, so falling through would hand b"" to
        # feedparser and log the healthy path as an unparseable feed.
        if r.status_code == 304:
            return None
        r.raise_for_status()
    except Exception as e:
        log.error("  %s: HTTP failure — %s", source["key"], e)
        return []

    if cache is not None:
        resp_headers = r.headers or {}
        etag = resp_headers.get("ETag")
        last_modified = resp_headers.get("Last-Modified")
        if etag or last_modified:
            cache[source["key"]] = {"etag": etag, "last_modified": last_modified}

    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        log.warning("  %s: feed unparseable — %s", source["key"], feed.bozo_exception)
        return []

    rows: list[dict] = []
    for entry in feed.entries:
        link = getattr(entry, "link", None)
        title = getattr(entry, "title", None)
        if not link or not title:
            continue
        rows.append({
            "url": _canonical_url(link),
            "source": source["key"],
            "feed_name": source["feed_name"],
            "lang": source["lang"],
            "title": title.strip(),
            "title_hash": _title_hash(title),
            "raw_summary": _summary(entry),
            "published_at": _parse_published(entry),
        })
    return rows


def _upsert(c, rows: list[dict]) -> tuple[list[dict], int]:
    """Insert new rows; return (inserted_rows, n_skipped_duplicates).

    The inserted rows come back rather than just a count because
    `src.news.watch` alerts on them — a fresh insert is the only reliable
    "we have never seen this article" signal available.

    Two-stage dedup:
    1. Canonical URL is the PK — same URL across runs collapses.
    2. Title hash query — if a different feed surfaced the same article
       (Google News pointing at a Bloomberg URL with different tracking),
       skip the duplicate before insertion.

    The title-hash check is per-run, not global. Cross-run dedup happens
    via the URL PK (Google News URLs are stable). Per-run dedup catches
    the case where two feeds in this batch surface the same headline.
    """
    if not rows:
        return [], 0
    seen_titles: set[str] = set()
    inserted: list[dict] = []
    skipped = 0

    # ON CONFLICT: don't overwrite content (title, summary) — first
    # ingestion wins. But DO fill in published_at if it was null and we
    # now have a value (catches feedparser quirks fixed retroactively).
    # RETURNING (xmax = 0) tells us if the row was a fresh insert (true)
    # or an existing-row update (false) — needed for accurate counts.
    #
    # The WHERE is what keeps `src.news.watch` from churning the table.
    # Without it, a conflict rewrites published_at to the value it already
    # holds — and Postgres writes a new row version regardless, so a poller
    # re-seeing ~600 unchanged articles every few minutes would produce dead
    # tuples and index bloat all day. Conditional GET only covers the feeds
    # that send validators; measured live, that is 5 of 12. With the WHERE, a
    # genuinely-unchanged conflict updates nothing, returns no row, and
    # `fetchone()` yields None — already counted as a duplicate below.
    sql = """
        INSERT INTO raw_news (url, source, feed_name, lang, title,
                              title_hash, raw_summary, published_at)
        VALUES (%(url)s, %(source)s, %(feed_name)s, %(lang)s, %(title)s,
                %(title_hash)s, %(raw_summary)s, %(published_at)s)
        ON CONFLICT (url) DO UPDATE SET
            published_at = COALESCE(raw_news.published_at, EXCLUDED.published_at)
        WHERE raw_news.published_at IS NULL
        RETURNING (xmax = 0) AS is_fresh_insert
    """
    for row in rows:
        h = row["title_hash"]
        if h in seen_titles:
            skipped += 1
            continue
        # Drop over-long URLs BEFORE the INSERT, not with a try/except around
        # it. `url` is the PRIMARY KEY, and Postgres refuses a btree index row
        # over 2704 bytes — a Google News redirect embeds a long base64 payload
        # and has been observed at 2848. The exception is not the real damage:
        # harvest() wraps EVERY source in one atomic() transaction, so a raise
        # here rolls back the whole run and every article from every feed is
        # lost, not just this one. Six of forty runs died that way over
        # 2026-09-02..04, and `src.news.watch` imports this function, so the
        # Zeabur poller crashed on the same articles every cycle.
        #
        # It must be a filter rather than a caught exception: a failed
        # statement poisons the surrounding transaction, so every later row
        # would fail with "current transaction is aborted" anyway.
        if len(row["url"].encode("utf-8")) > MAX_URL_BYTES:
            log.warning(
                "skipping %s article — URL is %d bytes, over the %d-byte "
                "index limit: %.120s...",
                row.get("source", "?"), len(row["url"].encode("utf-8")),
                MAX_URL_BYTES, row["url"],
            )
            skipped += 1
            continue
        seen_titles.add(h)
        c.execute(sql, row)
        result = c.fetchone()
        if result and result[0]:
            inserted.append(row)
        else:
            skipped += 1
    return inserted, skipped


def harvest(only: str | None = None) -> dict:
    sources = [s for s in all_sources() if only is None or s["key"] == only]
    if not sources:
        raise ValueError(f"No source matches key '{only}'")

    log.info("Harvesting %d source(s)", len(sources))
    total_in = total_skip = total_err = 0

    with atomic() as c:
        c.execute("SET search_path TO public, neon_auth")
        for src in sources:
            t0 = time.time()
            # No cache is passed, so this never returns None (304 only happens
            # on a conditional request).
            rows = _fetch_feed(src) or []
            new_rows, n_skip = _upsert(c, rows)
            dur = time.time() - t0
            log.info("  %s: %d items, %d new, %d dup, %.1fs",
                     src["key"], len(rows), len(new_rows), n_skip, dur)
            total_in += len(new_rows)
            total_skip += n_skip
            if not rows:
                total_err += 1

        log_ingestion(
            "news_harvest",
            datetime.now(UTC).date().isoformat(),
            total_in,
            "ok" if total_err == 0 else "partial",
            f"sources={len(sources)} new={total_in} dup={total_skip} errors={total_err}",
            c=c,
        )

    log.info("Done — %d new / %d dup / %d source errors",
             total_in, total_skip, total_err)
    return {"sources": len(sources), "new": total_in, "dup": total_skip, "errors": total_err}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="Run only one source (by key)")
    args = parser.parse_args()
    harvest(only=args.source)


if __name__ == "__main__":
    main()
