"""The two DB-facing modules: mcp_server/api/rg/db.py and riskguard/store.py.

These wrap SQL, so the tests substitute the fetch/cursor layer and assert on
the shaping either side of it — what gets asked for, and what comes back. That
catches the real defect class here (a wrong column, a stale row treated as
fresh, a lookback that silently shortens) without pretending to verify the SQL
itself, which only a live Postgres can do.

`build_metrics` gets the most attention: it is where every M1 input is
assembled, and where a stale-but-present value is indistinguishable from a
fresh one unless something checks.
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

from mcp_server.api.rg import db as rg_db  # noqa: E402
from riskguard import store  # noqa: E402


class FuturesChangeTests(unittest.TestCase):
    SERIES = {"2026-07-23": -70_000, "2026-07-24": -76_260,
              "2026-07-27": -75_000, "2026-07-28": -82_255,
              "2026-07-29": -82_785, "2026-07-30": -81_017}

    def test_change_is_measured_against_the_session_window_back(self):
        level, chg = store._fut_change(self.SERIES, "2026-07-30", 5)
        self.assertEqual(level, -81_017)
        self.assertEqual(chg, -81_017 - (-70_000))

    def test_too_short_a_series_yields_the_level_but_no_change(self):
        level, chg = store._fut_change(self.SERIES, "2026-07-30", 20)
        self.assertEqual(level, -81_017)
        self.assertIsNone(chg)

    def test_a_session_absent_from_the_series_yields_nothing(self):
        # Never guess a level for a day TAIFEX did not report.
        self.assertEqual(store._fut_change(self.SERIES, "2026-07-31", 5), (None, None))

    def test_empty_or_missing_series_is_safe(self):
        self.assertEqual(store._fut_change({}, "2026-07-30", 5), (None, None))
        self.assertEqual(store._fut_change(None, "2026-07-30", 5), (None, None))

    def test_later_sessions_do_not_leak_into_the_lookback(self):
        # Only history up to `as_of` may be used, or the replay would peek.
        _, chg = store._fut_change(self.SERIES, "2026-07-28", 2)
        self.assertEqual(chg, -82_255 - (-76_260))


class PctChangeTests(unittest.TestCase):
    def test_ordinary_change(self):
        self.assertEqual(store._pct_change(110.0, 100.0), 10.0)

    def test_zero_or_missing_operands_return_none_not_infinity(self):
        for a, b in ((None, 100.0), (100.0, None), (100.0, 0), (0, 100.0)):
            self.assertIsNone(store._pct_change(a, b))


class BuildMetricsTests(unittest.TestCase):
    """Everything M1 scores comes through here."""

    def setUp(self):
        self.taiex = [{"date": f"2026-07-{30 - i:02d}", "close": 40000.0 - i * 10,
                       "change_pct": -0.26} for i in range(29)]
        mock.patch.object(store, "taiex_series", return_value=self.taiex).start()
        self.margins = mock.patch.object(store, "margin_totals").start()
        mock.patch.object(store, "breadth_history", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)
        self.margins.return_value = [
            {"date": "2026-07-30", "margin_balance": 8_224_773.0},
            *[{"date": f"2026-07-{29 - i:02d}", "margin_balance": 9_000_000.0}
              for i in range(9)],
        ]

    def test_moving_average_needs_enough_history(self):
        m = store.build_metrics("2026-07-30", None)
        self.assertIsNotNone(m["ma20"])   # 29 closes is enough for MA20
        self.assertIsNone(m["ma60"])      # but not for MA60

    def test_margin_from_an_earlier_session_is_dropped_not_reused(self):
        # The July 2026 failure: the feed died on ~1 July, margin_totals kept
        # returning 6/29, and it scored as if it were today's.
        self.margins.return_value = [
            {"date": "2026-06-29", "margin_balance": 9_495_889.0}] * 8
        m = store.build_metrics("2026-07-30", None)
        self.assertIsNone(m["margin_balance"])
        self.assertIsNone(m["margin_chg_5d_pct"])

    def test_fresh_margin_is_used(self):
        m = store.build_metrics("2026-07-30", None)
        self.assertEqual(m["margin_balance"], 8_224_773.0)
        self.assertLess(m["margin_chg_5d_pct"], 0)

    def test_todays_breadth_counts_are_carried_through(self):
        m = store.build_metrics("2026-07-30", {"adv_count": 224, "dec_count": 775})
        self.assertEqual((m["adv_count"], m["dec_count"]), (224, 775))
        self.assertAlmostEqual(m["adv_ratio_5d"], 224 / 999, places=3)

    def test_supplied_breadth_history_beats_the_db(self):
        prior = [{"date": "2026-07-29", "adv_count": 900, "dec_count": 100}]
        m = store.build_metrics("2026-07-30", {"adv_count": 100, "dec_count": 900},
                                breadth_prior=prior)
        # Mean of 0.1 and 0.9, not 0.1 alone.
        self.assertAlmostEqual(m["adv_ratio_5d"], 0.5, places=2)

    def test_no_breadth_at_all_leaves_the_ratio_absent(self):
        m = store.build_metrics("2026-07-30", None)
        self.assertIsNone(m["adv_ratio_5d"])

    def test_closes_are_exposed_for_the_hysteresis_context(self):
        m = store.build_metrics("2026-07-30", None)
        self.assertEqual(m["_closes"][0], 40000.0)

    def test_a_session_missing_from_the_index_has_no_change_pct(self):
        m = store.build_metrics("2026-07-31", None)
        self.assertIsNone(m["taiex_pct"])


class UpsertPositionTests(unittest.TestCase):
    def test_only_whitelisted_fields_reach_the_statement(self):
        cur = mock.MagicMock()
        with mock.patch.object(store, "cur") as ctx:
            ctx.return_value.__enter__.return_value = cur
            store.upsert_position("2344", cost=51.5, note="x", bogus="drop me")
        sql, params = cur.execute.call_args.args
        self.assertIn("cost", sql)
        self.assertNotIn("bogus", sql)
        self.assertIn(51.5, params)

    def test_omitted_fields_are_left_untouched(self):
        # `/setpos 2344 exit=47.8` must not blank a cost set earlier.
        cur = mock.MagicMock()
        with mock.patch.object(store, "cur") as ctx:
            ctx.return_value.__enter__.return_value = cur
            store.upsert_position("2344", exit_price=47.8)
        sql = cur.execute.call_args.args[0]
        self.assertIn("exit_price", sql)
        self.assertNotIn("cost", sql)


class LastTradingDayTests(unittest.TestCase):
    def test_uses_the_newest_index_row(self):
        cur = mock.MagicMock()
        cur.fetchone.return_value = (date(2026, 7, 30),)
        with mock.patch.object(store, "cur") as ctx:
            ctx.return_value.__enter__.return_value = cur
            self.assertEqual(store.last_trading_day("2026-07-31"), "2026-07-30")

    def test_falls_back_to_yesterday_when_the_table_is_empty(self):
        cur = mock.MagicMock()
        cur.fetchone.return_value = (None,)
        with mock.patch.object(store, "cur") as ctx:
            ctx.return_value.__enter__.return_value = cur
            self.assertEqual(store.last_trading_day("2026-07-31"), "2026-07-30")


class StoreWriteTests(unittest.TestCase):
    """The rg_* write helpers. Thin SQL, but the parameters must be right."""

    def setUp(self):
        self.cur = mock.MagicMock()
        ctx = mock.patch.object(store, "cur").start()
        ctx.return_value.__enter__.return_value = self.cur
        self.addCleanup(mock.patch.stopall)

    def test_record_alert_defaults_the_dedup_key_to_the_ticker(self):
        self.cur.fetchone.return_value = (7,)
        self.assertEqual(store.record_alert("stop_exit", "critical", "m",
                                            ticker_id="2324"), 7)
        params = self.cur.execute.call_args.args[1]
        self.assertIn("2324", params)

    def test_record_alert_accepts_an_explicit_dedup_key(self):
        # Ticker-less alerts must supply their own or they collapse together.
        self.cur.fetchone.return_value = (8,)
        store.record_alert("settlement_gap", "critical", "m",
                           dedup_key="2026-07-28")
        self.assertIn("2026-07-28", self.cur.execute.call_args.args[1])

    def test_record_alert_returns_none_when_the_unique_index_rejects_it(self):
        self.cur.fetchone.return_value = None
        self.assertIsNone(store.record_alert("stop_exit", "critical", "m",
                                             ticker_id="2324"))

    def test_unpushed_critical_is_bounded_to_recent_days(self):
        # A stop breached two weeks ago is stale advice, not an emergency.
        self.cur.fetchall.return_value = [(7, "msg")]
        rows = store.unpushed_critical()
        self.assertEqual(rows, [{"id": 7, "message": "msg"}])
        sql, params = self.cur.execute.call_args.args
        self.assertIn("make_interval", sql)
        self.assertIn("NOT pushed", sql)
        self.assertIn(3, params)

    def test_mark_pushed_targets_one_row(self):
        store.mark_pushed(7)
        self.assertIn(7, self.cur.execute.call_args.args[1])

    def test_record_trade_writes_the_fill_and_folds_the_settlement(self):
        store.record_trade("2026-07-24", "2026-07-28", "2344", "buy",
                           51.5, 3, -154_500.0)
        self.assertEqual(self.cur.execute.call_count, 2)
        fold = self.cur.execute.call_args_list[1].args[0]
        # Accumulates rather than overwrites — two fills settling the same day
        # must sum, not replace one another.
        self.assertIn("rg_settlements.net_amount + EXCLUDED.net_amount", fold)

    def test_record_balance_appends(self):
        store.record_balance(476_276.0)
        self.assertIn(476_276.0, self.cur.execute.call_args.args[1])

    def test_latest_balance_is_none_when_never_reported(self):
        self.cur.fetchone.return_value = None
        self.assertIsNone(store.latest_balance())

    def test_set_no_trade_day_upserts_the_reason(self):
        store.set_no_trade_day("2026-08-04", "節律日")
        sql, params = self.cur.execute.call_args.args
        self.assertIn("ON CONFLICT", sql)
        self.assertIn("節律日", params)

    def test_snapshot_held_pct_only_covers_monitored_names(self):
        self.cur.rowcount = 4
        self.assertEqual(store.snapshot_held_pct("2026-07-30"), 4)
        self.assertIn("JOIN rg_positions", self.cur.execute.call_args.args[0])

    def test_closes_for_short_circuits_on_an_empty_list(self):
        self.assertEqual(store.closes_for([], "2026-07-30"), {})
        self.cur.execute.assert_not_called()

    def test_active_positions_coerces_numerics_to_float(self):
        self.cur.description = [mock.Mock(name=n) for n in range(10)]
        for m, n in zip(self.cur.description,
                        ["ticker_id", "name", "kind", "cost", "qty_lots",
                         "warn_price", "exit_price", "hard_stop_pct", "note",
                         "active"], strict=True):
            m.name = n
        self.cur.fetchall.return_value = [
            ("2324", "仁寶", "position", 30, 3, 29.5, 28.6, 10, None, True)]
        rows = store.active_positions()
        self.assertIsInstance(rows[0]["cost"], float)

    def test_prev_market_day_is_none_on_a_cold_start(self):
        self.cur.fetchone.return_value = None
        self.assertIsNone(store.prev_market_day("2026-07-30"))

    def test_upsert_market_daily_sends_reasons_as_json(self):
        store.upsert_market_daily(
            {"date": "2026-07-30", "taiex_close": 1.0, "taiex_pct": -0.26,
             "ma20": 2.0, "ma60": 3.0, "taiex_ret_5d_pct": -1.0,
             "adv_count": 224, "dec_count": 775, "adv_ratio_5d": 0.27,
             "margin_balance": None, "margin_chg_5d_pct": None,
             "fut_foreign_net_oi": -81017},
            "red", 6, [{"id": 1, "points": 3}])
        params = self.cur.execute.call_args.args[1]
        self.assertIn('"points": 3', params[-1])


class RgDbTests(unittest.TestCase):
    """The MCP read layer. Thin, but the shaping still has to be right."""

    def setUp(self):
        self.fetch = mock.patch.object(rg_db, "_fetch").start()
        mock.patch.object(rg_db, "_serialize", side_effect=lambda r: r).start()
        self.addCleanup(mock.patch.stopall)

    def test_latest_market_daily_returns_none_when_empty(self):
        self.fetch.return_value = []
        self.assertIsNone(rg_db.latest_market_daily())

    def test_positions_excludes_inactive_by_default(self):
        self.fetch.return_value = []
        rg_db.positions()
        self.assertIn("WHERE active", self.fetch.call_args.args[0])

    def test_positions_can_include_inactive(self):
        self.fetch.return_value = []
        rg_db.positions(include_inactive=True)
        self.assertNotIn("WHERE active", self.fetch.call_args.args[0])

    def test_latest_closes_short_circuits_on_an_empty_list(self):
        self.assertEqual(rg_db.latest_closes([]), {})
        self.fetch.assert_not_called()

    def test_latest_closes_skips_null_prices(self):
        self.fetch.return_value = [{"ticker_id": "2344", "close": 51.5},
                                   {"ticker_id": "8299", "close": None}]
        self.assertEqual(rg_db.latest_closes(["2344", "8299"]), {"2344": 51.5})

    def test_gain_5d_needs_six_closes(self):
        self.fetch.return_value = [{"close": 100.0}] * 5
        self.assertIsNone(rg_db.gain_5d_pct("2344"))

    def test_gain_5d_computes_the_trailing_return(self):
        self.fetch.return_value = [{"close": c} for c in
                                   (125.9, 120.0, 115.0, 110.0, 105.0, 100.0)]
        self.assertEqual(rg_db.gain_5d_pct("3231"), 25.9)

    def test_no_trade_reason_is_none_when_the_day_is_clear(self):
        self.fetch.return_value = []
        self.assertIsNone(rg_db.no_trade_reason("2026-07-31"))

    def test_checklist_facts_leaves_unbuilt_modules_as_none(self):
        # M3 and M6 must report skipped, never a fabricated pass or fail.
        # Call order inside checklist_facts: market, positions, balance,
        # gain_5d closes, no_trade_reason.
        self.fetch.side_effect = [
            [{"risk_light": "red"}],
            [{"name": "華邦電", "note": "", "active": True}],
            [{"amount": 100000.0, "ts": "2026-07-30"}],
            [{"close": c} for c in (51.5, 51, 50, 49, 48, 47)],
            [],
        ]
        facts = rg_db.checklist_facts("2344", "2026-07-31")
        self.assertIsNone(facts["sector_rank"])
        self.assertIsNone(facts["is_disposition"])

    def test_checklist_facts_flags_a_blacklisted_note(self):
        self.fetch.side_effect = [
            [{"risk_light": "green"}],
            [{"name": "國巨", "note": "拉黑:2026/7 週期 -55%", "active": False}],
            [],
            [],
            [],
        ]
        facts = rg_db.checklist_facts("2327", "2026-07-31")
        self.assertTrue(facts["blacklisted"])


if __name__ == "__main__":
    unittest.main()
