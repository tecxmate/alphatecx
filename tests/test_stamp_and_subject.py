"""Disclaimer on every response + the authorize subject resolver (index.py).

Layer 2: `_stamp()` funnels every tool response, so the `_disclaimer` field is
guaranteed present — a tool cannot ship data without it. Also covers
`_resolve_subject`, the HTTP-layer glue that turns a login credential into the
token subject (owner password vs per-customer secret), kept out of oauth.py so
that module stays DB-free.
"""
import os
import unittest
from importlib.util import find_spec
from unittest.mock import patch

os.environ.setdefault("OAUTH_SIGNING_KEY", "test-signing-key-not-a-real-secret")
os.environ.setdefault("OAUTH_PASSWORD", "test-password")
os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")

if find_spec("psycopg_pool") and find_spec("mcp"):
    from mcp_server.api import index
else:
    index = None


@unittest.skipIf(index is None, "server deps not installed")
class DisclaimerStampTests(unittest.TestCase):
    def test_every_stamp_carries_a_nonempty_disclaimer(self):
        out = index._stamp({"x": 1}, "view_x", "2026-08-08", "T+1")
        self.assertIn("_disclaimer", out)
        self.assertTrue(out["_disclaimer"])

    def test_stamp_still_preserves_payload_and_provenance(self):
        out = index._stamp({"x": 1}, "view_x", "2026-08-08", "T+1")
        self.assertEqual(out["x"], 1)
        self.assertEqual(out["_source"], "view_x")
        self.assertEqual(out["_as_of"], "2026-08-08")


@unittest.skipIf(index is None, "server deps not installed")
class ResolveSubjectTests(unittest.TestCase):
    def test_owner_password_resolves_owner(self):
        with patch.object(index.oauth_mod, "password_ok", return_value=True):
            self.assertEqual(index._resolve_subject("whatever"), "owner")

    def test_owner_is_checked_before_any_customer_db_lookup(self):
        with patch.object(index.oauth_mod, "password_ok", return_value=True), \
             patch.object(index.customers_mod, "authenticate") as auth:
            self.assertEqual(index._resolve_subject("pw"), "owner")
            auth.assert_not_called()

    def test_customer_secret_resolves_to_customer_id(self):
        with patch.object(index.oauth_mod, "password_ok", return_value=False), \
             patch.object(index.customers_mod, "authenticate",
                          return_value={"id": "cust_7"}):
            self.assertEqual(index._resolve_subject("atx_secret"), "cust_7")

    def test_bad_credential_resolves_to_none(self):
        with patch.object(index.oauth_mod, "password_ok", return_value=False), \
             patch.object(index.customers_mod, "authenticate", return_value=None):
            self.assertIsNone(index._resolve_subject("garbage"))


if __name__ == "__main__":
    unittest.main()
