import unittest
from decimal import Decimal
from unittest.mock import patch

from mcp_server.api import limit_board as lb


def D(v):
    return Decimal(str(v))


class TickTableTests(unittest.TestCase):
    def test_tick_chosen_by_band_of_candidate_price_not_reference(self):
        # ref 96 -> x1.1 = 105.6 crosses into the 100-500 band (0.50 tick),
        # so the limit is 105.50 and not 105.65 as the reference's own
        # 0.10 tick would give. This straddle is the spec's §3 warning.
        self.assertEqual(lb.limit_up(D(96)), D("105.50"))

    def test_limit_up_floors_and_limit_down_ceils_to_tick(self):
        # Both round *inward*, so the band is never breached.
        self.assertEqual(lb.limit_up(D("26.35")), D("28.95"))    # 28.985 -> floor
        self.assertEqual(lb.limit_down(D("70.90")), D("63.90"))  # 63.81 -> ceil

    def test_tick_boundaries_are_exclusive_at_the_top(self):
        self.assertEqual(lb.tick_of(D("9.99")), D("0.01"))
        self.assertEqual(lb.tick_of(D("10")), D("0.05"))
        self.assertEqual(lb.tick_of(D("49.99")), D("0.05"))
        self.assertEqual(lb.tick_of(D("50")), D("0.10"))
        self.assertEqual(lb.tick_of(D("100")), D("0.50"))
        self.assertEqual(lb.tick_of(D("500")), D("1.00"))
        self.assertEqual(lb.tick_of(D("1000")), D("5.00"))

    def test_exact_tick_multiples_do_not_drift_below_the_limit(self):
        # 80 x 1.1 == 88.0 exactly; binary float would floor this to 87.9.
        self.assertEqual(lb.limit_up(D(80)), D("88.00"))

    def test_real_session_limits_match_the_exchange(self):
        # Sampled from the 2026-07-16 close and cross-checked against the
        # exchange's own published limit prices.
        for ref, up in [(D(80), D("88.00")), (D(11), D("12.10")),
                        (D("348.00"), D("382.50")), (D("374.00"), D("411.00"))]:
            self.assertEqual(lb.limit_up(ref), up, f"limit_up({ref})")
        for ref, down in [(D(1415), D("1275.00")), (D(523), D("471.00")),
                          (D(379), D("341.50")), (D("269.50"), D("243.00"))]:
            self.assertEqual(lb.limit_down(ref), down, f"limit_down({ref})")


class ParsingTests(unittest.TestCase):
    def test_sign_column_survives_twse_html_colour_wrapper(self):
        self.assertEqual(lb._sign("<p style= color:red>+</p>"), 1)
        self.assertEqual(lb._sign("<p style= color:green>-</p>"), -1)
        self.assertEqual(lb._sign("X"), 0)
        self.assertEqual(lb._sign(""), 0)

    def test_dec_handles_exchange_placeholders_and_thousands(self):
        self.assertEqual(lb._dec("1,275.00"), D("1275.00"))
        self.assertIsNone(lb._dec("--"))
        self.assertIsNone(lb._dec(""))
        self.assertIsNone(lb._dec(None))

    def test_price_normalises_each_exchange_no_quote_spelling(self):
        # The two exchanges disagree: TWSE prints '--' for an exhausted book
        # side, TPEX prints '0.00'. Both must read as "no quote", or every
        # TPEX lock goes undetected.
        self.assertIsNone(lb._price("--"))
        self.assertIsNone(lb._price("0.00"))
        self.assertIsNone(lb._price(""))
        self.assertEqual(lb._price("58.40"), D("58.40"))

    def test_only_four_digit_codes_count_as_equities(self):
        self.assertTrue(lb._is_equity("2330"))
        self.assertFalse(lb._is_equity("00400A"))  # active ETF
        self.assertFalse(lb._is_equity("006203"))  # ETF
        self.assertFalse(lb._is_equity("03028P"))  # warrant


class RowBuildTests(unittest.TestCase):
    def _row(self, **kw):
        base = dict(
            ticker_id="9921", name="巨大", market="TWSE",
            close=D(88), change=D(8), open_=D("85.5"), high=D(88), low=D("84.8"),
            volume_shares=D(3299453), turnover_twd=D(288636064),
            bid_price=D(88), bid_lots=D(3732), ask_price=None, ask_lots=D(0),
        )
        base.update(kw)
        return lb._build_row(**base)

    def test_reference_price_is_derived_from_close_minus_change(self):
        r = self._row()
        self.assertEqual(r["reference_price"], 80.0)
        self.assertEqual(r["pct_change"], 10.0)

    def test_locked_up_when_ask_side_is_exhausted(self):
        r = self._row()
        self.assertTrue(r["is_at_limit"])
        self.assertEqual(r["limit_direction"], "up")
        self.assertTrue(r["is_locked"])
        self.assertEqual(r["bid_lots_at_close"], 3732)

    def test_at_limit_but_unlocked_when_an_ask_remains(self):
        # 6141 柏承: closed at the 43.75 limit but with 16 lots still offered.
        r = self._row(ticker_id="6141", close=D("43.75"), change=D("3.95"),
                      bid_price=D("43.60"), bid_lots=D(7),
                      ask_price=D("43.75"), ask_lots=D(16))
        self.assertTrue(r["is_at_limit"])
        self.assertFalse(r["is_locked"])

    def test_near_limit_name_is_not_reported_at_limit(self):
        # 6202 盛群 closed -9.59% with the limit at -9.87%.
        r = self._row(ticker_id="6202", close=D("64.10"), change=D("-6.80"),
                      bid_price=D("64.00"), bid_lots=D(59),
                      ask_price=D("64.10"), ask_lots=D(16))
        self.assertEqual(r["pct_change"], -9.59)
        self.assertFalse(r["is_at_limit"])
        self.assertIsNone(r["is_locked"])

    def test_tpex_zero_quote_is_a_lock_not_a_live_offer(self):
        # 2221 大甲 on TPEX: limit-up with 最後賣價 published as '0.00'.
        # Parsed literally this reads as a 0.00 offer and the lock is missed.
        r = self._row(ticker_id="2221", market="TPEX",
                      close=D("58.40"), change=D("5.30"),
                      bid_price=lb._price("58.40"), bid_lots=D(252),
                      ask_price=lb._price("0.00"), ask_lots=D(0))
        self.assertTrue(r["is_at_limit"])
        self.assertTrue(r["is_locked"])

    def test_limit_down_lock_detected_from_missing_bid(self):
        # 8046 南電, prev 1415 -> limit down 1275 on the 5.00 tick.
        r = self._row(ticker_id="8046", close=D(1275), change=D(-140),
                      bid_price=None, bid_lots=D(0),
                      ask_price=D(1275), ask_lots=D(733))
        self.assertEqual(r["limit_direction"], "down")
        self.assertTrue(r["is_locked"])

    def test_no_limit_security_is_flagged_not_treated_as_a_limit_hit(self):
        # New listings trade without a band; a 40% move must not be reported
        # as "at the limit" off a limit price that does not exist.
        r = self._row(close=D(140), change=D(40))
        self.assertFalse(r["has_price_limit"])
        self.assertFalse(r["is_at_limit"])
        self.assertIsNone(r["limit_up_price"])

    def test_unparseable_or_untraded_rows_are_dropped(self):
        self.assertIsNone(self._row(close=None))
        self.assertIsNone(self._row(change=None))
        self.assertIsNone(self._row(close=D(5), change=D(5)))  # reference 0


class TwseStatTests(unittest.TestCase):
    """A refused query must never be mistaken for a quiet holiday.

    If it is, `scan_limit_board` answers with TPEX alone and presents half the
    market as the board, with nothing in `errors`.
    """

    def _fetch(self, payload):
        with patch.object(lb, "_get_json", return_value=(payload, None)):
            return lb.fetch_twse_board("20260716")

    def test_no_session_is_not_an_error(self):
        rows, err = self._fetch({"stat": "很抱歉，沒有符合條件的資料!", "tables": []})
        self.assertEqual(rows, [])
        self.assertIsNone(err)

    def test_refusal_is_reported_rather_than_read_as_a_holiday(self):
        rows, err = self._fetch({"stat": "查詢日期大於今日，請重新查詢!", "tables": []})
        self.assertEqual(rows, [])
        self.assertIn("refused", err)

    def test_empty_response_is_an_error(self):
        rows, err = self._fetch(None)
        self.assertEqual(rows, [])
        self.assertIsNotNone(err)

    def test_transport_failure_is_reported(self):
        with patch.object(lb, "_get_json", return_value=(None, "Timeout: too slow")):
            rows, err = lb.fetch_twse_board("20260716")
        self.assertEqual(rows, [])
        self.assertIn("Timeout", err)

    def test_board_table_is_found_by_columns_not_position(self):
        # MI_INDEX ships ~10 tables and their order is not contractual.
        payload = {"stat": "OK", "tables": [
            {"fields": ["指數", "收盤指數"], "data": [["x", "1"]]},
            {"fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額",
                        "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)",
                        "漲跌價差", "最後揭示買價", "最後揭示買量",
                        "最後揭示賣價", "最後揭示賣量", "本益比"],
             "data": [["9921", "巨大", "3,299,453", "1,937", "288,636,064",
                       "85.50", "88.00", "84.80", "88.00",
                       "<p style= color:red>+</p>", "8.00",
                       "88.00", "3,732", "--", "0", "220.00"]]},
        ]}
        rows, err = self._fetch(payload)
        self.assertIsNone(err)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker_id"], "9921")
        self.assertTrue(rows[0]["is_locked"])


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"ticker_id": "A", "pct_change": 10.0, "is_locked": True,
             "turnover_twd": 300_000_000, "is_at_limit": True},
            {"ticker_id": "B", "pct_change": 9.6, "is_locked": False,
             "turnover_twd": 1_000_000, "is_at_limit": True},
            {"ticker_id": "C", "pct_change": -10.0, "is_locked": True,
             "turnover_twd": 50_000_000, "is_at_limit": True},
            {"ticker_id": "D", "pct_change": 2.0, "is_locked": None,
             "turnover_twd": 90_000_000, "is_at_limit": False},
        ]

    def _ids(self, **kw):
        kw.setdefault("direction", "up")
        kw.setdefault("min_pct", 9.5)
        kw.setdefault("locked_only", False)
        kw.setdefault("min_turnover_twd", 0)
        return [r["ticker_id"] for r in lb.filter_board(self.rows, **kw)]

    def test_direction_up_excludes_limit_down_names(self):
        self.assertEqual(self._ids(), ["A", "B"])

    def test_direction_down_excludes_limit_up_names(self):
        self.assertEqual(self._ids(direction="down"), ["C"])

    def test_direction_both_uses_absolute_move(self):
        self.assertEqual(self._ids(direction="both"), ["A", "C", "B"])

    def test_locked_only_drops_unlocked_and_null_locks(self):
        self.assertEqual(self._ids(direction="both", locked_only=True), ["A", "C"])

    def test_turnover_floor_applies(self):
        self.assertEqual(self._ids(min_turnover_twd=20_000_000), ["A"])

    def test_results_are_ordered_by_move_size(self):
        self.assertEqual(self._ids(direction="both", min_pct=0),
                         ["A", "C", "B", "D"])


class TriageTests(unittest.TestCase):
    def test_cheap_and_accumulating_with_no_anti_flag_is_a_sleeper(self):
        out = lb.apply_triage({
            "pe_ratio": 12.0, "dividend_yield": 4.0, "foreign_held_pct": 8.0,
            "foreign_net_z20": 1.8, "margin_pct_of_limit": 2.0,
            "foreign_net_5d": 500, "is_at_limit": True, "_valuation_known": True,
        })
        self.assertEqual(out["triage"], "sleeper")
        self.assertEqual(
            set(out["sleeper_flags"]),
            {"cheap", "yield", "under_owned", "accumulating", "no_froth"},
        )

    def test_any_anti_flag_forces_chase_even_with_sleeper_flags(self):
        out = lb.apply_triage({
            "pe_ratio": 12.0, "foreign_net_z20": 1.8, "foreign_net_5d": -900,
            "is_at_limit": True, "_valuation_known": True,
        })
        self.assertIn("distributing_into_pop", out["sleeper_flags"])
        self.assertEqual(out["triage"], "chase")

    def test_rich_multiple_is_a_chase(self):
        # 9921 巨大 on 2026-07-16: limit-up on a 220x trailing P/E.
        out = lb.apply_triage({
            "pe_ratio": 220.0, "foreign_held_pct": 22.3,
            "is_at_limit": True, "_valuation_known": True,
        })
        self.assertEqual(out["triage"], "chase")
        self.assertIn("story_premium", out["sleeper_flags"])

    def test_missing_valuation_row_is_not_read_as_missing_earnings(self):
        # A TPEX name we hold no BWIBBU row for must not be auto-labelled a
        # chase; §8 says 上櫃 is where much of the limit-up action lives.
        out = lb.apply_triage({
            "pe_ratio": None, "_valuation_known": False,
            "foreign_net_z20": 1.5, "is_at_limit": True,
        })
        self.assertNotIn("no_earnings", out["sleeper_flags"])
        self.assertEqual(out["triage"], "watch")

    def test_known_absent_earnings_is_an_anti_flag(self):
        out = lb.apply_triage({
            "pe_ratio": None, "_valuation_known": True, "is_at_limit": True,
        })
        self.assertIn("no_earnings", out["sleeper_flags"])
        self.assertEqual(out["triage"], "chase")

    def test_null_enrichment_degrades_to_watch_rather_than_raising(self):
        out = lb.apply_triage({"is_at_limit": True})
        self.assertEqual(out["sleeper_flags"], [])
        self.assertEqual(out["triage"], "watch")

    def test_triage_does_not_mutate_the_input_hit(self):
        hit = {"pe_ratio": 12.0, "is_at_limit": True}
        lb.apply_triage(hit)
        self.assertNotIn("triage", hit)


if __name__ == "__main__":
    unittest.main()
