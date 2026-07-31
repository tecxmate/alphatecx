"""The margin harvest gap: a failure that recorded itself as a success.

TWSE publishes 融資融券彙總 after the 16:30 harvest window, so the nightly
`fetch_all_margin(target)` routinely returns nothing. That was logged as
`empty`, `get_ingested_dates` read `empty` as "confirmed holiday, skip
forever", and the day could never be retried — `--only margin` reported
"29 skipped, 0 rows" while the endpoint served the data fine. Every session
from ~2026-07-01 to 07-30 went missing this way while T86 ingested normally,
and Risk Guard's M1 margin subitem scored blind for a month.

Two independent guards, one per failure mode:
  - an `empty` on a real trading day is retryable (calendar-aware skip list);
  - each run sweeps recent sessions that still have no rows, so a late publish
    lands on the next run instead of being lost.
"""
import sys
import types
import unittest
from datetime import date
from unittest import mock

for _name in ("polars", "psycopg_pool", "psycopg"):
    if _name not in sys.modules:
        _mod = types.ModuleType(_name)
        _mod.ConnectionPool = object
        _mod.DataFrame = object
        sys.modules[_name] = _mod

from src.harvester import daily, loader  # noqa: E402


class SkipListTests(unittest.TestCase):
    """`empty` must no longer mean two different things."""

    def _run(self, rows):
        cur = mock.MagicMock()
        cur.fetchall.return_value = rows
        with mock.patch.object(loader, "cur") as ctx:
            ctx.return_value.__enter__.return_value = cur
            result = loader.get_ingested_dates("twse_margin")
        return result, cur.execute.call_args.args[0]

    def test_the_query_consults_the_calendar(self):
        # The fix lives in SQL, so this is where it has to be asserted: an
        # `empty` row only counts as skippable when the market was shut.
        _, sql = self._run([])
        self.assertIn("market_holidays", sql)
        self.assertIn("ISODOW", sql)
        self.assertIn("status = 'ok'", sql)

    def test_returns_the_dates_the_query_selected(self):
        result, _ = self._run([(date(2026, 7, 30),), (date(2026, 7, 29),)])
        self.assertEqual(result, {"2026-07-30", "2026-07-29"})

    def test_null_target_dates_are_dropped(self):
        result, _ = self._run([(None,), (date(2026, 7, 30),)])
        self.assertEqual(result, {"2026-07-30"})


class MissingSessionsTests(unittest.TestCase):
    def test_asks_for_sessions_with_no_margin_rows(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [(date(2026, 7, 29),), (date(2026, 7, 30),)]
        with mock.patch.object(loader, "cur") as ctx:
            ctx.return_value.__enter__.return_value = cur
            out = loader.margin_sessions_missing(days=10)
        self.assertEqual(out, ["2026-07-29", "2026-07-30"])
        sql, params = cur.execute.call_args.args
        # Keyed off the data, not ingestion_log, so it repairs the gap whatever
        # caused it — including a log row that lied.
        self.assertIn("raw_twse_margin", sql)
        self.assertIn("raw_twse_index", sql)
        self.assertEqual(params, (10,))


class CatchupSelectionTests(unittest.TestCase):
    def test_todays_session_is_not_queued_twice(self):
        with mock.patch.object(loader, "margin_sessions_missing",
                               return_value=["2026-07-29", "2026-07-30"]):
            self.assertEqual(daily._margin_catchup("20260730"), ["20260729"])

    def test_is_capped_so_a_long_outage_does_not_stall_the_run(self):
        with mock.patch.object(
                loader, "margin_sessions_missing",
                return_value=[f"2026-07-{d:02d}" for d in range(1, 20)]):
            self.assertEqual(len(daily._margin_catchup("20260730")),
                             daily._MARGIN_CATCHUP_LIMIT)

    def test_oldest_first_so_the_gap_closes_from_the_far_end(self):
        with mock.patch.object(loader, "margin_sessions_missing",
                               return_value=["2026-07-27", "2026-07-28"]):
            self.assertEqual(daily._margin_catchup("20260730"),
                             ["20260727", "20260728"])

    def test_a_lookup_failure_never_costs_the_run_its_normal_fetch(self):
        with mock.patch.object(loader, "margin_sessions_missing",
                               side_effect=RuntimeError("db down")):
            self.assertEqual(daily._margin_catchup("20260730"), [])

    def test_nothing_missing_means_no_extra_requests(self):
        with mock.patch.object(loader, "margin_sessions_missing", return_value=[]):
            self.assertEqual(daily._margin_catchup("20260730"), [])


if __name__ == "__main__":
    unittest.main()
