"""Tests for the continuous news poller (src/news/watch.py).

No network, no DB — every test drives the pure functions or stubs
`requests.get` / the cursor. The pieces that need a live feed (the actual
loop) are exercised through `poll_once` with a fake fetch.
"""
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

from src.news import harvest, watch


def _row(**kw) -> dict:
    """A raw_news-shaped row with sane defaults."""
    base = {
        "url": "https://example.com/a",
        "source": "gnews-tw-ai-zh",
        "feed_name": "Google News — TSMC/Foxconn/AI servers (zh-TW)",
        "lang": "zh-Hant",
        "title": "some headline",
        "title_hash": "abc123",
        "raw_summary": None,
        # Recent by default so RunPrimingTests, which exercises the real run()
        # loop against the wall clock, stays inside MAX_ALERT_AGE. A fixed
        # calendar date here rots: run() drops anything older than the window,
        # so the alert stopped firing once that date aged out. is_recent tests
        # pass their own published_at and are unaffected.
        "published_at": datetime.now(UTC) - timedelta(minutes=5),
    }
    base.update(kw)
    return base


# Watchlist gives English names, dim_ticker gives Chinese ones. Both have to
# be in the term list or the zh-Hant feeds only ever match on the code.
TERMS = {
    "6488": ["環球晶", "GlobalWafers"],
    "2330": ["台積電", "TSMC"],
}


class MatchTermsTests(unittest.TestCase):
    def test_matches_chinese_name_in_title(self):
        # Arrange
        row = _row(title="環球晶7月營收創高，外資買超")

        # Act
        hit = watch.match_terms(row, TERMS)

        # Assert
        self.assertEqual(hit, "6488")

    def test_matches_english_name_case_insensitively(self):
        row = _row(title="globalwafers lifts capex guidance", lang="en")
        self.assertEqual(watch.match_terms(row, TERMS), "6488")

    def test_matches_ticker_code_as_standalone_token(self):
        row = _row(title="環球晶(6488)法說會重點")
        self.assertEqual(watch.match_terms(row, TERMS), "6488")

    def test_ignores_ticker_code_embedded_in_a_longer_number(self):
        # '64880' must not read as '6488' — this is the whole reason the code
        # match is boundary-aware rather than a substring test.
        row = _row(title="某檔股票成交 64880 張")
        self.assertIsNone(watch.match_terms(row, TERMS))

    def test_matches_on_summary_when_title_is_silent(self):
        row = _row(title="盤中焦點", raw_summary="台積電領漲電子股")
        self.assertEqual(watch.match_terms(row, TERMS), "2330")

    def test_returns_none_when_nothing_matches(self):
        row = _row(title="ECB holds rates steady", lang="en")
        self.assertIsNone(watch.match_terms(row, TERMS))


class RecencyTests(unittest.TestCase):
    NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    def test_recent_article_is_alertable(self):
        row = _row(published_at=self.NOW - timedelta(minutes=20))
        self.assertTrue(watch.is_recent(row, self.NOW))

    def test_stale_article_is_not_alertable(self):
        # A feed can re-surface week-old items (new source, missed cron slot,
        # Google News re-wrapping an old URL). Those insert fresh but are not
        # news — alerting on them would fire a week-old headline.
        row = _row(published_at=self.NOW - timedelta(days=7))
        self.assertFalse(watch.is_recent(row, self.NOW))

    def test_undated_article_is_alertable(self):
        # `_parse_published` returns None for feeds with no parseable date.
        # It just appeared in the feed for the first time, so treat it as now.
        # The cold-start flood this could cause is handled by the priming
        # cycle in run(), not here.
        row = _row(published_at=None)
        self.assertTrue(watch.is_recent(row, self.NOW))

    def test_future_dated_article_is_alertable(self):
        # Publisher clock skew shouldn't silently drop an item.
        row = _row(published_at=self.NOW + timedelta(hours=2))
        self.assertTrue(watch.is_recent(row, self.NOW))


class FormatAlertTests(unittest.TestCase):
    def test_escapes_html_in_titles(self):
        # send() posts with parse_mode=HTML; an unescaped '<' in a headline
        # makes Telegram reject the whole message with a 400.
        hits = [("2330", _row(title="TSMC & Q3 <guidance>", lang="en"))]

        msg = watch.format_alert(hits)

        self.assertIn("TSMC &amp; Q3 &lt;guidance&gt;", msg)
        self.assertNotIn("<guidance>", msg)

    def test_includes_ticker_and_feed_name(self):
        hits = [("6488", _row(title="環球晶營收創高"))]
        msg = watch.format_alert(hits)
        self.assertIn("6488", msg)
        self.assertIn("環球晶營收創高", msg)

    def test_caps_item_count_and_notes_the_remainder(self):
        hits = [
            ("2330", _row(title=f"headline {i}", url=f"https://e.com/{i}"))
            for i in range(watch.MAX_ALERT_ITEMS + 5)
        ]

        msg = watch.format_alert(hits)

        self.assertIn("+5 more", msg)

    def test_stays_within_the_telegram_length_limit(self):
        hits = [
            ("2330", _row(title="x" * 900, url=f"https://e.com/{i}"))
            for i in range(watch.MAX_ALERT_ITEMS)
        ]
        self.assertLessEqual(len(watch.format_alert(hits)), watch.TELEGRAM_MAX_CHARS)


class ConditionalGetTests(unittest.TestCase):
    SOURCE = {"key": "digitimes", "feed_name": "DIGITIMES Asia",
              "url": "https://example.com/rss", "lang": "en"}

    def test_sends_stored_validators_on_the_next_fetch(self):
        cache = {"digitimes": {"etag": 'W/"abc"',
                               "last_modified": "Thu, 31 Jul 2026 04:00:00 GMT"}}
        resp = mock.Mock(status_code=304, content=b"")

        with mock.patch("src.news.harvest.requests.get", return_value=resp) as get:
            harvest._fetch_feed(self.SOURCE, cache=cache)

        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["If-None-Match"], 'W/"abc"')
        self.assertEqual(headers["If-Modified-Since"], "Thu, 31 Jul 2026 04:00:00 GMT")

    def test_304_returns_none_rather_than_an_empty_list(self):
        # raise_for_status() does NOT raise on 304 and the body is empty, so
        # without an explicit check this would fall through to feedparser and
        # be misreported as an unparseable feed.
        resp = mock.Mock(status_code=304, content=b"")
        with mock.patch("src.news.harvest.requests.get", return_value=resp):
            result = harvest._fetch_feed(self.SOURCE, cache={"digitimes": {"etag": "x"}})
        self.assertIsNone(result)

    def test_stores_validators_from_a_200(self):
        resp = mock.Mock(
            status_code=200,
            content=b"<rss><channel></channel></rss>",
            headers={"ETag": 'W/"new"', "Last-Modified": "Fri, 01 Aug 2026 00:00:00 GMT"},
        )
        cache: dict = {}

        with mock.patch("src.news.harvest.requests.get", return_value=resp):
            harvest._fetch_feed(self.SOURCE, cache=cache)

        self.assertEqual(cache["digitimes"]["etag"], 'W/"new"')
        self.assertEqual(cache["digitimes"]["last_modified"],
                         "Fri, 01 Aug 2026 00:00:00 GMT")

    def test_no_cache_means_no_conditional_headers(self):
        # harvest() calls _fetch_feed without a cache; it must behave exactly
        # as it did before conditional GET existed.
        resp = mock.Mock(status_code=200, content=b"<rss></rss>", headers={})
        with mock.patch("src.news.harvest.requests.get", return_value=resp) as get:
            harvest._fetch_feed(self.SOURCE)
        headers = get.call_args.kwargs["headers"]
        self.assertNotIn("If-None-Match", headers)
        self.assertNotIn("If-Modified-Since", headers)


class _FakeCursor:
    """Minimal cursor: every execute() queues a fresh/duplicate verdict."""

    def __init__(self, verdicts):
        self._verdicts = list(verdicts)
        self._last = None

    def execute(self, sql, params=None):
        self._last = self._verdicts.pop(0) if self._verdicts else False

    def fetchone(self):
        return (self._last,)


class UpsertReturnsInsertedRowsTests(unittest.TestCase):
    def test_returns_the_rows_that_were_fresh_inserts(self):
        rows = [_row(title="a", title_hash="h1"), _row(title="b", title_hash="h2")]
        c = _FakeCursor([True, False])

        inserted, skipped = harvest._upsert(c, rows)

        self.assertEqual([r["title"] for r in inserted], ["a"])
        self.assertEqual(skipped, 1)

    def test_per_run_title_dedup_still_skips_before_touching_the_db(self):
        rows = [_row(title="a", title_hash="dup"), _row(title="a copy", title_hash="dup")]
        c = _FakeCursor([True])

        inserted, skipped = harvest._upsert(c, rows)

        self.assertEqual(len(inserted), 1)
        self.assertEqual(skipped, 1)

    def test_empty_input(self):
        self.assertEqual(harvest._upsert(_FakeCursor([]), []), ([], 0))

    def test_an_unchanged_conflict_returns_no_row_and_counts_as_duplicate(self):
        # The DO UPDATE carries `WHERE raw_news.published_at IS NULL`, so a
        # genuinely-unchanged row updates nothing and RETURNING yields no row.
        # fetchone() gives None — the poller must read that as a duplicate, not
        # crash and not alert.
        class _NoRowCursor(_FakeCursor):
            def fetchone(self):
                return None

        inserted, skipped = harvest._upsert(_NoRowCursor([]), [_row(title_hash="h9")])

        self.assertEqual(inserted, [])
        self.assertEqual(skipped, 1)


class PollOnceTests(unittest.TestCase):
    SOURCES = [{"key": "a", "feed_name": "A", "url": "https://a", "lang": "en"}]

    def test_skips_the_write_transaction_when_every_feed_is_unchanged(self):
        # 12 feeds × 480 cycles/day of no-op upserts is pure dead-tuple churn.
        # A cycle where everything 304s must not open a transaction at all.
        with mock.patch("src.news.watch.all_sources", return_value=self.SOURCES), \
             mock.patch("src.news.harvest._fetch_feed", return_value=None), \
             mock.patch("src.news.watch.atomic") as atomic_:
            inserted = watch.poll_once(cache={})

        self.assertEqual(inserted, [])
        atomic_.assert_not_called()


class RunPrimingTests(unittest.TestCase):
    def test_first_cycle_ingests_but_sends_no_alert(self):
        # Cold start: every item in every feed is a fresh insert. Alerting on
        # that first batch would fire hundreds of headlines at once.
        fresh = [_row(title="台積電大漲")]

        with mock.patch("src.news.watch.poll_once", return_value=fresh), \
             mock.patch("src.news.watch.load_alert_terms", return_value=TERMS), \
             mock.patch("src.news.watch.telegram.send") as send:
            watch.run(poll_seconds=0, max_cycles=1)

        send.assert_not_called()

    def test_second_cycle_alerts_on_matching_rows(self):
        fresh = [_row(title="台積電大漲")]

        with mock.patch("src.news.watch.poll_once", return_value=fresh), \
             mock.patch("src.news.watch.load_alert_terms", return_value=TERMS), \
             mock.patch("src.news.watch.telegram.send") as send:
            watch.run(poll_seconds=0, max_cycles=2)

        send.assert_called_once()
        self.assertIn("2330", send.call_args.args[0])

    def test_non_matching_rows_produce_no_message(self):
        fresh = [_row(title="ECB holds rates steady", lang="en")]

        with mock.patch("src.news.watch.poll_once", return_value=fresh), \
             mock.patch("src.news.watch.load_alert_terms", return_value=TERMS), \
             mock.patch("src.news.watch.telegram.send") as send:
            watch.run(poll_seconds=0, max_cycles=2)

        send.assert_not_called()

    def test_a_failed_cycle_does_not_kill_the_loop(self):
        # The poller is a long-running service; one bad cycle (feed 500s, DB
        # blip) has to be survivable or a restart is needed to resume.
        calls = {"n": 0}

        def flaky(cache):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("db went away")
            return []

        with mock.patch("src.news.watch.poll_once", side_effect=flaky), \
             mock.patch("src.news.watch.load_alert_terms", return_value=TERMS), \
             mock.patch("src.news.watch.telegram.send"):
            watch.run(poll_seconds=0, max_cycles=3)

        self.assertEqual(calls["n"], 3)


if __name__ == "__main__":
    unittest.main()
