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
        # Real metrics always carry both the 5-day mean and today's raw counts;
        # subitem 2 reads the worse of the two.
        "adv_ratio_5d": 0.55, "adv_count": 550, "dec_count": 450,
        "margin_chg_5d_pct": 0.5,
        # Deeply net short is the normal resting state, so a calm day carries a
        # big negative level and a near-zero change.
        "fut_foreign_net_oi": -70_000, "fut_net_oi_chg_5d": -500,
    }
    base.update(over)
    return base


class SubitemTests(unittest.TestCase):
    def test_calm_market_is_green_but_with_no_margin(self):
        # Since PRD §5's absolute level was restored, subitem 4 contributes +2
        # on every session the data has ever shown, so a calm day floors at 2.
        # Green survives (band is <=2) but with zero headroom: one point from
        # any other subitem tips it to yellow. Locked in a test so the next
        # person reads it as a deliberate calibration, not drift.
        score, reasons = scoring.score_day(metrics())
        self.assertEqual(score, 2)
        self.assertEqual(scoring.light_from_score(score), "green")
        self.assertEqual(scoring.light_from_score(score + 1), "yellow")
        self.assertEqual(scoring.missing_subitems(reasons), [])

    def test_below_both_moving_averages_stacks_to_three(self):
        score, reasons = scoring.score_day(
            metrics(taiex_close=42000.0, ma20=44000.0, ma60=43000.0))
        self.assertEqual(reasons[0]["points"], 3)
        self.assertEqual(score, 5)   # 3 trend + 2 constant futures level

    def test_below_ma20_only_scores_one(self):
        _, reasons = scoring.score_day(
            metrics(taiex_close=43500.0, ma20=44000.0, ma60=43000.0))
        self.assertEqual(reasons[0]["points"], 1)

    def test_breadth_bands(self):
        self.assertEqual(scoring.score_day(metrics(adv_ratio_5d=0.39))[1][1]["points"], 2)
        self.assertEqual(scoring.score_day(metrics(adv_ratio_5d=0.44))[1][1]["points"], 1)
        self.assertEqual(scoring.score_day(metrics(adv_ratio_5d=0.46))[1][1]["points"], 0)

    def test_single_day_breadth_collapse_scores_despite_a_calm_mean(self):
        # 2026-07-07: 128 up / 892 down = 0.126 on the day, but a 5-day mean of
        # 0.517 because 07-01…07-06 were strong. The mean alone scored zero and
        # the row failed acceptance; the shock term is what catches it.
        _, reasons = scoring.score_day(
            metrics(adv_ratio_5d=0.517, adv_count=128, dec_count=892))
        self.assertEqual(reasons[1]["points"], 2)

    def test_breadth_takes_the_worse_reading_and_never_sums_them(self):
        # Both halves bad must still cap at the weight PRD §5 gives subitem 2.
        _, reasons = scoring.score_day(
            metrics(adv_ratio_5d=0.10, adv_count=87, dec_count=960))
        self.assertEqual(reasons[1]["points"], 2)

    def test_a_strong_session_inside_a_weak_regime_still_scores_the_regime(self):
        # 2026-07-15 rallied (893/125) while the 5-day mean was still poor.
        _, reasons = scoring.score_day(
            metrics(adv_ratio_5d=0.39, adv_count=893, dec_count=125))
        self.assertEqual(reasons[1]["points"], 2)

    def test_ordinary_weak_day_is_not_a_shock(self):
        # 2026-07-24 printed 0.34 — weak, but nowhere near a panic print.
        _, reasons = scoring.score_day(
            metrics(adv_ratio_5d=0.50, adv_count=333, dec_count=645))
        self.assertEqual(reasons[1]["points"], 0)

    def test_zero_counts_do_not_divide_by_zero(self):
        _, reasons = scoring.score_day(
            metrics(adv_ratio_5d=0.55, adv_count=0, dec_count=0))
        self.assertEqual(reasons[1]["points"], 0)

    def test_margin_needs_both_rising_leverage_and_falling_index(self):
        rising_in_up_market = scoring.score_day(
            metrics(margin_chg_5d_pct=5.0, taiex_ret_5d_pct=2.0))[1][2]
        self.assertEqual(rising_in_up_market["points"], 0)

        rising_in_down_market = scoring.score_day(
            metrics(margin_chg_5d_pct=5.0, taiex_ret_5d_pct=-2.0))[1][2]
        self.assertEqual(rising_in_down_market["points"], 2)

    def test_futures_scores_the_level_not_the_change(self):
        def pts(**kw):
            return scoring.score_day(metrics(**kw))[1][3]["points"]

        self.assertEqual(pts(fut_foreign_net_oi=-82_515), 2)   # PRD §5 example
        self.assertEqual(pts(fut_foreign_net_oi=-20_000), 2)   # boundary, inclusive
        self.assertEqual(pts(fut_foreign_net_oi=-10_000), 1)
        self.assertEqual(pts(fut_foreign_net_oi=-5_000), 0)
        # Net LONG is never a risk penalty.
        self.assertEqual(pts(fut_foreign_net_oi=+30_000), 0)
        # The change is now context only — it must not move the score.
        self.assertEqual(pts(fut_foreign_net_oi=-82_515, fut_net_oi_chg_5d=+9_929), 2)

    def test_the_level_scores_on_every_observed_session(self):
        # Documents the accepted cost of following PRD §5 literally. Through
        # 2026-06/07 the level sat 65k–86k net short on EVERY session, so this
        # subitem is a constant, not a discriminator: it reads the same whether
        # foreigners piled into shorts or covered them. Kept as a test so the
        # property is visible rather than folklore.
        for level in (-65_039, -81_017, -86_189):
            _, reasons = scoring.score_day(
                metrics(fut_foreign_net_oi=level, fut_net_oi_chg_5d=-200))
            self.assertEqual(reasons[3]["points"], 2, f"level {level} scores +2")

    def test_a_known_level_scores_even_when_the_change_is_missing(self):
        # The level is what is scored now, so a missing change is no longer a
        # data gap for this subitem.
        _, reasons = scoring.score_day(
            metrics(fut_foreign_net_oi=-81_017, fut_net_oi_chg_5d=None))
        self.assertFalse(reasons[3]["data_missing"])
        self.assertEqual(reasons[3]["points"], 2)

    def test_a_missing_level_is_flagged_as_data_missing(self):
        _, reasons = scoring.score_day(metrics(fut_foreign_net_oi=None))
        self.assertTrue(reasons[3]["data_missing"])
        self.assertEqual(reasons[3]["points"], 0)

    def test_day_drop_bands_do_not_stack(self):
        self.assertEqual(scoring.score_day(metrics(taiex_pct=-6.47))[1][4]["points"], 2)
        self.assertEqual(scoring.score_day(metrics(taiex_pct=-2.31))[1][4]["points"], 1)
        self.assertEqual(scoring.score_day(metrics(taiex_pct=-1.9))[1][4]["points"], 0)


class MissingDataTests(unittest.TestCase):
    def test_absent_subitem_scores_zero_and_is_flagged_not_silently_calm(self):
        score, reasons = scoring.score_day(
            metrics(fut_foreign_net_oi=None, fut_net_oi_chg_5d=None))
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
