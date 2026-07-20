import unittest

from mcp_server.api import quote as q


class NumParseTests(unittest.TestCase):
    def test_dash_and_blank_are_none_not_zero(self):
        self.assertIsNone(q._num("-"))
        self.assertIsNone(q._num(""))
        self.assertIsNone(q._num(None))
        self.assertEqual(q._num("2320.0000"), 2320.0)

    def test_first_depth_level(self):
        self.assertEqual(q._first("58.40_58.30_58.20"), 58.40)
        self.assertIsNone(q._first(""))


def msg(**over):
    m = dict(c="2330", n="台積電", ex="tse", z="2320.0000", y="2290.0000",
             u="2515.0000", w="2065.0000", o="2300.0000", h="2345.0000",
             l="2300.0000", v="45133", tv="6436", t="13:30:00",
             a="2321.0000_2322.0000", b="2320.0000_2319.0000")
    m.update(over)
    return m


class ParseMsgTests(unittest.TestCase):
    def test_basic_fields_and_pct(self):
        r = q.parse_msg(msg())
        self.assertEqual(r["ticker_id"], "2330")
        self.assertEqual(r["market"], "TWSE")
        self.assertEqual(r["last_price"], 2320.0)
        self.assertEqual(r["pct_change"], round((2320/2290 - 1) * 100, 2))
        self.assertEqual(r["best_ask"], 2321.0)
        self.assertEqual(r["best_bid"], 2320.0)

    def test_otc_maps_to_tpex(self):
        self.assertEqual(q.parse_msg(msg(ex="otc"))["market"], "TPEX")

    def test_no_print_yields_null_price_and_null_at_limit(self):
        # z='-' before the first trade must not fabricate a price or a limit hit.
        r = q.parse_msg(msg(z="-"))
        self.assertIsNone(r["last_price"])
        self.assertIsNone(r["is_at_limit"])
        self.assertIsNone(r["pct_change"])

    def test_limit_up_detected_from_authoritative_u(self):
        r = q.parse_msg(msg(z="2515.0000"))
        self.assertTrue(r["is_at_limit"])
        self.assertEqual(r["limit_direction"], "up")

    def test_limit_down_detected_from_authoritative_w(self):
        r = q.parse_msg(msg(z="2065.0000"))
        self.assertTrue(r["is_at_limit"])
        self.assertEqual(r["limit_direction"], "down")

    def test_mid_session_is_not_at_limit(self):
        r = q.parse_msg(msg(z="2320.0000"))
        self.assertFalse(r["is_at_limit"])
        self.assertIsNone(r["limit_direction"])


if __name__ == "__main__":
    unittest.main()
