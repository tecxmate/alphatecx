"""Entry checklist, message formatting, and the two PRD review gates.

PRD §5 M7 and §6 both state constraints as *code-review acceptance conditions*
rather than as behaviours:

  - the 金口訣 / 節律 layer may veto a day and nothing else — it must not appear
    in any score, light, or alert trigger;
  - the 兵法 quote table is presentation only, on the same terms;
  - the checklist must never phrase anything as a buy recommendation.

A review condition that only exists in prose survives exactly as long as the
reviewer's attention. These tests turn all three into failing assertions.
"""
import inspect
import unittest

from mcp_server.api.rg import checklist, light, messages, scoring, stops
from mcp_server.api.rg import config as cfg


def facts(**over):
    base = {"ticker_id": "3231", "name": "緯創", "risk_light": "green",
            "sector_rank": None, "gain_5d_pct": 2.0, "is_disposition": None,
            "no_trade_reason": None, "buy_amount": None, "available_cash": None}
    base.update(over)
    return base


class ChecklistTests(unittest.TestCase):
    def test_clean_sheet_says_nothing_stops_you_and_never_says_buy(self):
        result = checklist.evaluate(facts())
        self.assertEqual(result["verdict"], "clear")
        self.assertEqual(result["summary"], cfg.VERDICT_CLEAR)
        self.assertNotIn("買進", result["summary"])
        self.assertNotIn("建議", result["summary"])

    def test_red_light_blocks_q1(self):
        result = checklist.evaluate(facts(risk_light="red"))
        self.assertEqual(result["verdict"], "blocked")
        self.assertTrue(result["summary"].startswith(cfg.VERDICT_BLOCKED))

    def test_vertical_run_blocks_q3_the_175_case(self):
        # PRD §10 case 1: 3231 at 175 after a four-day +25.9% run.
        result = checklist.evaluate(facts(gain_5d_pct=25.9))
        q3 = next(q for q in result["questions"] if q["id"] == 3)
        self.assertEqual(q3["status"], "fail")
        self.assertEqual(result["verdict"], "blocked")

    def test_gain_just_under_the_limit_passes(self):
        result = checklist.evaluate(facts(gain_5d_pct=cfg.MAX_5D_GAIN_PCT - 0.1))
        self.assertEqual(result["verdict"], "clear")

    def test_oversized_buy_blocks_q6(self):
        result = checklist.evaluate(facts(buy_amount=80_000, available_cash=100_000))
        q6 = next(q for q in result["questions"] if q["id"] == 6)
        self.assertEqual(q6["status"], "fail")

    def test_buy_within_the_cash_limit_passes_q6(self):
        result = checklist.evaluate(facts(buy_amount=70_000, available_cash=100_000))
        q6 = next(q for q in result["questions"] if q["id"] == 6)
        self.assertEqual(q6["status"], "pass")

    def test_unbuilt_modules_report_skipped_not_pass_and_are_surfaced(self):
        result = checklist.evaluate(facts())
        statuses = {q["id"]: q["status"] for q in result["questions"]}
        self.assertEqual(statuses[2], "skipped")   # M3 sector rank
        self.assertEqual(statuses[4], "skipped")   # M6 disposition
        self.assertTrue(any("未驗證" in w for w in result["warnings"]))

    def test_blacklisted_name_is_warned_about(self):
        result = checklist.evaluate(
            facts(blacklisted=True, blacklist_note="拉黑:2026/7 週期 -55%"))
        self.assertTrue(any("拉黑" in w for w in result["warnings"]))

    def test_all_six_questions_are_always_returned(self):
        self.assertEqual([q["id"] for q in checklist.evaluate(facts())["questions"]],
                         [1, 2, 3, 4, 5, 6])

    def test_multiple_failures_are_all_named_in_the_summary(self):
        result = checklist.evaluate(facts(risk_light="red", gain_5d_pct=30.0))
        self.assertEqual(result["failed_count"], 2)
        self.assertIn("垂直段", result["summary"])


class M7VetoTests(unittest.TestCase):
    """M7 has veto power over a day and no other power at all."""

    def test_no_trade_day_blocks_q5(self):
        result = checklist.evaluate(facts(no_trade_reason="節律日"))
        q5 = next(q for q in result["questions"] if q["id"] == 5)
        self.assertEqual(q5["status"], "fail")
        self.assertEqual(result["verdict"], "blocked")

    def test_veto_does_not_alter_the_risk_score(self):
        metrics = {"taiex_close": 45000.0, "taiex_pct": 0.5, "ma20": 44000.0,
                   "ma60": 43000.0, "adv_ratio_5d": 0.55,
                   "margin_chg_5d_pct": 0.5, "taiex_ret_5d_pct": 1.0,
                   "fut_foreign_net_oi": 5000}
        baseline, _ = scoring.score_day(metrics)
        with_veto, _ = scoring.score_day({**metrics, "no_trade_reason": "節律日"})
        self.assertEqual(baseline, with_veto)

    def test_scoring_and_light_modules_never_reference_the_veto_or_the_quotes(self):
        # Structural, not behavioural: if someone later wires 節律 or 兵法 into a
        # scoring path, this fails at source-read time rather than in production.
        for module in (scoring, light, stops):
            src = inspect.getsource(module)
            for banned in ("no_trade", "SUNZI", "兵法", "金口訣"):
                self.assertNotIn(banned, src,
                                 f"{module.__name__} must not reference {banned}")

    def test_sunzi_table_is_only_read_by_the_message_layer(self):
        self.assertIn("SUNZI_BY_KIND", inspect.getsource(messages))
        self.assertNotIn("SUNZI_BY_KIND", inspect.getsource(checklist))


class MessageTests(unittest.TestCase):
    def test_alert_has_head_fact_action_and_quote(self):
        alert = {"kind": "stop_exit", "ticker_id": "2324", "name": "仁寶",
                 "severity": "critical", "close": 29.05, "line": 28.6,
                 "line_is_fallback": False, "action": "明天開盤全數出場。"}
        out = messages.format_alert(alert, light="red")
        self.assertIn("仁寶(2324)", out)
        self.assertIn("29.05", out)
        self.assertIn("👉", out)
        self.assertIn(cfg.SUNZI_BY_KIND["stop_exit"], out)

    def test_alert_without_an_action_still_gets_one(self):
        out = messages.format_alert({"kind": "unknown_kind", "severity": "info"})
        self.assertIn("👉", out)

    def test_html_metacharacters_are_escaped(self):
        out = messages.format_alert(
            {"kind": "x", "ticker_id": "1", "name": "<b>&", "severity": "info"})
        self.assertIn("&lt;b&gt;&amp;", out)

    def test_light_change_lists_scoring_subitems_and_missing_data(self):
        _, reasons = scoring.score_day(
            {"taiex_close": 42000.0, "taiex_pct": -6.5, "ma20": 45000.0,
             "ma60": 44000.0, "adv_ratio_5d": 0.1})
        out = messages.format_light_change("yellow", "red", 7, reasons,
                                           missing=["futures", "margin"])
        self.assertIn("red", out)
        self.assertIn("資料缺漏", out)
        self.assertIn("futures", out)
        self.assertIn("👉", out)

    def test_checklist_render_never_contains_a_buy_recommendation(self):
        for f in (facts(), facts(risk_light="red"), facts(gain_5d_pct=30.0)):
            out = messages.format_checklist(checklist.evaluate(f))
            self.assertNotIn("建議買", out)
            self.assertNotIn("可以買", out)

    def test_green_light_message_uses_the_no_glory_quote(self):
        _, reasons = scoring.score_day({"taiex_close": 1.0, "taiex_pct": 0.1,
                                        "ma20": 0.5, "ma60": 0.4})
        out = messages.format_light_change("yellow", "green", 0, reasons)
        self.assertIn(cfg.SUNZI_BY_KIND["risk_light_green"], out)


if __name__ == "__main__":
    unittest.main()
