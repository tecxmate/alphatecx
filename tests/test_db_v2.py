import unittest

from mcp_server.api.query_safety import safe_flow_col


class QuerySafetyTests(unittest.TestCase):
    def test_safe_col_allows_known_flow_columns(self):
        self.assertEqual(safe_flow_col("foreign_5d", "foreign_1d"), "foreign_5d")
        self.assertEqual(
            safe_flow_col("consecutive_foreign_buy_days", "foreign_1d"),
            "consecutive_foreign_buy_days",
        )

    def test_safe_col_falls_back_for_unknown_identifiers(self):
        self.assertEqual(
            safe_flow_col("foreign_5d DESC; DROP TABLE x", "foreign_1d"),
            "foreign_1d",
        )
        self.assertEqual(safe_flow_col("", "foreign_1d"), "foreign_1d")
