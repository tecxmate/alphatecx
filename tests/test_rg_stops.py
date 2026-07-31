"""M2 stop evaluation and M2b settlement arithmetic."""
import unittest

from mcp_server.api.rg import config as cfg
from mcp_server.api.rg import settlement, stops


def pos(**over):
    base = {"ticker_id": "2324", "name": "仁寶", "kind": "position",
            "cost": 30.0, "qty_lots": 3, "warn_price": 29.5,
            "exit_price": 28.6, "hard_stop_pct": 10, "active": True}
    base.update(over)
    return base


class StopTests(unittest.TestCase):
    def test_close_above_both_lines_is_silent(self):
        self.assertEqual(stops.evaluate([pos()], {"2324": 31.0}), [])

    def test_close_at_warn_line_fires_warn(self):
        alerts = stops.evaluate([pos()], {"2324": 29.5})
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], "stop_warn")
        self.assertEqual(alerts[0]["severity"], "warn")

    def test_close_at_exit_line_fires_exit_not_warn(self):
        alerts = stops.evaluate([pos()], {"2324": 28.6})
        self.assertEqual([a["kind"] for a in alerts], ["stop_exit"])
        self.assertEqual(alerts[0]["severity"], "critical")

    def test_exit_alert_carries_the_conditional_order_instruction(self):
        # PRD §5 M2 v1.1 — the four-day stall on 28.6 is the reason this is
        # mandatory copy, not a nicety.
        alerts = stops.evaluate([pos()], {"2324": 28.0})
        self.assertIn(cfg.CONDITIONAL_ORDER_ADVICE, alerts[0]["action"])

    def test_every_alert_has_an_action_line(self):
        for close in (29.5, 28.0):
            for a in stops.evaluate([pos()], {"2324": close}):
                self.assertTrue(a["action"].strip())

    def test_watch_rows_are_never_stop_checked(self):
        self.assertEqual(stops.evaluate([pos(kind="watch")], {"2324": 1.0}), [])

    def test_inactive_rows_are_skipped(self):
        self.assertEqual(stops.evaluate([pos(active=False)], {"2324": 1.0}), [])

    def test_missing_price_is_not_treated_as_a_breach(self):
        self.assertEqual(stops.evaluate([pos()], {}), [])

    def test_unset_exit_falls_back_to_cost_minus_hard_stop(self):
        warn, exit_price, fallback = stops.effective_lines(
            pos(exit_price=None, warn_price=None, cost=100.0, hard_stop_pct=10))
        self.assertEqual(exit_price, 90.0)
        self.assertTrue(fallback)
        self.assertIsNone(warn)

    def test_fallback_line_is_flagged_in_the_alert(self):
        alerts = stops.evaluate([pos(exit_price=None, warn_price=None,
                                     cost=100.0, hard_stop_pct=10)],
                                {"2324": 89.0})
        self.assertTrue(alerts[0]["line_is_fallback"])

    def test_no_cost_and_no_lines_means_no_alert_rather_than_a_guess(self):
        warn, exit_price, fallback = stops.effective_lines(
            pos(cost=None, exit_price=None, warn_price=None))
        self.assertIsNone(exit_price)
        self.assertFalse(fallback)


class DistanceTests(unittest.TestCase):
    def test_distances_agree_with_evaluate_about_triggering(self):
        rows = stops.distances([pos()], {"2324": 28.6})
        self.assertEqual(rows[0]["triggered"], "exit")
        self.assertEqual(rows[0]["pct_to_exit"], 0.0)

    def test_distance_handles_missing_close(self):
        rows = stops.distances([pos()], {})
        self.assertIsNone(rows[0]["close"])
        self.assertIsNone(rows[0]["triggered"])


# 2026-07-24 is a Friday; 7/25–7/26 是週末.
DAYS = ["2026-07-22", "2026-07-23", "2026-07-24",
        "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"]


class SettlementDateTests(unittest.TestCase):
    def test_t_plus_two_counts_trading_days_not_calendar_days(self):
        self.assertEqual(settlement.settle_date("2026-07-24", DAYS), "2026-07-28")

    def test_midweek_trade_settles_two_sessions_later(self):
        self.assertEqual(settlement.settle_date("2026-07-28", DAYS), "2026-07-30")

    def test_unknown_trade_date_returns_none_rather_than_guessing(self):
        self.assertIsNone(settlement.settle_date("2026-07-25", DAYS))

    def test_calendar_running_out_returns_none(self):
        self.assertIsNone(settlement.settle_date("2026-07-31", DAYS))


class FillAmountTests(unittest.TestCase):
    def test_buy_is_negative_and_includes_fees(self):
        amount = settlement.fill_amount("buy", 51.5, 3)
        gross = 51.5 * 3 * cfg.SHARES_PER_LOT
        self.assertLess(amount, 0)
        self.assertLess(amount, -gross)      # fee makes it worse than gross

    def test_sell_is_positive_and_net_of_tax(self):
        amount = settlement.fill_amount("sell", 51.5, 3)
        gross = 51.5 * 3 * cfg.SHARES_PER_LOT
        self.assertGreater(amount, 0)
        self.assertLess(amount, gross)

    def test_minimum_fee_applies_to_tiny_fills(self):
        amount = settlement.fill_amount("buy", 10.0, 0.001)
        self.assertAlmostEqual(amount, -(10.0 * 0.001 * 1000 + cfg.BROKER_FEE_MIN))


class SettlementGapTests(unittest.TestCase):
    def test_the_0724_near_miss_is_caught_two_sessions_early(self):
        # 應付 472,487 對上餘額 446,276 — 缺口 26,211.
        alerts = settlement.check_gap(
            [{"date": "2026-07-28", "net_amount": -472487.0}],
            balance=446276.0, today="2026-07-24", trading_days=DAYS)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "critical")
        self.assertEqual(alerts[0]["shortfall"], 26211.0)
        self.assertEqual(alerts[0]["days_ahead"], 2)

    def test_sufficient_balance_is_silent(self):
        self.assertEqual(settlement.check_gap(
            [{"date": "2026-07-28", "net_amount": -400000.0}],
            balance=446276.0, today="2026-07-24", trading_days=DAYS), [])

    def test_incoming_sale_funds_a_later_purchase(self):
        # A sale settling first carries forward, which is how the account
        # actually behaves — flagging this would be a false alarm.
        alerts = settlement.check_gap(
            [{"date": "2026-07-28", "net_amount": +300000.0},
             {"date": "2026-07-29", "net_amount": -400000.0}],
            balance=150000.0, today="2026-07-24", trading_days=DAYS)
        self.assertEqual(alerts, [])

    def test_unreported_balance_warns_instead_of_passing_silently(self):
        alerts = settlement.check_gap(
            [{"date": "2026-07-28", "net_amount": -1.0}],
            balance=None, today="2026-07-24", trading_days=DAYS)
        self.assertEqual(alerts[0]["severity"], "warn")
        self.assertIn("/balance", alerts[0]["action"])

    def test_past_settlements_are_ignored(self):
        alerts = settlement.check_gap(
            [{"date": "2026-07-22", "net_amount": -999999.0}],
            balance=1000.0, today="2026-07-24", trading_days=DAYS)
        self.assertEqual(alerts, [])


if __name__ == "__main__":
    unittest.main()
