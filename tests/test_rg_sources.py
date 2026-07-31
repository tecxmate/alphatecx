"""Parsers for the two feeds Risk Guard adds (PRD §2).

Both payloads are undocumented and change without notice, so the parsers are
tested against captured real responses rather than mocks of our own assumptions.
The fixtures below are trimmed copies of live 2026-07-30 responses.
"""
import unittest

from riskguard import sources

# TWSE MI_INDEX?type=MS, table 7. The 整體市場 column counts warrants, ETFs and
# convertibles; the 股票 column is the ~1,000 common stocks we actually mean.
MI_INDEX_MS = {
    "stat": "OK",
    "date": "20260730",
    "tables": [
        {"title": "115年07月30日 大盤統計資訊",
         "fields": ["成交統計", "成交金額(元)", "成交股數(股)", "成交筆數"],
         "data": [["1.一般股票", "1,026,389,321,287", "5,995,805,009", "3,888,970"]]},
        {"title": "漲跌證券數合計",
         "fields": ["類型", "整體市場", "股票"],
         "data": [
             ["上漲(漲停)", "3,536(32)", "224(2)"],
             ["下跌(跌停)", "6,546(668)", "775(25)"],
             ["持平", "739", "58"],
             ["未成交", "17,573", "1"],
             ["無比價", "2,982", "23"],
         ]},
    ],
}

TAIFEX_CSV = (
    "日期,商品名稱,身份別,多方交易口數,多方交易契約金額(千元),空方交易口數,"
    "空方交易契約金額(千元),多空交易口數淨額,多空交易契約金額淨額(千元),"
    "多方未平倉口數,多方未平倉契約金額(千元),空方未平倉口數,"
    "空方未平倉契約金額(千元),多空未平倉口數淨額,多空未平倉契約金額淨額(千元)\n"
    "2026/07/30,臺股期貨,自營商,8948,72462872,9565,77393618,-617,-4930746,"
    "6991,56441635,4995,40306880,1996,16134755\n"
    "2026/07/30,臺股期貨,投信,1291,10408120,176,1421729,1115,8986390,"
    "79257,638589500,3400,27394480,75857,611195020\n"
    "2026/07/30,臺股期貨,外資及陸資,109127,883393887,107346,869072904,1781,14320983,"
    "13822,111431104,94839,764338993,-81017,-652907889\n"
    "2026/07/30,電子期貨,外資及陸資,183,1874819,156,1596659,27,278160,"
    "23,232889,277,2804791,-254,-2571902\n"
)


class BreadthParserTests(unittest.TestCase):
    def test_reads_the_stock_only_column(self):
        result = sources.parse_breadth(MI_INDEX_MS)
        self.assertEqual(result, {"adv_count": 224, "dec_count": 775})

    def test_does_not_read_the_whole_market_column(self):
        # 3,536 / 6,546 would measure the warrant market, not the equity market.
        result = sources.parse_breadth(MI_INDEX_MS)
        self.assertNotEqual(result["adv_count"], 3536)

    def test_limit_hit_counts_in_parentheses_are_stripped(self):
        self.assertEqual(sources._count("3,536(32)"), 3536)
        self.assertEqual(sources._count("87(2)"), 87)

    def test_missing_table_returns_none_rather_than_zeros(self):
        # Zeros would score as a ratio of 0.0 and silently max out the breadth
        # penalty; None makes the subitem report data_missing instead.
        self.assertIsNone(sources.parse_breadth({"tables": []}))
        self.assertIsNone(sources.parse_breadth({}))

    def test_table_present_but_rows_missing_returns_none(self):
        payload = {"tables": [{"title": "漲跌證券數合計",
                               "data": [["持平", "739", "58"]]}]}
        self.assertIsNone(sources.parse_breadth(payload))


class TaifexParserTests(unittest.TestCase):
    def test_reads_foreign_net_open_interest_for_the_index_future(self):
        self.assertEqual(sources.parse_taifex_oi(TAIFEX_CSV), -81017)

    def test_ignores_other_investor_types(self):
        # 投信's +75,857 sits above the foreign row in the file; taking the
        # first match blindly would invert the signal's sign.
        self.assertNotEqual(sources.parse_taifex_oi(TAIFEX_CSV), 75857)

    def test_ignores_other_products(self):
        # 電子期貨's −254 must not be mistaken for the index future's position.
        self.assertNotEqual(sources.parse_taifex_oi(TAIFEX_CSV), -254)

    def test_header_only_body_from_a_non_trading_day_returns_none(self):
        header = TAIFEX_CSV.split("\n")[0] + "\n"
        self.assertIsNone(sources.parse_taifex_oi(header))

    def test_empty_body_returns_none(self):
        self.assertIsNone(sources.parse_taifex_oi(""))


if __name__ == "__main__":
    unittest.main()
