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


if __name__ == "__main__":
    unittest.main()
