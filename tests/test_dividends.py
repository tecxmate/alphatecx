import unittest

from src.harvester import twse


class RocDateTests(unittest.TestCase):
    def test_roc_chinese_date_to_iso(self):
        self.assertEqual(twse._roc_cn_to_iso("115年07月01日"), "2026-07-01")
        self.assertEqual(twse._roc_cn_to_iso("114年12月31日"), "2025-12-31")

    def test_single_digit_month_and_day_are_padded(self):
        self.assertEqual(twse._roc_cn_to_iso("115年3月5日"), "2026-03-05")

    def test_malformed_is_none(self):
        self.assertIsNone(twse._roc_cn_to_iso(""))
        self.assertIsNone(twse._roc_cn_to_iso("2026-07-01"))
        self.assertIsNone(twse._roc_cn_to_iso("not a date"))


if __name__ == "__main__":
    unittest.main()
