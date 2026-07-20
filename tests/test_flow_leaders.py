import unittest

from mcp_server.api import flow_leaders as fl


class PriceStatTests(unittest.TestCase):
    def test_move_is_median_anchored_not_endpoint(self):
        # Latest 167 against a window median of ~160 is a +4.4% drift — flat.
        row = {"close_today": 167.0, "med_close": 160.0, "p10": 152.0, "p90": 167.0}
        self.assertAlmostEqual(fl.price_move_pct(row), 4.375, places=2)

    def test_a_single_corrupt_print_cannot_distort_move_or_range(self):
        # 4536 printed 87.3 once inside a ~160 window. The median/p10/p90 shrug
        # it off where a min/first-based metric would read a ~50% swing.
        clean = {"close_today": 167.0, "med_close": 160.0, "p10": 152.0, "p90": 167.0}
        # Same window, one bad tick — median/percentiles barely move.
        withbad = {"close_today": 167.0, "med_close": 159.0, "p10": 151.0, "p90": 167.0}
        self.assertLess(abs(fl.price_move_pct(withbad)), 8.0)
        self.assertLess(fl.price_range_pct(withbad), 12.0)
        self.assertLess(fl.price_range_pct(clean), 12.0)

    def test_missing_price_is_none_not_zero(self):
        self.assertIsNone(fl.price_move_pct({"close_today": None, "med_close": 10}))
        self.assertIsNone(fl.price_range_pct({"p10": 1, "p90": 2, "med_close": None}))

    def test_margin_usage_none_when_limit_missing(self):
        self.assertIsNone(fl.margin_usage_pct({"margin_balance": 100, "margin_limit": 0}))
        self.assertAlmostEqual(fl.margin_usage_pct({"margin_balance": 50, "margin_limit": 1000}), 5.0)


def tuo_kai(**over):
    """拓凱 (4536) as of 2026-06-30 — the sleeper ground truth."""
    row = dict(
        ticker_id="4536", name="拓凱", market="TWSE",
        close_today=167.0, med_close=160.0, p10=152.0, p90=167.0,
        foreign_net_sum=743237, buy_day_ratio=0.85, foreign_net_z20=-0.39,
        pe_ratio=12.44, pb_ratio=1.66, dividend_yield=4.79, valuation_known=True,
        foreign_held_pct=12.48, margin_balance=710, margin_limit=22705,
        revenue_yoy_pct=10.0, turnover_twd=300_000_000,
    )
    row.update(over)
    return row


def ri_chi(**over):
    """日馳 (1526) as of 2026-07-17 — the chase ground truth."""
    row = dict(
        ticker_id="1526", name="日馳", market="TWSE",
        close_today=17.25, med_close=15.6, p10=14.2, p90=17.25,
        foreign_net_sum=-44400, buy_day_ratio=0.55, foreign_net_z20=-3.25,
        pe_ratio=None, pb_ratio=0.78, dividend_yield=0.0, valuation_known=True,
        foreign_held_pct=2.36, margin_balance=610, margin_limit=5000,
        revenue_yoy_pct=-24.0, turnover_twd=200_000_000,
    )
    row.update(over)
    return row


class AcceptanceTests(unittest.TestCase):
    """The two non-negotiable cases from the handoff, as pure-function checks.

    The full 'appears in the top 20 of the whole market' assertion is an
    integration property validated live against Neon (scripts/smoke); here we
    pin the per-name verdict + a high score so the weights can't silently drift.
    """

    def test_tuokai_is_a_high_scoring_sleeper(self):
        out = fl.score_row(tuo_kai())
        self.assertEqual(out["triage"], "sleeper")
        self.assertGreater(out["sleeper_score"], 65)
        self.assertTrue(out["accumulation_into_flat"])
        self.assertLessEqual(abs(out["price_move_pct"]), 8.0)
        for f in ("cheap", "accumulating", "flat", "under_owned"):
            self.assertIn(f, out["sleeper_flags"])

    def test_richi_is_a_chase_on_no_earnings_and_distribution(self):
        out = fl.score_row(ri_chi())
        self.assertEqual(out["triage"], "chase")
        self.assertIn("no_earnings", out["sleeper_flags"])
        self.assertIn("distributing", out["sleeper_flags"])

    def test_single_day_z_does_not_sink_a_multiweek_grinder(self):
        # 拓凱's final-day z20 is negative; the sleeper verdict must survive it.
        self.assertEqual(fl.score_row(tuo_kai(foreign_net_z20=-0.9))["triage"], "sleeper")


class TriageRubricTests(unittest.TestCase):
    def test_any_anti_flag_forces_chase(self):
        self.assertEqual(fl.score_row(tuo_kai(foreign_net_sum=-1))["triage"], "chase")
        self.assertEqual(fl.score_row(tuo_kai(pe_ratio=95.0))["triage"], "chase")

    def test_ran_hard_is_a_chase_even_if_cheap(self):
        out = fl.score_row(tuo_kai(close_today=250.0, med_close=160.0))
        self.assertIn("already_ran", out["sleeper_flags"])
        self.assertEqual(out["triage"], "chase")

    def test_sleeper_requires_cheap_and_accumulating_and_flat(self):
        # Cheap + flat but weak buying → not a sleeper (accumulating missing).
        out = fl.score_row(tuo_kai(buy_day_ratio=0.55, foreign_net_z20=0.1))
        self.assertNotIn("accumulating", out["sleeper_flags"])
        self.assertEqual(out["triage"], "watch")

    def test_pe_null_without_a_valuation_row_is_not_no_earnings(self):
        # A TPEX-style coverage gap must not be read as loss-making.
        out = fl.score_row(tuo_kai(pe_ratio=None, valuation_known=False))
        self.assertNotIn("no_earnings", out["sleeper_flags"])
        self.assertNotEqual(out["triage"], "chase")

    def test_pe_null_with_a_valuation_row_is_no_earnings(self):
        out = fl.score_row(tuo_kai(pe_ratio=None, valuation_known=True))
        self.assertIn("no_earnings", out["sleeper_flags"])
        self.assertEqual(out["triage"], "chase")


class RobustnessTests(unittest.TestCase):
    def test_fully_null_enrichment_degrades_to_watch_without_raising(self):
        out = fl.score_row({"ticker_id": "9999"})
        self.assertEqual(out["triage"], "watch")
        self.assertEqual(out["sleeper_flags"], [])
        self.assertFalse(out["accumulation_into_flat"])
        self.assertIsNone(out["price_move_pct"])

    def test_score_does_not_mutate_input(self):
        row = tuo_kai()
        fl.score_row(row)
        self.assertNotIn("triage", row)
        self.assertNotIn("sleeper_score", row)

    def test_unknown_margin_and_revenue_do_not_penalise(self):
        # A name with no margin/revenue row should still be scoreable, not zeroed.
        out = fl.score_row(tuo_kai(margin_balance=None, margin_limit=None, revenue_yoy_pct=None))
        self.assertEqual(out["triage"], "sleeper")


if __name__ == "__main__":
    unittest.main()
