"""Delivery guarantees in the post-close pipeline.

These cover the two states that look identical from the outside and are the
most dangerous to get wrong:

  - an alert that was recorded but never reached the phone;
  - a position whose stop was never checked, reported as "no alerts".

`riskguard.pipeline` imports `src.harvester.loader`, which pulls in polars, and
`store`/`send` both need real credentials. Everything is stubbed at module level
so these stay pure unit tests with no DB and no network.
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

from mcp_server.api.rg import stops  # noqa: E402
from riskguard import pipeline  # noqa: E402


def pos(**over):
    base = {"ticker_id": "2324", "name": "仁寶", "kind": "position",
            "cost": 30.0, "qty_lots": 3, "warn_price": 29.5,
            "exit_price": 28.6, "hard_stop_pct": 10, "active": True}
    base.update(over)
    return base


class ResendTests(unittest.TestCase):
    """PRD §6 補發 critical — write first, send second, retry what didn't land."""

    def test_undelivered_critical_alerts_are_resent_and_marked(self):
        pending = [{"id": 7, "message": "🚨 仁寶(2324) 收盤 29.05 ≤ 出場線 28.6"}]
        with mock.patch.object(pipeline.store, "unpushed_critical", return_value=pending), \
             mock.patch.object(pipeline, "send", return_value=True) as send, \
             mock.patch.object(pipeline.store, "mark_pushed") as mark:
            self.assertEqual(pipeline.flush_undelivered(), 1)
        send.assert_called_once_with(pending[0]["message"])
        mark.assert_called_once_with(7)

    def test_a_still_failing_send_is_not_marked_pushed(self):
        # It has to stay queued, or the next run would treat a second failure
        # as a delivered alert.
        pending = [{"id": 7, "message": "x"}]
        with mock.patch.object(pipeline.store, "unpushed_critical", return_value=pending), \
             mock.patch.object(pipeline, "send", return_value=False), \
             mock.patch.object(pipeline.store, "mark_pushed") as mark:
            self.assertEqual(pipeline.flush_undelivered(), 0)
        mark.assert_not_called()

    def test_nothing_pending_sends_nothing(self):
        with mock.patch.object(pipeline.store, "unpushed_critical", return_value=[]), \
             mock.patch.object(pipeline, "send") as send:
            self.assertEqual(pipeline.flush_undelivered(), 0)
        send.assert_not_called()

    def test_a_failed_send_leaves_the_row_unpushed_for_the_next_run(self):
        # The full trap: record succeeds, send fails. Without flush_undelivered
        # the de-dup index would suppress the re-record on the next run and the
        # alert would never be delivered at all.
        with mock.patch.object(pipeline.store, "record_alert", return_value=42), \
             mock.patch.object(pipeline, "send", return_value=False), \
             mock.patch.object(pipeline.store, "mark_pushed") as mark:
            delivered = pipeline._emit("stop_exit", "critical", "msg", ticker_id="2324")
        self.assertFalse(delivered)
        mark.assert_not_called()

    def test_duplicate_record_does_not_resend_inline(self):
        # record_alert returning None means the unique index rejected it.
        # Inline silence is correct; delivery is flush_undelivered's job.
        with mock.patch.object(pipeline.store, "record_alert", return_value=None), \
             mock.patch.object(pipeline, "send") as send:
            self.assertFalse(pipeline._emit("stop_exit", "critical", "msg",
                                            ticker_id="2324"))
        send.assert_not_called()


class UnpricedPositionTests(unittest.TestCase):
    """A position with no close was not checked — and must say so."""

    def test_position_without_a_close_is_reported(self):
        rows = stops.unpriced([pos(ticker_id="8299", name="群聯")], {})
        self.assertEqual([r["ticker_id"] for r in rows], ["8299"])

    def test_priced_position_is_not_reported(self):
        self.assertEqual(stops.unpriced([pos()], {"2324": 31.0}), [])

    def test_watch_names_are_not_reported(self):
        # A watch name has no stop to check, so an unchecked-stop warning about
        # one would be noise.
        self.assertEqual(stops.unpriced([pos(kind="watch")], {}), [])

    def test_inactive_positions_are_not_reported(self):
        self.assertEqual(stops.unpriced([pos(active=False)], {}), [])

    def test_stop_check_warns_instead_of_reporting_zero_alerts(self):
        positions = [pos(ticker_id="8299", name="群聯")]
        with mock.patch.object(pipeline.store, "active_positions", return_value=positions), \
             mock.patch.object(pipeline.store, "closes_for", return_value={}), \
             mock.patch.object(pipeline, "_emit", return_value=True) as emit:
            sent = pipeline.run_stop_check("2026-07-31")

        self.assertEqual(sent, 1)
        kinds = [c.args[0] for c in emit.call_args_list]
        self.assertEqual(kinds, ["stop_unchecked"])
        self.assertEqual(emit.call_args.kwargs["ticker_id"], "8299")

    def test_a_priced_position_that_is_fine_emits_nothing(self):
        with mock.patch.object(pipeline.store, "active_positions", return_value=[pos()]), \
             mock.patch.object(pipeline.store, "closes_for", return_value={"2324": 31.0}), \
             mock.patch.object(pipeline, "_emit", return_value=True) as emit:
            self.assertEqual(pipeline.run_stop_check("2026-07-31"), 0)
        emit.assert_not_called()


def _metrics(**over):
    base = {"date": "2026-07-30", "taiex_close": 39933.3, "taiex_pct": -0.26,
            "ma20": 44000.0, "ma60": 43000.0, "taiex_ret_5d_pct": -10.0,
            "adv_count": 224, "dec_count": 775, "adv_ratio_5d": 0.268,
            "margin_balance": None, "margin_chg_5d_pct": None,
            "fut_foreign_net_oi": -81_017, "fut_net_oi_chg_5d": -5_819,
            "_closes": [39933.3, 40039.18, 41603.36]}
    base.update(over)
    return base


class RiskLightTests(unittest.TestCase):
    def setUp(self):
        self.store = mock.patch.object(pipeline, "store").start()
        self.sources = mock.patch.object(pipeline, "sources").start()
        self.emit = mock.patch.object(pipeline, "_emit", return_value=True).start()
        self.addCleanup(mock.patch.stopall)
        self.sources.fetch_breadth.return_value = {"adv_count": 224, "dec_count": 775}
        self.sources.fetch_foreign_futures_oi_series.return_value = {"2026-07-30": -81_017}
        self.store.build_metrics.return_value = _metrics()
        self.store.prev_market_day.return_value = {
            "date": "2026-07-29", "risk_light": "red", "risk_score": 8}

    def test_computes_stores_and_reports_the_light(self):
        out = pipeline.run_risk_light("2026-07-30")
        self.assertEqual(out["light"], "red")
        self.store.upsert_market_daily.assert_called_once()

    def test_an_unchanged_light_is_not_pushed(self):
        # PRD §5 M1: only transitions are pushed. A light that speaks every day
        # stops being read.
        pipeline.run_risk_light("2026-07-30")
        self.emit.assert_not_called()

    def test_a_changed_light_is_pushed_and_keyed_on_the_new_colour(self):
        self.store.prev_market_day.return_value = {
            "date": "2026-07-29", "risk_light": "green", "risk_score": 0}
        pipeline.run_risk_light("2026-07-30")
        self.emit.assert_called_once()
        self.assertEqual(self.emit.call_args.args[0], "risk_light_change")
        self.assertEqual(self.emit.call_args.kwargs["dedup_key"], "red")

    def test_cold_start_publishes_and_pushes(self):
        self.store.prev_market_day.return_value = None
        out = pipeline.run_risk_light("2026-07-30")
        self.assertIsNone(out["prev_light"])
        self.emit.assert_called_once()

    def test_missing_subitems_are_surfaced_to_the_caller(self):
        self.store.build_metrics.return_value = _metrics(fut_net_oi_chg_5d=None)
        out = pipeline.run_risk_light("2026-07-30")
        self.assertIn("futures", out["data_missing"])


class SettlementCheckTests(unittest.TestCase):
    def setUp(self):
        self.store = mock.patch.object(pipeline, "store").start()
        self.emit = mock.patch.object(pipeline, "_emit", return_value=True).start()
        self.addCleanup(mock.patch.stopall)
        self.store.trading_days.return_value = [
            "2026-07-24", "2026-07-27", "2026-07-28"]

    def test_no_schedule_means_no_work(self):
        self.store.settlement_schedule.return_value = []
        self.assertEqual(pipeline.run_settlement_check("2026-07-24"), 0)
        self.emit.assert_not_called()

    def test_a_shortfall_is_pushed_keyed_on_the_settlement_date(self):
        self.store.settlement_schedule.return_value = [
            {"date": "2026-07-28", "net_amount": -472487.0}]
        self.store.latest_balance.return_value = 446276.0
        self.assertEqual(pipeline.run_settlement_check("2026-07-24"), 1)
        self.assertEqual(self.emit.call_args.kwargs["dedup_key"], "2026-07-28")

    def test_two_shortfalls_on_different_dates_are_two_alerts(self):
        # They must not collapse into one via the de-dup index.
        self.store.settlement_schedule.return_value = [
            {"date": "2026-07-27", "net_amount": -500_000.0},
            {"date": "2026-07-28", "net_amount": -100_000.0}]
        self.store.latest_balance.return_value = 0.0
        pipeline.run_settlement_check("2026-07-24")
        keys = [c.kwargs["dedup_key"] for c in self.emit.call_args_list]
        self.assertEqual(sorted(keys), ["2026-07-27", "2026-07-28"])


class PostCloseTests(unittest.TestCase):
    def setUp(self):
        self.store = mock.patch.object(pipeline, "store").start()
        self.addCleanup(mock.patch.stopall)
        self.store.last_trading_day.return_value = "2026-07-30"

    def test_a_failing_stage_does_not_stop_the_others(self):
        # A dead TAIFEX must not also cancel that day's stop-loss check — the
        # compound failure this system exists to avoid.
        with mock.patch.object(pipeline, "run_risk_light",
                               side_effect=RuntimeError("TAIFEX down")), \
             mock.patch.object(pipeline, "run_stop_check", return_value=1) as stops_, \
             mock.patch.object(pipeline, "run_settlement_check", return_value=0), \
             mock.patch.object(pipeline, "flush_undelivered", return_value=0):
            out = pipeline.post_close()
        stops_.assert_called_once()
        self.assertTrue(any("M1" in e for e in out["errors"]))

    def test_a_clean_run_reports_no_errors_and_resends_last(self):
        calls = []
        with mock.patch.object(pipeline, "run_risk_light",
                               return_value={"light": "red"}), \
             mock.patch.object(pipeline, "run_stop_check",
                               side_effect=lambda *a: calls.append("M2") or 0), \
             mock.patch.object(pipeline, "run_settlement_check",
                               side_effect=lambda *a: calls.append("M2b") or 0), \
             mock.patch.object(pipeline, "flush_undelivered",
                               side_effect=lambda: calls.append("resend") or 0):
            out = pipeline.post_close()
        self.assertEqual(out["errors"], [])
        # The re-send sweep runs last so it also catches this run's failures.
        self.assertEqual(calls[-1], "resend")

    def test_the_light_is_passed_down_to_the_alert_formatters(self):
        with mock.patch.object(pipeline, "run_risk_light",
                               return_value={"light": "red"}), \
             mock.patch.object(pipeline, "run_stop_check", return_value=0) as stops_, \
             mock.patch.object(pipeline, "run_settlement_check", return_value=0), \
             mock.patch.object(pipeline, "flush_undelivered", return_value=0):
            pipeline.post_close("2026-07-30")
        self.assertEqual(stops_.call_args.args[1], "red")


class PreMarketTests(unittest.TestCase):
    def setUp(self):
        self.store = mock.patch.object(pipeline, "store").start()
        self.emit = mock.patch.object(pipeline, "_emit", return_value=True).start()
        self.flush = mock.patch.object(pipeline, "flush_undelivered",
                                       return_value=0).start()
        self.addCleanup(mock.patch.stopall)
        self.store.last_trading_day.return_value = "2026-07-30"
        self.store.active_positions.return_value = []
        self.store.closes_for.return_value = {}
        self.store.no_trade_reason.return_value = None

    def test_red_is_restated_before_the_open(self):
        self.store.prev_market_day.return_value = {
            "date": "2026-07-30", "risk_light": "red", "risk_score": 6}
        out = pipeline.pre_market()
        self.assertTrue(out["pushed"])
        self.assertEqual(self.emit.call_args.args[0], "risk_light_restate")

    def test_yellow_and_green_stay_quiet(self):
        for light in ("yellow", "green"):
            self.emit.reset_mock()
            self.store.prev_market_day.return_value = {
                "date": "2026-07-30", "risk_light": light, "risk_score": 3}
            out = pipeline.pre_market()
            self.assertFalse(out["pushed"], light)
            self.emit.assert_not_called()

    def test_undelivered_alerts_are_resent_even_on_a_quiet_light(self):
        # An exit alert stranded by an overnight outage has to arrive before
        # 09:00 whatever colour the light is.
        self.store.prev_market_day.return_value = {
            "date": "2026-07-30", "risk_light": "green", "risk_score": 0}
        pipeline.pre_market()
        self.flush.assert_called_once()

    def test_no_light_computed_yet_is_handled(self):
        self.store.prev_market_day.return_value = None
        self.assertFalse(pipeline.pre_market()["pushed"])

    def test_the_no_trade_veto_is_shown_in_the_restatement(self):
        self.store.prev_market_day.return_value = {
            "date": "2026-07-30", "risk_light": "red", "risk_score": 6}
        self.store.no_trade_reason.return_value = "節律日"
        pipeline.pre_market()
        self.assertIn("節律日", self.emit.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
