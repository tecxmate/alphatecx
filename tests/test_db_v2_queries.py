import unittest
from importlib.util import find_spec
from unittest.mock import patch

if find_spec("psycopg_pool"):
    from mcp_server.api import db_v2
else:
    db_v2 = None


@unittest.skipIf(db_v2 is None, "psycopg_pool is not installed")
class MarketFlowScreenerTests(unittest.TestCase):
    def test_market_flow_screener_filters_unclassified_full_market(self):
        captured = {}

        def fake_fetch(sql, params=()):
            captured["sql"] = sql
            captured["params"] = params
            return []

        with patch.object(db_v2, "_fetch", side_effect=fake_fetch):
            rows = db_v2.query_market_flow_screener(
                market="twse",
                classification="unclassified",
                min_streak=3,
                foreign_5d_above=1000,
                sort_by="foreign_20d",
                sort_direction="asc",
                limit=500,
            )

        self.assertEqual(rows, [])
        self.assertIn("FROM view_ticker_momentum tm", captured["sql"])
        self.assertIn("LEFT JOIN view_latest_signals ls", captured["sql"])
        self.assertIn("tm.ai_pillar = 'unclassified'", captured["sql"])
        self.assertIn("ORDER BY tm.foreign_20d ASC", captured["sql"])
        self.assertEqual(captured["params"], ("TWSE", 3, 1000, 200))

    def test_market_flow_screener_rejects_unknown_market(self):
        rows = db_v2.query_market_flow_screener(market="NYSE")
        self.assertEqual(rows, [{"error": "market must be 'TWSE' or 'TPEX'"}])

    def test_market_flow_screener_falls_back_from_unsafe_sort(self):
        captured = {}

        def fake_fetch(sql, params=()):
            captured["sql"] = sql
            return []

        with patch.object(db_v2, "_fetch", side_effect=fake_fetch):
            db_v2.query_market_flow_screener(sort_by="foreign_5d DESC; DROP TABLE x")

        self.assertIn("ORDER BY tm.foreign_5d DESC", captured["sql"])


@unittest.skipIf(db_v2 is None, "psycopg_pool is not installed")
class QuantScreenerTests(unittest.TestCase):
    def test_quant_screener_can_query_all_signal_covered_tickers(self):
        captured = {}

        def fake_fetch(sql, params=()):
            captured["sql"] = sql
            captured["params"] = params
            return []

        with patch.object(db_v2, "_fetch", side_effect=fake_fetch):
            rows = db_v2.query_screener(
                rs_below=-5,
                foreign_z_below=-1,
                pct_below_52w_high_below=-20,
                universe="all_with_signals",
            )

        self.assertEqual(rows, [])
        self.assertIn("JOIN dim_ticker dt", captured["sql"])
        self.assertNotIn("dim_supply_chain", captured["sql"])
        self.assertNotIn("dt.ai_pillar IS NOT NULL", captured["sql"])
        self.assertEqual(captured["params"], (-5, -1, -20))

    def test_quant_screener_defaults_to_classified(self):
        captured = {}

        def fake_fetch(sql, params=()):
            captured["sql"] = sql
            return []

        with patch.object(db_v2, "_fetch", side_effect=fake_fetch):
            db_v2.query_screener()

        self.assertIn("dt.ai_pillar IS NOT NULL", captured["sql"])


if __name__ == "__main__":
    unittest.main()
