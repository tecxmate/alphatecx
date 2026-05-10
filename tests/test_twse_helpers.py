import unittest
from datetime import date

from src.harvester import twse


class TwseHelperTests(unittest.TestCase):
    def test_numeric_parsers_handle_exchange_placeholders(self):
        self.assertEqual(twse._to_int("1,234"), 1234)
        self.assertEqual(twse._to_int("--"), 0)
        self.assertEqual(twse._to_float("12.5%"), 12.5)
        self.assertIsNone(twse._to_float("--"))

    def test_roc_date_conversion(self):
        self.assertEqual(twse._roc_to_iso("115/04/29"), "2026-04-29")
        self.assertEqual(twse._roc_to_iso("2026-04-29"), "2026-04-29")

    def test_trading_day_candidates_skip_weekends(self):
        self.assertEqual(
            twse.trading_day_candidates(3, from_date=date(2026, 5, 11)),
            ["20260511", "20260508", "20260507"],
        )
