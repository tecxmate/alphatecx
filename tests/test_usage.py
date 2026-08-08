"""Per-customer usage metering (mcp_server/api/usage.py), productization Layer 1.

The write (record) and read (calls_this_month) are exercised with no DB by
patching the pool/read layer. The design contract under test: record() swallows
errors (metering must not break a tool response) and calls_this_month() fails
open to 0 (a read blip must not lock a customer out at the quota gate).
"""
import os
import unittest
from importlib.util import find_spec
from unittest.mock import MagicMock, patch

os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")

if find_spec("psycopg_pool"):
    from mcp_server.api import usage
else:
    usage = None


@unittest.skipIf(usage is None, "psycopg_pool is not installed")
class RecordTests(unittest.TestCase):
    def test_record_upserts_with_increment(self):
        conn = MagicMock()
        # `with db.pool().connection() as conn:` → context manager yields conn.
        ctx = MagicMock()
        ctx.__enter__.return_value = conn
        with patch.object(usage.db, "pool") as pool:
            pool.return_value.connection.return_value = ctx
            usage.record("cust_1", yyyymm="2026-08")
        sql, params = conn.execute.call_args.args
        self.assertIn("INSERT INTO usage_monthly", sql)
        self.assertIn("ON CONFLICT", sql)
        self.assertIn("calls = usage_monthly.calls + 1", sql)
        self.assertEqual(params, ("cust_1", "2026-08"))
        conn.commit.assert_called_once()

    def test_record_empty_customer_is_a_noop(self):
        with patch.object(usage.db, "pool") as pool:
            usage.record("")
            pool.assert_not_called()

    def test_record_swallows_db_errors(self):
        with patch.object(usage.db, "pool", side_effect=RuntimeError("db down")):
            usage.record("cust_1")  # must not raise


@unittest.skipIf(usage is None, "psycopg_pool is not installed")
class CallsThisMonthTests(unittest.TestCase):
    def test_returns_the_stored_count(self):
        with patch.object(usage.db, "_fetch", return_value=[{"calls": 42}]):
            self.assertEqual(usage.calls_this_month("cust_1", yyyymm="2026-08"), 42)

    def test_missing_row_is_zero(self):
        with patch.object(usage.db, "_fetch", return_value=[]):
            self.assertEqual(usage.calls_this_month("cust_1"), 0)

    def test_read_error_fails_open_to_zero(self):
        with patch.object(usage.db, "_fetch", side_effect=RuntimeError("db down")):
            self.assertEqual(usage.calls_this_month("cust_1"), 0)

    def test_empty_customer_is_zero_without_a_query(self):
        with patch.object(usage.db, "_fetch") as fetch:
            self.assertEqual(usage.calls_this_month(""), 0)
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
