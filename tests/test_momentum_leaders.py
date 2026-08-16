"""momentum_leaders_scan scoring + the spec's falsifiable acceptance cases.

The crux, per the spec: 川湖 2059 must be `momentum-entry` in June and `chase`
in August — same stock, opposite verdict, because by August it is 75% above its
50-day mean. If it says entry in August the tool is a blow-off chaser and has
earned nothing.

Everything here is pure-function, no DB: the whole point of keeping judgment out
of SQL is that these cases are checkable.
"""
import unittest

from mcp_server.api import momentum_leaders as ml


def row(**over) -> dict:
    """A clean, institution-backed, early-trend name. Each test perturbs the one
    dimension it is about, so a failure names its own cause."""
    base = {
        "ticker_id": "0000", "name": "test", "market": "TWSE",
        "close": 100.0, "high": 101.0, "low": 98.0,
        "ma_50": 85.0, "ma_50_prev": 83.0,
        "ma_200": 70.0, "ma_200_prev": 69.0,
        "high_3m": 100.0, "volume_ratio_20": 2.0,
        "atr_14": 4.0, "recent_swing_low": 88.0,
        "rs_percentile": 92.0,
        "foreign_trend_net": 10_000_000, "trust_trend_net": 2_000_000,
        "trend_return_pct": 25.0,
        "rev_yoy_pct": 35.0, "rev_yoy_pct_prev": 20.0,
        "pe_ratio": 38.0,
        "base_days_before_leg": 9,
        "limit_up": False,
    }
    base.update(over)
    return base


class AcceptanceTests(unittest.TestCase):
    """Section 7 of the spec, verbatim."""

    def test_chuanhu_june_is_an_entry(self):
        # Early in a clean, institution-backed breakout from a ~5,000 base.
        out = ml.score_row(row(
            close=5900.0, high=5920.0, low=5780.0,
            ma_50=4980.0, ma_50_prev=4890.0, ma_200=4100.0, ma_200_prev=4050.0,
            high_3m=5900.0, volume_ratio_20=2.4, atr_14=210.0,
            recent_swing_low=5200.0, rs_percentile=96.0,
            foreign_trend_net=12_500_000, trust_trend_net=3_400_000,
            trend_return_pct=28.0, rev_yoy_pct=41.0, rev_yoy_pct_prev=30.0,
            pe_ratio=40.1, base_days_before_leg=9,
        ))
        self.assertEqual(out["triage"], ml.TRIAGE_ENTRY)
        self.assertEqual(out["flags"], [])
        self.assertLess(out["extension_above_ma50_pct"], 40.0)
        self.assertIsNotNone(out["trailing_stop"])

    def test_chuanhu_august_is_a_chase(self):
        # THE crux. Up ~75% in two weeks to 12,500 on a ~90x P/E: the blow-off.
        # Note it still scores highly — relative strength and breakout quality
        # are excellent at a top. Only the parabolic guard rejects it.
        out = ml.score_row(row(
            close=12_500.0, high=12_600.0, low=12_100.0,
            ma_50=7_100.0, ma_50_prev=6_500.0, ma_200=5_200.0, ma_200_prev=5_000.0,
            high_3m=12_600.0, volume_ratio_20=2.8, atr_14=800.0,
            recent_swing_low=9_800.0, rs_percentile=99.0,
            foreign_trend_net=8_000_000, trust_trend_net=2_000_000,
            trend_return_pct=75.0, rev_yoy_pct=45.0, pe_ratio=90.0,
            base_days_before_leg=12,
        ))
        self.assertEqual(out["triage"], ml.TRIAGE_CHASE)
        self.assertIn("parabolic", out["flags"])
        self.assertGreater(out["extension_above_ma50_pct"], 40.0)

    def test_the_same_stock_flips_verdict_on_extension_alone(self):
        # Stated as the whole justification for the tool, so assert it directly
        # rather than leaving it implied by the two tests above.
        june = ml.score_row(row(close=5900.0, ma_50=4980.0, high_3m=5900.0,
                                recent_swing_low=5200.0, atr_14=210.0))
        august = ml.score_row(row(close=12_500.0, ma_50=7_100.0, high_3m=12_600.0,
                                  recent_swing_low=9_800.0, atr_14=800.0,
                                  trend_return_pct=75.0))
        self.assertEqual(june["triage"], ml.TRIAGE_ENTRY)
        self.assertEqual(august["triage"], ml.TRIAGE_CHASE)

    def test_shengtian_4541_is_a_chase_on_three_counts(self):
        # +39% in 8 sessions, foreign net -430k, no base.
        out = ml.score_row(row(
            close=100.0, ma_50=68.5, ma_50_prev=64.0,
            high_3m=100.0, volume_ratio_20=2.2, rs_percentile=91.0,
            foreign_trend_net=-430_098, trust_trend_net=900_000,
            trend_return_pct=39.0, base_days_before_leg=1,
        ))
        self.assertEqual(out["triage"], ml.TRIAGE_CHASE)
        for flag in ("parabolic", "no_base", "retail_pump"):
            self.assertIn(flag, out["flags"])
        # 投信 buying alongside foreign selling is the pattern itself, not a
        # defence against it.
        self.assertFalse(out["inst_confirmed"])

    def test_richi_1526_is_a_chase_on_retail_pump(self):
        # Limit-up x2 with foreign selling into it, revenue -24%.
        out = ml.score_row(row(
            close=100.0, ma_50=80.0, ma_50_prev=79.0,
            high_3m=100.0, volume_ratio_20=2.5, rs_percentile=88.0,
            foreign_trend_net=-1_200_000, trust_trend_net=None,
            trend_return_pct=22.0, rev_yoy_pct=-24.0,
            base_days_before_leg=7, limit_up=True,
        ))
        self.assertEqual(out["triage"], ml.TRIAGE_CHASE)
        self.assertIn("retail_pump", out["flags"])

    def test_aidc_2634_is_not_a_chase(self):
        # Institution-backed defence theme, early. Entry or watch both fine;
        # `chase` is the failure the spec names.
        out = ml.score_row(row(
            close=62.0, ma_50=55.0, ma_50_prev=53.5,
            ma_200=48.0, ma_200_prev=47.5,
            high_3m=62.0, volume_ratio_20=1.8, atr_14=1.8,
            recent_swing_low=56.0, rs_percentile=84.0,
            foreign_trend_net=4_500_000, trust_trend_net=1_100_000,
            trend_return_pct=14.0, rev_yoy_pct=18.0, base_days_before_leg=11,
        ))
        self.assertNotEqual(out["triage"], ml.TRIAGE_CHASE)
        self.assertEqual(out["flags"], [])

    def test_tuokai_4536_the_value_name_is_never_a_momentum_entry(self):
        # Flat value name — belongs to flow_leaders. Low RS, no trend, no
        # breakout: it must score low and must not be an entry.
        out = ml.score_row(row(
            close=152.0, ma_50=155.0, ma_50_prev=156.0,
            ma_200=158.0, ma_200_prev=158.5,
            high_3m=175.0, volume_ratio_20=0.6, rs_percentile=35.0,
            foreign_trend_net=800_000, trust_trend_net=0,
            trend_return_pct=1.0, rev_yoy_pct=4.0, pe_ratio=12.0,
            base_days_before_leg=40,
        ))
        self.assertNotEqual(out["triage"], ml.TRIAGE_ENTRY)
        self.assertLess(out["momentum_score"], ml.ENTRY_SCORE_MIN)


class AntiFlagTests(unittest.TestCase):
    def test_an_early_trend_limit_up_is_not_flagged(self):
        # Limit-up only matters once already extended: an early-trend lock is
        # one of the better entries there is.
        out = ml.score_row(row(limit_up=True))
        self.assertNotIn("limit_locked_extended", out["flags"])

    def test_an_extended_limit_up_is_flagged(self):
        out = ml.score_row(row(limit_up=True, close=100.0, ma_50=60.0))
        self.assertIn("limit_locked_extended", out["flags"])
        self.assertIn("parabolic", out["flags"])

    def test_climax_volume_needs_a_weak_close_not_just_volume(self):
        # Huge volume closing AT the high is accumulation, not distribution.
        strong = ml.score_row(row(volume_ratio_20=4.0, close=100.9,
                                  high=101.0, low=98.0))
        self.assertNotIn("climax_volume", strong["flags"])
        weak = ml.score_row(row(volume_ratio_20=4.0, close=98.5,
                                high=101.0, low=98.0))
        self.assertIn("climax_volume", weak["flags"])

    def test_foreign_selling_without_a_price_rise_is_not_a_pump(self):
        out = ml.score_row(row(foreign_trend_net=-500_000, trend_return_pct=-3.0))
        self.assertNotIn("retail_pump", out["flags"])

    def test_thresholds_are_caller_tunable(self):
        r = row(close=100.0, ma_50=70.0)          # 42.9% extended
        self.assertIn("parabolic", ml.score_row(r)["flags"])
        self.assertNotIn("parabolic",
                         ml.score_row(r, max_extension_pct=50.0)["flags"])


class StopTests(unittest.TestCase):
    def test_the_tightest_of_the_three_binds_and_is_named(self):
        # atr: 100 - 2.5*4 = 90 ; swing: 88 ; ma50 floor: 85*0.97 = 82.45
        stop, basis, dist = ml.trailing_stop(row())
        self.assertEqual(basis, "atr")
        self.assertAlmostEqual(stop, 90.0, places=2)
        self.assertAlmostEqual(dist, 10.0, places=2)

    def test_a_higher_swing_low_takes_over(self):
        stop, basis, _ = ml.trailing_stop(row(recent_swing_low=95.0))
        self.assertEqual(basis, "swing_low")
        self.assertAlmostEqual(stop, 95.0, places=2)

    def test_the_ma50_floor_can_bind_when_volatility_is_wide(self):
        stop, basis, _ = ml.trailing_stop(
            row(atr_14=20.0, recent_swing_low=60.0, ma_50=95.0))
        self.assertEqual(basis, "ma50")
        self.assertAlmostEqual(stop, 92.15, places=2)

    def test_no_stop_below_the_price_means_no_stop_at_all(self):
        # Price under every floor: not a formatting problem, a real "this is not
        # an uptrend" answer.
        stop, basis, dist = ml.trailing_stop(
            row(close=50.0, atr_14=None, recent_swing_low=60.0, ma_50=80.0))
        self.assertIsNone(stop)
        self.assertIsNone(basis)
        self.assertIsNone(dist)

    def test_an_entry_is_never_emitted_without_a_stop(self):
        # §8, the hard rule: the tool refuses to call something an entry it
        # cannot give an exit for.
        out = ml.score_row(row(atr_14=None, recent_swing_low=None, ma_50=None,
                               ma_200=None))
        self.assertIsNone(out["trailing_stop"])
        self.assertNotEqual(out["triage"], ml.TRIAGE_ENTRY)

    def test_the_first_target_is_a_multiple_of_the_risk(self):
        out = ml.score_row(row())            # stop 90, risk 10
        self.assertAlmostEqual(out["r_multiple_target"], 125.0, places=2)


class MonitorModeTests(unittest.TestCase):
    def test_a_broken_trend_reports_the_exit(self):
        out = ml.monitor_row(row(close=89.0, atr_14=4.0, recent_swing_low=90.0))
        self.assertTrue(out["stop_hit"])
        self.assertIn("exit", out["action"])

    def test_an_intact_trend_holds(self):
        out = ml.monitor_row(row())
        self.assertFalse(out["stop_hit"])
        self.assertIn("hold", out["action"])

    def test_monitor_does_not_re_score(self):
        # A held position has one question — is the trend intact. Re-scoring
        # invites re-justifying a loser, which the spec names as the primary
        # failure mode.
        out = ml.monitor_row(row())
        self.assertNotIn("momentum_score", out)
        self.assertNotIn("triage", out)


class InstitutionalConfirmationTests(unittest.TestCase):
    def test_both_buying_is_full_confirmation(self):
        confirmed, score = ml.inst_confirmation(
            {"foreign_trend_net": 1, "trust_trend_net": 1})
        self.assertTrue(confirmed)
        self.assertEqual(score, 1.0)

    def test_trust_buying_into_foreign_selling_is_not_confirmation(self):
        confirmed, score = ml.inst_confirmation(
            {"foreign_trend_net": -1, "trust_trend_net": 1})
        self.assertFalse(confirmed)
        self.assertLess(score, 0.5)

    def test_no_flow_data_is_not_confirmation(self):
        confirmed, _ = ml.inst_confirmation({})
        self.assertFalse(confirmed)

    def test_confirmation_can_be_waived_by_the_caller(self):
        r = row(foreign_trend_net=None, trust_trend_net=None)
        self.assertNotEqual(ml.score_row(r)["triage"], ml.TRIAGE_ENTRY)
        self.assertEqual(
            ml.score_row(r, require_inst_confirm=False)["triage"],
            ml.TRIAGE_ENTRY)


if __name__ == "__main__":
    unittest.main()


class StopDirectionTests(unittest.TestCase):
    """Entry and monitor need OPPOSITE handling of a stop above the price.

    Caught by the acceptance run: monitor mode discarded any candidate stop
    above the close, which silently slid the stop down and reported "hold" no
    matter how far price fell. The exit signal the mode exists to produce could
    never fire.
    """

    def test_entry_discards_a_stop_above_the_price(self):
        # You cannot open a position with a stop above where you bought.
        stop, _, _ = ml.trailing_stop(
            row(close=89.0, atr_14=None, recent_swing_low=90.0, ma_50=None),
            for_entry=True)
        self.assertIsNone(stop)

    def test_monitor_keeps_it_because_that_is_the_break(self):
        stop, basis, _ = ml.trailing_stop(
            row(close=89.0, atr_14=None, recent_swing_low=90.0, ma_50=None),
            for_entry=False)
        self.assertEqual((stop, basis), (90.0, "swing_low"))

    def test_a_position_broken_through_its_swing_low_exits(self):
        out = ml.monitor_row(row(close=89.0, atr_14=4.0, recent_swing_low=90.0))
        self.assertTrue(out["stop_hit"])


class EngineSeparationTests(unittest.TestCase):
    """§5: the two scanners' logic is inverted and must stay strictly separate.

    Not pedantry — sharing a helper between them silently breaks both, because
    the same input means opposite things. These assert the inversion holds.
    """

    def test_a_high_pe_never_penalises_a_momentum_name(self):
        # In flow_leaders a story-premium P/E is an anti-flag. Here you are
        # paying for the trend, so it must not move the verdict.
        cheap = ml.score_row(row(pe_ratio=11.0))
        rich = ml.score_row(row(pe_ratio=95.0))
        self.assertEqual(cheap["triage"], rich["triage"])
        self.assertEqual(cheap["momentum_score"], rich["momentum_score"])

    def test_a_flat_price_is_disqualifying_here_and_required_there(self):
        # "Has not run yet" is the sleeper requirement and the momentum failure.
        flat = ml.score_row(row(rs_percentile=20.0, close=100.0, ma_50=101.0,
                                ma_50_prev=101.5, high_3m=130.0,
                                volume_ratio_20=0.5))
        self.assertNotEqual(flat["triage"], ml.TRIAGE_ENTRY)

    def test_the_momentum_module_shares_no_scoring_with_flow_leaders(self):
        # A cheap structural check: importing one must not pull the other's
        # thresholds into scope, which is how a "shared helper" refactor would
        # start.
        import mcp_server.api.flow_leaders as fl
        overlap = {n for n in dir(ml) if n.isupper()} & {n for n in dir(fl) if n.isupper()}
        self.assertEqual(overlap, set(), f"shared constants invite drift: {overlap}")
