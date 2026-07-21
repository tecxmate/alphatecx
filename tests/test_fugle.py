import unittest

from mcp_server.api import fugle


def payload(**over):
    j = {
        "symbol": "2330", "name": "台積電", "market": "TSE",
        "referencePrice": 2320.0, "previousClose": 2320.0,
        "lastPrice": 2410.0, "lastSize": 3, "changePercent": 3.88,
        "openPrice": 2350.0, "highPrice": 2410.0, "lowPrice": 2345.0,
        "bids": [{"price": 2405.0, "size": 57}],
        "asks": [{"price": 2410.0, "size": 659}],
        "total": {"tradeVolume": 29811},
        "lastUpdated": 1784611800000000,
        "date": "2026-07-21",
    }
    j.update(over)
    return j


class ParseQuoteTests(unittest.TestCase):
    def test_basic_fields(self):
        r = fugle.parse_quote(payload())
        self.assertEqual(r["ticker_id"], "2330")
        self.assertEqual(r["market"], "TWSE")
        self.assertEqual(r["last_price"], 2410.0)
        self.assertEqual(r["prev_close"], 2320.0)
        self.assertEqual(r["pct_change"], 3.88)
        self.assertEqual(r["best_bid"], 2405.0)
        self.assertEqual(r["best_ask"], 2410.0)
        self.assertEqual(r["volume_shares_lots"], 29811.0)

    def test_otc_maps_to_tpex(self):
        self.assertEqual(fugle.parse_quote(payload(market="OTC"))["market"], "TPEX")

    def test_limit_prices_computed_from_reference_via_tick_table(self):
        # reference 2320 -> +10% = 2552, floored to the 5.00 tick = 2550.
        r = fugle.parse_quote(payload(referencePrice=2320.0))
        self.assertEqual(r["limit_up_price"], 2550.0)
        self.assertEqual(r["limit_down_price"], 2090.0)  # 2088 ceil to 5.00 tick

    def test_at_limit_up_when_last_reaches_computed_limit(self):
        r = fugle.parse_quote(payload(referencePrice=2320.0, lastPrice=2550.0))
        self.assertTrue(r["is_at_limit"])
        self.assertEqual(r["limit_direction"], "up")

    def test_missing_last_price_is_null_not_a_false_limit(self):
        r = fugle.parse_quote(payload(lastPrice=None))
        self.assertIsNone(r["last_price"])
        self.assertIsNone(r["is_at_limit"])

    def test_missing_reference_leaves_limits_null(self):
        r = fugle.parse_quote(payload(referencePrice=None))
        self.assertIsNone(r["limit_up_price"])
        self.assertIsNone(r["limit_down_price"])

    def test_epoch_micros_render_as_taipei_iso(self):
        r = fugle.parse_quote(payload())
        self.assertTrue(r["quote_time"].endswith("+08:00"))


if __name__ == "__main__":
    unittest.main()
