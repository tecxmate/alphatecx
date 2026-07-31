"""M1 scorer and light state machine.

The replay rows from PRD §7 are reproduced here as synthetic metric bundles.
That is on purpose: `riskguard/replay.py` verifies the same rows against live
data and needs a DB plus two network calls per session, so it cannot run in CI.
These tests pin the *decision*, the replay pins the *inputs*. Both are needed —
a scorer that passes here and fails there means the data changed, which is a
different bug from a scorer that got the logic wrong.
"""
import unittest

from mcp_server.api.rg import config as cfg
from mcp_server.api.rg import light as light_mod
from mcp_server.api.rg import scoring


def metrics(**over):
    base = {
        "taiex_close": 45000.0, "taiex_pct": 0.5,
        "ma20": 44000.0, "ma60": 43000.0, "taiex_ret_5d_pct": 1.0,
        "adv_ratio_5d": 0.55, "margin_chg_5d_pct": 0.5,
        "fut_foreign_net_oi": 5000,
    }
    base.update(over)
    return base


class SubitemTests(unittest.TestCase):
    def test_calm_market_scores_zero_and_is_green(self):
        score, reasons = scoring.score_day(metrics())
        self.assertEqual(score, 0)
        self.assertEqual(scoring.light_from_score(score), "green")
        self.assertEqual(scoring.missing_subitems(reasons), [])

    def test_below_both_moving_averages_stacks_to_three(self):
        score, reasons = scoring.score_day(
            metrics(taiex_close=42000.0, ma20=44000.0, ma60=43000.0))
        self.assertEqual(reasons[0]["points"], 3)
        self.assertEqual(score, 3)

    def test_below_ma20_only_scores_one(self):
        _, reasons = scoring.score_day(
            metrics(taiex_close=43500.0, ma20=44000.0, ma60=43000.0))
        self.assertEqual(reasons[0]["points"], 1)

    def test_breadth_bands(self):
        self.assertEqual(scoring.score_day(metrics(adv_ratio_5d=0.39))[1][1]["points"], 2)
        self.assertEqual(scoring.score_day(metrics(adv_ratio_5d=0.44))[1][1]["points"], 1)
        self.assertEqual(scoring.score_day(metrics(adv_ratio_5d=0.46))[1][1]["points"], 0)

    def test_margin_needs_both_rising_leverage_and_falling_index(self):
        rising_in_up_market = scoring.score_day(
            metrics(margin_chg_5d_pct=5.0, taiex_ret_5d_pct=2.0))[1][2]
        self.assertEqual(rising_in_up_market["points"], 0)

        rising_in_down_market = scoring.score_day(
            metrics(margin_chg_5d_pct=5.0, taiex_ret_5d_pct=-2.0))[1][2]
        self.assertEqual(rising_in_down_market["points"], 2)

    def test_futures_net_short_bands(self):
        self.assertEqual(scoring.score_day(metrics(fut_foreign_net_oi=-81017))[1][3]["points"], 2)
        self.assertEqual(scoring.score_day(metrics(fut_foreign_net_oi=-15000))[1][3]["points"], 1)
        self.assertEqual(scoring.score_day(metrics(fut_foreign_net_oi=-5000))[1][3]["points"], 0)
        # Net long is never a risk penalty.
        self.assertEqual(scoring.score_day(metrics(fut_foreign_net_oi=40000))[1][3]["points"], 0)

    def test_day_drop_bands_do_not_stack(self):
        self.assertEqual(scoring.score_day(metrics(taiex_pct=-6.47))[1][4]["points"], 2)
        self.assertEqual(scoring.score_day(metrics(taiex_pct=-2.31))[1][4]["points"], 1)
        self.assertEqual(scoring.score_day(metrics(taiex_pct=-1.9))[1][4]["points"], 0)


class MissingDataTests(unittest.TestCase):
    def test_absent_subitem_scores_zero_and_is_flagged_not_silently_calm(self):
        score, reasons = scoring.score_day(metrics(fut_foreign_net_oi=None))
        self.assertEqual(reasons[3]["points"], 0)
        self.assertTrue(reasons[3]["data_missing"])
        self.assertIn("futures", scoring.missing_subitems(reasons))
        self.assertEqual(score, 0)

    def test_empty_metrics_never_raises(self):
        score, reasons = scoring.score_day({})
        self.assertEqual(score, 0)
        self.assertEqual(len(scoring.missing_subitems(reasons)), 5)

    def test_non_numeric_input_is_treated_as_missing(self):
        _, reasons = scoring.score_day(metrics(taiex_pct="n/a"))
        self.assertTrue(reasons[4]["data_missing"])


class ReplayRowTests(unittest.TestCase):
    """PRD §7 M1 回放驗收, as decisions over the inputs those days actually had.

    Breadth and futures figures below are the real values pulled from TWSE
    MI_INDEX type=MS and the TAIFEX institutional CSV while building this.
    """

    def test_0707_broke_monthly_line_reaches_at_least_yellow(self):
        # −2.31%, close 45479.11 under a ~45.6k MA20; breadth 128/892 that day
        # and a 5-day mean well under 0.40.
        score, _ = scoring.score_day(metrics(
            taiex_close=45479.11, taiex_pct=-2.31, ma20=45600.0, ma60=44000.0,
            adv_ratio_5d=0.21, taiex_ret_5d_pct=-2.5, margin_chg_5d_pct=1.0,
            fut_foreign_net_oi=-8000))
        self.assertGreaterEqual(score, cfg.SCORE_YELLOW)

    def test_0717_crash_day_is_red(self):
        # −6.47%, breadth 87/960.
        score, _ = scoring.score_day(metrics(
            taiex_close=42671.27, taiex_pct=-6.47, ma20=45600.0, ma60=44100.0,
            adv_ratio_5d=0.12, taiex_ret_5d_pct=-6.5, margin_chg_5d_pct=1.0,
            fut_foreign_net_oi=-45000))
        self.assertGreaterEqual(score, cfg.SCORE_RED)

    def test_0730_quiet_day_after_the_crash_does_not_relax_the_light(self):
        # −0.26%, but 39933.30 closed *below* 7/29's 40039.18 — the prior low
        # was broken, so the red→yellow hold streak is 0.
        closes = [39933.30, 40039.18, 41603.36, 43634.19, 43654.84, 44850.81]
        ctx = light_mod.build_index_context(closes)
        self.assertEqual(ctx["held_above_prior_low_days"], 0)

        resolved, why = light_mod.resolve_light(
            score=3, prev_light="red", ctx={**ctx, "prev_score": 7})
        self.assertEqual(resolved, "red", why)

    def test_0731_eight_percent_surge_cannot_jump_to_green(self):
        # One violent up day is a candidate first day, not an unlock: up_streak
        # is 1 and red must walk through yellow regardless.
        closes = [43128.0, 39933.30, 40039.18, 41603.36, 43634.19, 43654.84]
        ctx = light_mod.build_index_context(closes)
        self.assertEqual(ctx["up_streak"], 1)

        resolved, _ = light_mod.resolve_light(
            score=0, prev_light="red",
            ctx={**ctx, "prev_score": 7, "close_above_ma20": True})
        self.assertNotEqual(resolved, "green")


class HysteresisTests(unittest.TestCase):
    def test_upgrade_to_red_is_immediate(self):
        resolved, _ = light_mod.resolve_light(
            score=7, prev_light="green", ctx={"prev_score": 0})
        self.assertEqual(resolved, "red")

    def test_red_to_yellow_needs_two_sessions_holding_the_prior_low(self):
        blocked, _ = light_mod.resolve_light(
            score=3, prev_light="red",
            ctx={"prev_score": 6, "held_above_prior_low_days": 1})
        self.assertEqual(blocked, "red")

        allowed, _ = light_mod.resolve_light(
            score=3, prev_light="red",
            ctx={"prev_score": 6, "held_above_prior_low_days": 2})
        self.assertEqual(allowed, "yellow")

    def test_red_to_yellow_blocked_while_penalties_still_increasing(self):
        resolved, _ = light_mod.resolve_light(
            score=4, prev_light="red",
            ctx={"prev_score": 3, "held_above_prior_low_days": 5})
        self.assertEqual(resolved, "red")

    def test_yellow_to_green_via_ma20_reclaim(self):
        resolved, _ = light_mod.resolve_light(
            score=1, prev_light="yellow",
            ctx={"prev_score": 3, "close_above_ma20": True, "up_streak": 1})
        self.assertEqual(resolved, "green")

    def test_yellow_to_green_via_three_higher_closes(self):
        resolved, _ = light_mod.resolve_light(
            score=1, prev_light="yellow",
            ctx={"prev_score": 3, "close_above_ma20": False, "up_streak": 3})
        self.assertEqual(resolved, "green")

    def test_yellow_holds_without_either_unlock(self):
        resolved, _ = light_mod.resolve_light(
            score=0, prev_light="yellow",
            ctx={"prev_score": 3, "close_above_ma20": False, "up_streak": 2})
        self.assertEqual(resolved, "yellow")

    def test_cold_start_publishes_the_raw_band(self):
        resolved, _ = light_mod.resolve_light(score=6, prev_light=None, ctx={})
        self.assertEqual(resolved, "red")


class IndexContextTests(unittest.TestCase):
    def test_up_streak_counts_consecutive_higher_closes(self):
        ctx = light_mod.build_index_context([105.0, 104.0, 103.0, 110.0])
        self.assertEqual(ctx["up_streak"], 2)

    def test_up_streak_zero_when_today_is_lower(self):
        ctx = light_mod.build_index_context([100.0, 104.0, 103.0])
        self.assertEqual(ctx["up_streak"], 0)

    def test_short_series_does_not_raise(self):
        self.assertEqual(
            light_mod.build_index_context([]),
            {"up_streak": 0, "held_above_prior_low_days": 0},
        )
        light_mod.build_index_context([100.0])


if __name__ == "__main__":
    unittest.main()
