import unittest

from src.harvester import finmind as fm


class ParseDividendPolicyTests(unittest.TestCase):
    def test_splits_cash_and_stock_and_normalizes_roc_year(self):
        # 台中銀 114年: cash 0.39, stock 0.67 — the exact split the blended 殖利率 hid.
        raw = [{
            "year": "114年",
            "CashEarningsDistribution": 0.39, "CashStatutorySurplus": 0.0,
            "StockEarningsDistribution": 0.67, "StockStatutorySurplus": 0.0,
            "CashExDividendTradingDate": "2026-08-04",
            "StockExDividendTradingDate": "2026-08-04",
            "AnnouncementDate": "2026-07-17",
        }]
        out = fm.parse_dividend_policy(raw, "2812")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["year"], 2025)          # 114 + 1911
        self.assertAlmostEqual(out[0]["cash_dividend"], 0.39)
        self.assertAlmostEqual(out[0]["stock_dividend"], 0.67)
        self.assertEqual(out[0]["cash_ex_date"], "2026-08-04")

    def test_sums_earnings_and_statutory_surplus(self):
        raw = [{"year": "2024", "CashEarningsDistribution": 1.0,
                "CashStatutorySurplus": 0.5, "StockEarningsDistribution": 0.0}]
        out = fm.parse_dividend_policy(raw, "9999")
        self.assertAlmostEqual(out[0]["cash_dividend"], 1.5)

    def test_blank_dates_become_none(self):
        raw = [{"year": "2023", "CashExDividendTradingDate": "",
                "StockExDividendTradingDate": "0"}]
        out = fm.parse_dividend_policy(raw, "1")
        self.assertIsNone(out[0]["cash_ex_date"])
        self.assertIsNone(out[0]["stock_ex_date"])


class FillProbabilityTests(unittest.TestCase):
    AS_OF = "2026-07-24"

    def _ev(self, ex, before, mx):
        return {"ex_date": ex, "before_price": before, "max_price": mx}

    def test_all_filled_is_one(self):
        rows = [self._ev("2024-07-23", 19.55, 19.9),
                self._ev("2025-08-13", 23.4, 23.55)]
        prob, n, last = fm.fill_probability(rows, self.AS_OF)
        self.assertEqual(prob, 1.0)
        self.assertEqual(n, 2)
        self.assertEqual(last, "2025-08-13")

    def test_never_filled_is_zero_the_trap_signature(self):
        # 晶華-style: post-ex high never reaches the pre-ex close.
        rows = [self._ev("2022-06-01", 200.0, 180.0),
                self._ev("2023-06-01", 190.0, 175.0),
                self._ev("2024-06-01", 185.0, 170.0)]
        prob, n, _ = fm.fill_probability(rows, self.AS_OF)
        self.assertEqual(prob, 0.0)
        self.assertEqual(n, 3)

    def test_events_outside_window_are_ignored(self):
        rows = [self._ev("2010-06-01", 50.0, 60.0)]   # >5y before as_of
        prob, n, _ = fm.fill_probability(rows, self.AS_OF)
        self.assertIsNone(prob)
        self.assertEqual(n, 0)

    def test_missing_prices_do_not_count(self):
        rows = [self._ev("2025-06-01", None, 10.0),
                self._ev("2025-07-01", 10.0, None)]
        prob, n, _ = fm.fill_probability(rows, self.AS_OF)
        self.assertIsNone(prob)
        self.assertEqual(n, 0)


class GovernanceKeywordTests(unittest.TestCase):
    def test_flags_laundering_and_indictment(self):
        self.assertTrue(fm.is_governance_title("台中銀6員工遭起訴 涉洗錢36億"))
        self.assertTrue(fm.is_governance_title("某公司遭搜索 疑掏空"))

    def test_ordinary_news_is_not_governance(self):
        self.assertFalse(fm.is_governance_title("台中銀下半年的走勢會如何？今年獲利如何？"))


class ParseNewsTests(unittest.TestCase):
    def test_dedup_hash_and_governance_flag(self):
        raw = [{"date": "2026-06-01 06:51:02", "title": "涉洗錢遭起訴",
                "source": "CMoney", "link": "https://x/1"}]
        out = fm.parse_news(raw, "2812")
        self.assertEqual(out[0]["news_date"], "2026-06-01")
        self.assertTrue(out[0]["is_governance"])
        self.assertEqual(len(out[0]["title_hash"]), 32)
        self.assertEqual(out[0]["url"], "https://x/1")

    def test_untitled_rows_dropped(self):
        self.assertEqual(fm.parse_news([{"date": "2026-06-01", "title": ""}], "1"), [])


if __name__ == "__main__":
    unittest.main()
