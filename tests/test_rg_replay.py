"""The M1 replay harness.

Worth testing in its own right: this is the tool that decides whether the
scorer is calibrated, and it has already been wrong once. Running it without
`--write` used to leave `rg_market_daily` empty, so the 5-day breadth mean
collapsed to a single session and report-only disagreed with `--write` about
the same day — which produced two false "7/7 PASS" results. The
`breadth_prior` carry now pins that.

Everything below is mocked: no DB, no network.
"""
import sys
import types
import unittest
from unittest import mock

for _name in ("polars", "psycopg_pool", "psycopg"):
    if _name not in sys.modules:
        _mod = types.ModuleType(_name)
        _mod.ConnectionPool = object
        _mod.DataFrame = object
        sys.modules[_name] = _mod

from riskguard import replay  # noqa: E402

SESSIONS = ["2026-07-28", "2026-07-29", "2026-07-30"]


def _series(dates):
    return [{"date": d, "close": 100.0 - i, "change_pct": -1.0}
            for i, d in enumerate(reversed(dates))]


def _metrics(as_of, **over):
    base = {"date": as_of, "taiex_close": 100.0, "taiex_pct": -4.0,
            "ma20": 110.0, "ma60": 105.0, "taiex_ret_5d_pct": -5.0,
            "adv_count": 96, "dec_count": 931, "adv_ratio_5d": 0.30,
            "margin_balance": None, "margin_chg_5d_pct": None,
            "fut_foreign_net_oi": -80_000, "fut_net_oi_chg_5d": -9_000,
            "_closes": [100.0, 101.0, 102.0]}
    base.update(over)
    return base


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.store = mock.patch.object(replay, "store").start()
        self.sources = mock.patch.object(replay, "sources").start()
        self.addCleanup(mock.patch.stopall)
        self.store.taiex_series.return_value = _series(SESSIONS)
        self.store.build_metrics.side_effect = lambda d, *a, **k: _metrics(d)
        self.sources.fetch_breadth.return_value = {"adv_count": 96, "dec_count": 931}
        self.sources.fetch_foreign_futures_oi_series.return_value = {
            d: -80_000 for d in SESSIONS}

    def test_scores_every_session_in_chronological_order(self):
        rows = replay.replay("2026-07-28", "2026-07-30")
        self.assertEqual([r["date"] for r in rows], SESSIONS)

    def test_report_only_does_not_persist(self):
        replay.replay("2026-07-28", "2026-07-30")
        self.store.upsert_market_daily.assert_not_called()

    def test_write_persists_every_session(self):
        replay.replay("2026-07-28", "2026-07-30", write=True)
        self.assertEqual(self.store.upsert_market_daily.call_count, len(SESSIONS))

    def test_breadth_history_is_carried_in_memory_not_read_from_the_db(self):
        # The bug this guards: without the carry, each session saw an empty
        # history and its "5-day mean" became that one day's ratio.
        replay.replay("2026-07-28", "2026-07-30")
        priors = [c.kwargs["breadth_prior"]
                  for c in self.store.build_metrics.call_args_list]
        self.assertEqual(len(priors[0]), 0)     # first session has no history
        self.assertEqual(len(priors[1]), 1)     # then one, then two
        self.assertEqual(len(priors[2]), 2)
        self.assertEqual(priors[2][0]["date"], "2026-07-29")   # newest first

    def test_taifex_is_fetched_once_for_the_whole_window(self):
        replay.replay("2026-07-28", "2026-07-30")
        self.sources.fetch_foreign_futures_oi_series.assert_called_once()

    def test_empty_index_table_reports_nothing_rather_than_crashing(self):
        self.store.taiex_series.return_value = []
        self.assertEqual(replay.replay("2026-07-28", "2026-07-30"), [])

    def test_sessions_outside_the_range_are_excluded(self):
        self.store.taiex_series.return_value = _series(["2026-07-20"] + SESSIONS)
        rows = replay.replay("2026-07-28", "2026-07-30")
        self.assertNotIn("2026-07-20", [r["date"] for r in rows])

    def test_a_missing_breadth_day_is_not_carried_as_history(self):
        self.sources.fetch_breadth.return_value = None
        replay.replay("2026-07-28", "2026-07-30")
        priors = [c.kwargs["breadth_prior"]
                  for c in self.store.build_metrics.call_args_list]
        self.assertTrue(all(p == [] for p in priors))


class ReportTests(unittest.TestCase):
    def _row(self, date, light, score=6):
        return {"date": date, "pct": -4.0, "score": score, "raw": light,
                "light": light, "why": "", "missing": [],
                "points": {"trend": 3, "breadth": 2, "margin": 0,
                           "futures": 0, "day_drop": 2}}

    def test_returns_zero_when_every_acceptance_row_passes(self):
        rows = [self._row(d, "red") for d in replay.EXPECTED]
        self.assertEqual(replay.report(rows), 0)

    def test_counts_a_wrong_light_as_a_failure(self):
        rows = [self._row(d, "red") for d in replay.EXPECTED]
        rows[0] = self._row(rows[0]["date"], "green")
        self.assertEqual(replay.report(rows), 1)

    def test_an_unscored_acceptance_row_is_not_treated_as_a_pass(self):
        # PRD §7 asks for coverage; a row with no data is an unverified claim,
        # so it counts against the result rather than silently vanishing.
        rows = [self._row(d, "red") for d in list(replay.EXPECTED)[:-1]]
        self.assertEqual(replay.report(rows), 1)

    def test_known_misses_are_reported_but_never_counted_as_failures(self):
        rows = [self._row(d, "red") for d in replay.EXPECTED]
        rows.append(self._row("2026-06-08", "green"))
        self.assertEqual(replay.report(rows), 0)

    def test_yellow_satisfies_a_row_that_accepts_red_or_yellow(self):
        self.assertIn("yellow", replay.EXPECTED["2026-07-07"])
        rows = [self._row(d, "red") for d in replay.EXPECTED]
        rows[list(replay.EXPECTED).index("2026-07-07")] = \
            self._row("2026-07-07", "yellow")
        self.assertEqual(replay.report(rows), 0)

    def test_0731_must_never_be_allowed_to_go_green(self):
        # The +8.0% session. PRD §7: red → at most a yellow candidate.
        self.assertNotIn("green", replay.EXPECTED["2026-07-31"])


if __name__ == "__main__":
    unittest.main()
