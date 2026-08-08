"""Multi-tenant customer identity (mcp_server/api/customers.py), productization Layer 0.

Pure secret helpers plus the authenticate() logic, exercised with no DB by
patching the read layer — same approach as test_db_v2_queries. Provisioning
(the write path) is a thin INSERT run by the owner CLI and is not covered here;
the value in it is the secret generation/hashing, which is tested directly.
"""
import os
import unittest
from importlib.util import find_spec
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
