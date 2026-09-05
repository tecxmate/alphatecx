"""One oversized article URL must not discard a whole news run.

WHAT HAPPENED. `raw_news.url` is the PRIMARY KEY, so every URL becomes a btree
index row, and Postgres refuses one over 2704 bytes:

    psycopg.errors.ProgramLimitExceeded: index row size 2848 exceeds btree
    version 4 maximum 2704 for index "raw_news_pkey"

A Google News redirect URL (base64 payload, not a readable path) crossed the
limit. The raise is not the real damage: `harvest()` wraps EVERY source in one
`atomic()` transaction, so the exception rolled back the entire run — every
article from every feed, not just the offending row. Six of forty runs died
that way over 2026-09-02..04. And `src/news/watch.py` imports this same
`_upsert`, so the Zeabur poller hit it on every cycle those articles were live.

The fix is a pre-filter, not a caught exception, and that distinction is the
point of `test_the_guard_runs_before_execute_not_around_it`: a failed statement
poisons the surrounding transaction, so catching the error would leave every
later row failing with "current transaction is aborted" — a partial fix that
looks like a whole one.
"""

from __future__ import annotations

import pytest

from src.news import harvest


class _FakeCursor:
    """Records executed rows. Raises like Postgres if a URL would exceed the
    index limit, so the test exercises the real failure rather than a mock of
    the fix."""

    BTREE_MAX = 2704

    def __init__(self):
        self.executed: list[dict] = []
        self.poisoned = False

    def execute(self, _sql, row):
        if self.poisoned:
            raise RuntimeError("current transaction is aborted")
        if len(row["url"].encode("utf-8")) > self.BTREE_MAX:
            self.poisoned = True
            raise RuntimeError(
                f"index row size {len(row['url'])} exceeds btree version 4 "
                f'maximum {self.BTREE_MAX} for index "raw_news_pkey"'
            )
        self.executed.append(row)

    def fetchone(self):
        return (True,)


def _row(url: str, title: str) -> dict:
    return {
        "url": url, "source": "gnews-geo-tw", "feed_name": "Google News",
        "lang": "zh-Hant", "title": title, "title_hash": title,
        "raw_summary": None, "published_at": None,
    }


def _monster_url() -> str:
    """Shaped like the real thing: a Google News redirect whose base64 payload
    pushes it past the index limit."""
    return "https://news.google.com/rss/articles/" + ("A" * 2900)


class TestOversizedUrlDoesNotKillTheRun:
    def test_the_offending_article_is_skipped(self):
        c = _FakeCursor()
        inserted, skipped = harvest._upsert(c, [_row(_monster_url(), "huge")])
        assert inserted == []
        assert skipped == 1

    def test_every_other_article_in_the_batch_still_lands(self):
        """The regression that mattered: the run lost ALL articles, not one."""
        c = _FakeCursor()
        rows = [
            _row("https://example.com/a", "first"),
            _row(_monster_url(), "huge"),
            _row("https://example.com/b", "second"),
        ]
        inserted, skipped = harvest._upsert(c, rows)
        assert [r["title"] for r in inserted] == ["first", "second"]
        assert skipped == 1
        assert not c.poisoned, "a raise here would have rolled back the run"

    def test_the_guard_runs_before_execute_not_around_it(self):
        """A try/except would still have poisoned the transaction, leaving
        every later row failing with 'current transaction is aborted'."""
        c = _FakeCursor()
        harvest._upsert(c, [_row(_monster_url(), "huge"),
                            _row("https://example.com/ok", "after")])
        assert [r["title"] for r in c.executed] == ["after"]

    def test_a_normal_url_is_untouched(self):
        c = _FakeCursor()
        inserted, skipped = harvest._upsert(
            c, [_row("https://www.digitimes.com/news/a2026090501.html", "ok")]
        )
        assert len(inserted) == 1 and skipped == 0

    def test_the_limit_sits_below_the_btree_maximum(self):
        """2704 is the hard cap on the whole index row; the URL is only part of
        it, so the threshold must leave headroom rather than equal the cap."""
        assert harvest.MAX_URL_BYTES < _FakeCursor.BTREE_MAX

    def test_the_limit_is_measured_in_bytes_not_characters(self):
        """A percent-decoded CJK URL is far more bytes than characters; the cap
        Postgres enforces is bytes."""
        url = "https://example.com/" + ("台" * 900)   # 900 chars, 2700+ bytes
        assert len(url) < harvest.MAX_URL_BYTES
        assert len(url.encode("utf-8")) > harvest.MAX_URL_BYTES
        c = _FakeCursor()
        inserted, skipped = harvest._upsert(c, [_row(url, "cjk")])
        assert inserted == [] and skipped == 1

    def test_a_url_just_under_the_limit_still_inserts(self):
        c = _FakeCursor()
        url = "https://example.com/" + "a" * (harvest.MAX_URL_BYTES - 25)
        inserted, _ = harvest._upsert(c, [_row(url, "boundary")])
        assert len(inserted) == 1

    def test_the_skip_is_logged_loudly_enough_to_notice(self, caplog):
        """Silently dropping articles is how this class of bug hides. The
        warning has to name the source and the size."""
        c = _FakeCursor()
        with caplog.at_level("WARNING"):
            harvest._upsert(c, [_row(_monster_url(), "huge")])
        assert "gnews-geo-tw" in caplog.text
        assert str(harvest.MAX_URL_BYTES) in caplog.text


class TestExistingDedupStillWorks:
    def test_duplicate_titles_within_a_batch_are_still_collapsed(self):
        c = _FakeCursor()
        inserted, skipped = harvest._upsert(
            c, [_row("https://example.com/1", "same"),
                _row("https://example.com/2", "same")]
        )
        assert len(inserted) == 1 and skipped == 1

    def test_an_empty_batch_is_a_no_op(self):
        assert harvest._upsert(_FakeCursor(), []) == ([], 0)


@pytest.mark.parametrize("shared", ["_fetch_feed", "_upsert"])
def test_the_poller_uses_the_same_functions_so_it_gets_the_same_fix(shared):
    """`src/news/watch.py` imports these rather than copying them — which is
    why fixing _upsert fixes the Zeabur worker too. If that import is ever
    replaced with a local copy, this fails and says so."""
    import src.news.watch as watch
    assert getattr(watch, shared) is getattr(harvest, shared)
