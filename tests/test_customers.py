"""Multi-tenant customer identity (mcp_server/api/customers.py), productization Layer 0.

Pure secret helpers plus the authenticate() logic, exercised with no DB by
patching the read layer — same approach as test_db_v2_queries. Provisioning
(the write path) is a thin INSERT run by the owner CLI and is not covered here;
the value in it is the secret generation/hashing, which is tested directly.
"""
import os
import unittest
from importlib.util import find_spec
from unittest.mock import MagicMock, patch

os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")

if find_spec("psycopg_pool"):
    from mcp_server.api import customers
else:
    customers = None


@unittest.skipIf(customers is None, "psycopg_pool is not installed")
class SecretHelpersTests(unittest.TestCase):
    def test_new_secret_is_prefixed_and_unique(self):
        a, b = customers.new_secret(), customers.new_secret()
        self.assertTrue(a.startswith("atx_"))
        self.assertNotEqual(a, b)

    def test_new_id_is_prefixed_and_unique(self):
        self.assertTrue(customers.new_id().startswith("cust_"))
        self.assertNotEqual(customers.new_id(), customers.new_id())

    def test_hash_is_deterministic_and_matches(self):
        s = customers.new_secret()
        self.assertEqual(customers.hash_secret(s), customers.hash_secret(s))
        self.assertTrue(customers.secret_matches(s, customers.hash_secret(s)))

    def test_wrong_secret_and_empty_hash_do_not_match(self):
        s = customers.new_secret()
        self.assertFalse(customers.secret_matches("atx_wrong", customers.hash_secret(s)))
        self.assertFalse(customers.secret_matches(s, ""))


def _row(**over):
    base = {"id": "cust_x", "email": "a@b.co", "plan": "private",
            "status": "active", "monthly_quota": None}
    base.update(over)
    return base


@unittest.skipIf(customers is None, "psycopg_pool is not installed")
class AuthenticateTests(unittest.TestCase):
    def test_active_customer_authenticates(self):
        with patch.object(customers.db, "_fetch", return_value=[_row()]):
            self.assertEqual(customers.authenticate("atx_secret")["id"], "cust_x")

    def test_lookup_uses_the_hash_never_the_raw_secret(self):
        captured = {}

        def fake(sql, params=()):
            captured["params"] = params
            return [_row()]

        with patch.object(customers.db, "_fetch", side_effect=fake):
            customers.authenticate("atx_secret")
        # The plaintext secret must never reach the query.
        self.assertEqual(captured["params"], (customers.hash_secret("atx_secret"),))

    def test_suspended_customer_is_refused(self):
        with patch.object(customers.db, "_fetch", return_value=[_row(status="suspended")]):
            self.assertIsNone(customers.authenticate("atx_secret"))

    def test_unknown_secret_returns_none(self):
        with patch.object(customers.db, "_fetch", return_value=[]):
            self.assertIsNone(customers.authenticate("nope"))

    def test_empty_credential_short_circuits_without_a_query(self):
        with patch.object(customers.db, "_fetch") as fetch:
            self.assertIsNone(customers.authenticate(""))
            fetch.assert_not_called()

    def test_db_error_fails_closed(self):
        # A database blip must never mint a token; auth fails closed.
        with patch.object(customers.db, "_fetch", side_effect=RuntimeError("db down")):
            self.assertIsNone(customers.authenticate("atx_secret"))


@unittest.skipIf(customers is None, "psycopg_pool is not installed")
class GetByEmailTests(unittest.TestCase):
    def test_found_returns_row(self):
        with patch.object(customers.db, "_fetch", return_value=[_row(email="a@b.co")]):
            self.assertEqual(customers.get_by_email("a@b.co")["id"], "cust_x")

    def test_missing_returns_none(self):
        with patch.object(customers.db, "_fetch", return_value=[]):
            self.assertIsNone(customers.get_by_email("nope@b.co"))

    def test_empty_email_short_circuits(self):
        with patch.object(customers.db, "_fetch") as fetch:
            self.assertIsNone(customers.get_by_email(""))
            fetch.assert_not_called()


@unittest.skipIf(customers is None, "psycopg_pool is not installed")
class ListAllTests(unittest.TestCase):
    def test_returns_rows(self):
        with patch.object(customers.db, "_fetch", return_value=[_row(), _row(id="cust_y")]):
            self.assertEqual(len(customers.list_all()), 2)

    def test_db_error_returns_empty_list(self):
        with patch.object(customers.db, "_fetch", side_effect=RuntimeError("db down")):
            self.assertEqual(customers.list_all(), [])


@unittest.skipIf(customers is None, "psycopg_pool is not installed")
class SetStatusTests(unittest.TestCase):
    def _pool_returning(self, rowcount):
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = rowcount
        conn.execute.return_value = cur
        ctx = MagicMock()
        ctx.__enter__.return_value = conn
        pool = MagicMock()
        pool.return_value.connection.return_value = ctx
        return pool, conn

    def test_rejects_an_invalid_status(self):
        with self.assertRaises(ValueError):
            customers.set_status("cust_1", "banana")

    def test_updates_status_and_commits(self):
        pool, conn = self._pool_returning(1)
        with patch.object(customers.db, "pool", pool):
            self.assertTrue(customers.set_status("cust_1", "suspended"))
        sql, params = conn.execute.call_args.args
        self.assertIn("UPDATE customers SET status", sql)
        self.assertEqual(params, ("suspended", "cust_1"))
        conn.commit.assert_called_once()

    def test_no_matching_row_returns_false(self):
        pool, _ = self._pool_returning(0)
        with patch.object(customers.db, "pool", pool):
            self.assertFalse(customers.set_status("cust_missing", "active"))

    def test_empty_id_returns_false(self):
        self.assertFalse(customers.set_status("", "active"))

    def test_db_error_returns_false(self):
        with patch.object(customers.db, "pool", side_effect=RuntimeError("db down")):
            self.assertFalse(customers.set_status("cust_1", "active"))


if __name__ == "__main__":
    unittest.main()
