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


@unittest.skipIf(index is None, "server deps not installed")
class SubjectStillValidTests(unittest.TestCase):
    """Refresh must re-check status so a suspended customer can't refresh forever."""

    def test_owner_is_always_valid_without_a_db_lookup(self):
        with patch.object(index.customers_mod, "get") as get:
            self.assertTrue(index._subject_still_valid("owner"))
            get.assert_not_called()

    def test_active_customer_is_valid(self):
        with patch.object(index.customers_mod, "get",
                          return_value={"id": "cust_1", "status": "active"}):
            self.assertTrue(index._subject_still_valid("cust_1"))

    def test_suspended_customer_is_refused(self):
        with patch.object(index.customers_mod, "get",
                          return_value={"id": "cust_1", "status": "suspended"}):
            self.assertFalse(index._subject_still_valid("cust_1"))

    def test_deleted_or_unresolvable_customer_fails_closed(self):
        # get() returns None for a missing row or on a swallowed DB error.
        with patch.object(index.customers_mod, "get", return_value=None):
            self.assertFalse(index._subject_still_valid("cust_gone"))


@unittest.skipIf(index is None, "server deps not installed")
class MeteringStampTests(unittest.TestCase):
    """_stamp counts the call against the current customer, and only a customer."""

    def tearDown(self):
        index.current_customer.set(None)

    def test_customer_call_is_metered(self):
        index.current_customer.set("cust_9")
        with patch.object(index.usage_mod, "record") as record:
            index._stamp({"x": 1}, "view_x", "2026-08-09", "T+1")
            record.assert_called_once_with("cust_9")

    def test_owner_is_not_metered(self):
        index.current_customer.set("owner")
        with patch.object(index.usage_mod, "record") as record:
            index._stamp({"x": 1}, "view_x", "2026-08-09", "T+1")
            record.assert_not_called()

    def test_anonymous_context_is_not_metered(self):
        index.current_customer.set(None)
        with patch.object(index.usage_mod, "record") as record:
            index._stamp({"x": 1}, "view_x", "2026-08-09", "T+1")
            record.assert_not_called()


@unittest.skipIf(index is None, "server deps not installed")
class CustomerGateTests(unittest.TestCase):
    """Per-session gate: active + under quota passes; else 402/429."""

    def test_active_under_quota_passes(self):
        with patch.object(index.customers_mod, "get",
                          return_value={"id": "c", "status": "active", "monthly_quota": 100}), \
             patch.object(index.usage_mod, "calls_this_month", return_value=10):
            self.assertIsNone(index._customer_gate("c"))

    def test_unlimited_quota_passes_without_a_usage_read(self):
        with patch.object(index.customers_mod, "get",
                          return_value={"id": "c", "status": "active", "monthly_quota": None}), \
             patch.object(index.usage_mod, "calls_this_month") as calls:
            self.assertIsNone(index._customer_gate("c"))
            calls.assert_not_called()

    def test_inactive_customer_gets_402(self):
        with patch.object(index.customers_mod, "get",
                          return_value={"id": "c", "status": "suspended", "monthly_quota": 100}):
            self.assertEqual(index._customer_gate("c").status_code, 402)

    def test_missing_customer_gets_402(self):
        with patch.object(index.customers_mod, "get", return_value=None):
            self.assertEqual(index._customer_gate("c").status_code, 402)

    def test_over_quota_gets_429(self):
        with patch.object(index.customers_mod, "get",
                          return_value={"id": "c", "status": "active", "monthly_quota": 100}), \
             patch.object(index.usage_mod, "calls_this_month", return_value=100):
            self.assertEqual(index._customer_gate("c").status_code, 429)


@unittest.skipIf(index is None, "server deps not installed")
class ApplyBillingTests(unittest.TestCase):
    """Billing webhook glue: resolve the customer and flip status; pick the code."""

    def test_non_subscription_event_acks_200(self):
        with patch.object(index.billing_mod, "event_to_status", return_value=None):
            self.assertEqual(index._apply_billing({}), 200)

    def test_active_by_customer_id_sets_status(self):
        with patch.object(index.billing_mod, "event_to_status",
                          return_value=("cust_1", None, "active")), \
             patch.object(index.customers_mod, "set_status", return_value=True) as ss:
            self.assertEqual(index._apply_billing({}), 200)
            ss.assert_called_once_with("cust_1", "active")

    def test_email_fallback_resolves_then_sets(self):
        with patch.object(index.billing_mod, "event_to_status",
                          return_value=(None, "a@b.co", "suspended")), \
             patch.object(index.customers_mod, "get_by_email",
                          return_value={"id": "cust_9"}), \
             patch.object(index.customers_mod, "set_status", return_value=True) as ss:
            self.assertEqual(index._apply_billing({}), 200)
            ss.assert_called_once_with("cust_9", "suspended")

    def test_unknown_customer_acks_200_without_a_write(self):
        with patch.object(index.billing_mod, "event_to_status",
                          return_value=(None, "x@y.co", "active")), \
             patch.object(index.customers_mod, "get_by_email", return_value=None), \
             patch.object(index.customers_mod, "set_status") as ss:
            self.assertEqual(index._apply_billing({}), 200)
            ss.assert_not_called()

    def test_write_failure_returns_500_for_retry(self):
        with patch.object(index.billing_mod, "event_to_status",
                          return_value=("cust_1", None, "active")), \
             patch.object(index.customers_mod, "set_status", return_value=False):
            self.assertEqual(index._apply_billing({}), 500)


if __name__ == "__main__":
    unittest.main()
