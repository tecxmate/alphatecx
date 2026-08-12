"""Console pages built from live state — against the REAL shapes of their reads.

Why this file exists separately from test_console.py: the first version of the
overview test mocked `query_data_status` with a *list of row dicts*, which is
what the author assumed it returned. It actually returns a single dict of
`{table_counts, latest_t86_date, recent_ingestions}` (db_v2.py). The test passed,
and `/d/<token>/` raised AttributeError in production on every request — the mock
had encoded the mistake instead of catching it.

So every fixture below is copied from the shape the real function constructs, and
the docstring names where. A mock is only as good as its fidelity to the contract
it stands in for.
"""
import os
import unittest
from importlib.util import find_spec
from unittest.mock import patch

os.environ.setdefault("OAUTH_SIGNING_KEY", "test-signing-key-not-a-real-secret")
os.environ.setdefault("OAUTH_PASSWORD", "test-password")
os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")

if find_spec("psycopg_pool") and find_spec("mcp"):
    from mcp_server.api import console_pages
else:
    console_pages = None


def _data_status() -> dict:
    """Exactly the shape db_v2.query_data_status() returns (db_v2.py, tail)."""
    return {
        "table_counts": {
            "raw_twse_t86": 412033, "raw_twse_holdings": 98120,
            "raw_twse_margin": 114882, "raw_twse_ohlcv": 220144,
            "raw_monthly_revenue": 8801, "dim_ticker": 1043,
        },
        "latest_t86_date": "2026-08-11",
        "recent_ingestions": [
            {"source": "twse_t86", "target_date": "2026-08-11", "rows_upserted": 1043,
             "status": "ok", "finished_at": "2026-08-11T08:41:02Z"},
            {"source": "twse_margin", "target_date": "2026-08-11", "rows_upserted": 0,
             "status": "empty", "finished_at": "2026-08-11T08:39:55Z"},
        ],
    }


def _market_daily() -> dict:
    """`SELECT * FROM rg_market_daily` — the columns rg_status reads, with the
    scored subitems under `reasons` (verified against a live rg_status call)."""
    return {
        "date": "2026-08-11", "risk_light": "green", "risk_score": 2,
        "taiex_close": 45120.72, "taiex_pct": 0.43,
        "reasons": [
            {"id": 1, "name": "trend", "points": 0, "detail": "站上均線",
             "inputs": {"ma20": 43615.12, "ma60": 43810.5, "close": 45120.72},
             "data_missing": False},
            {"id": 3, "name": "margin", "points": 0, "detail": "融資或指數報酬資料缺漏",
             "inputs": {"taiex_ret_5d_pct": 4.059, "margin_chg_5d_pct": None},
             "data_missing": True},
            {"id": 4, "name": "futures", "points": 2, "detail": "外資期貨淨空 88,924 口",
             "inputs": {"window": 5, "threshold": 20000, "fut_net_oi_chg_5d": -1066.0,
                        "fut_foreign_net_oi": -88924.0},
             "data_missing": False},
        ],
    }


@unittest.skipIf(console_pages is None, "server deps not installed")
class OverviewShapeTests(unittest.TestCase):
    def test_renders_against_the_real_return_shape(self):
        # The regression: this raised AttributeError('str' has no 'get') in prod
        # because a dict was iterated as a list of rows.
        with patch.object(console_pages.db_v2, "query_data_status",
                          return_value=_data_status()):
            html = console_pages.overview_html(57)
        self.assertIn("412,033", html)          # a real count, formatted
        self.assertIn("2026-08-11", html)       # the session it holds

    def test_each_dataset_says_what_it_is(self):
        # "Rows: 412,033" is not information without this.
        with patch.object(console_pages.db_v2, "query_data_status",
                          return_value=_data_status()):
            html = console_pages.overview_html(57)
        self.assertIn("Institutional flow", html)
        self.assertIn("borrowed money", html)   # margin, in plain words

    def test_recent_harvest_runs_are_shown_with_their_result(self):
        with patch.object(console_pages.db_v2, "query_data_status",
                          return_value=_data_status()):
            html = console_pages.overview_html(57)
        self.assertIn("twse_margin", html)
        self.assertIn("empty", html)

    def test_unreachable_database_still_renders_navigation(self):
        with patch.object(console_pages.db_v2, "query_data_status",
                          side_effect=RuntimeError("down")):
            html = console_pages.overview_html(0)
        self.assertIn("unreachable", html)
        self.assertIn("atx-nav", html)


@unittest.skipIf(console_pages is None, "server deps not installed")
class FreshnessWordsTests(unittest.TestCase):
    """Dates are meaningless to a reader who does not know the trading calendar."""

    def test_same_day_and_previous_day_read_as_healthy(self):
        self.assertEqual(console_pages._freshness_words("2026-08-11", "2026-08-11")[0], "ok")
        self.assertIn("yesterday",
                      console_pages._freshness_words("2026-08-10", "2026-08-11")[1])

    def test_a_weekend_gap_is_not_reported_as_a_problem(self):
        # Monday reading Friday's session is healthy, not three days stale.
        cls, words = console_pages._freshness_words("2026-08-07", "2026-08-10")
        self.assertEqual(cls, "ok")
        self.assertIn("weekend", words)

    def test_a_genuinely_stalled_harvest_is_flagged(self):
        cls, words = console_pages._freshness_words("2026-07-20", "2026-08-11")
        self.assertEqual(cls, "bad")
        self.assertIn("stalled", words)

    def test_never_ingested_is_distinct_from_stale(self):
        self.assertEqual(console_pages._freshness_words(None, "2026-08-11")[1],
                         "never ingested")


@unittest.skipIf(console_pages is None, "server deps not installed")
class MarketPageTests(unittest.TestCase):
    def test_renders_the_light_and_its_score(self):
        with patch.object(console_pages.rg_db, "latest_market_daily",
                          return_value=_market_daily()):
            html = console_pages.market_html()
        self.assertIn("Normal conditions", html)     # green, in words
        self.assertIn("risk score", html)

    def test_every_check_states_what_it_measures(self):
        with patch.object(console_pages.rg_db, "latest_market_daily",
                          return_value=_market_daily()):
            html = console_pages.market_html()
        self.assertIn("moving averages", html)       # trend, explained
        self.assertIn("borrowed money", html)        # margin, explained

    def test_thresholds_come_from_the_scorer_not_this_page(self):
        # A page that retypes thresholds eventually disagrees with the number it
        # is explaining. These must track rg.config.
        with patch.object(console_pages.rg_db, "latest_market_daily",
                          return_value=_market_daily()):
            html = console_pages.market_html()
        self.assertIn(f"+{console_pages.cfg.MARGIN_GROWTH_PCT:.1f}%", html)
        self.assertIn(f"{console_pages.cfg.FUT_ADD_SHORT_HEAVY:,}", html)

    def test_a_missing_input_is_explained_not_scored_as_calm(self):
        with patch.object(console_pages.rg_db, "latest_market_daily",
                          return_value=_market_daily()):
            html = console_pages.market_html()
        self.assertIn("no data", html)
        self.assertIn("calm is the dangerous default", html)

    def test_a_triggered_check_says_why_it_added_to_the_score(self):
        with patch.object(console_pages.rg_db, "latest_market_daily",
                          return_value=_market_daily()):
            html = console_pages.market_html()
        self.assertIn("Triggered:", html)
        self.assertIn("added 2 to the score", html)

    def test_no_light_yet_explains_how_to_produce_one(self):
        with patch.object(console_pages.rg_db, "latest_market_daily",
                          return_value=None):
            html = console_pages.market_html()
        self.assertIn("riskguard.pipeline", html)

    def test_unreachable_database_does_not_raise(self):
        with patch.object(console_pages.rg_db, "latest_market_daily",
                          side_effect=RuntimeError("down")):
            html = console_pages.market_html()
        self.assertIn("atx-nav", html)


if __name__ == "__main__":
    unittest.main()
