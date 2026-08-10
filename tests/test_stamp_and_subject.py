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

    def test_glossary_attached_only_when_given(self):
        self.assertNotIn("_glossary", index._stamp({"x": 1}, "s", None, "T+1"))
        out = index._stamp({"x": 1}, "s", None, "T+1", glossary={"pe": "…"})
        self.assertEqual(out["_glossary"], {"pe": "…"})


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

    def test_trial_customer_is_valid(self):
        with patch.object(index.customers_mod, "get",
                          return_value={"id": "cust_1", "status": "trial"}):
            self.assertTrue(index._subject_still_valid("cust_1"))

    def test_deleted_customer_fails_closed(self):
        with patch.object(index.customers_mod, "get", return_value=None):
            self.assertFalse(index._subject_still_valid("cust_gone"))

    def test_unreachable_store_also_fails_closed_here(self):
        # Deliberately unlike the read gate's 503: a refresh mints a fresh
        # 90-day credential, so declining during a blip costs a retry while
        # issuing wrongly costs three months. Live sessions keep their access
        # token, which outlives a short outage.
        with patch.object(index.customers_mod, "get",
                          side_effect=index.customers_mod.LookupUnavailable("x")):
            self.assertFalse(index._subject_still_valid("cust_1"))


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
class UrlSecretSubjectTests(unittest.TestCase):
    """The URL-as-secret mount must name its subject, not leave it anonymous.

    It used to leave current_customer unset, so the profile tools saw no identity
    and set_my_risk_profile could only answer "can't persist" — inert for the
    operator, who reaches the server this way (observed live 2026-08-10). Driven
    through the real ASGI stack because the whole question is whether the value
    set in the middleware survives into the tool body.
    """

    @classmethod
    def setUpClass(cls):
        # One client for the class: FastMCP's session manager refuses a second
        # .run(), so entering the app's lifespan twice in one process raises.
        from starlette.testclient import TestClient
        cls.client = TestClient(index.app)
        cls.client.__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)

    def _call(self, path: str) -> tuple:
        seen = []
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "investing_principles", "arguments": {}}}
        with patch.object(index.customers_mod, "get_risk",
                          side_effect=lambda c: seen.append(c) or {}), \
             patch.object(index.usage_mod, "record") as record:
            resp = self.client.post(path, json=body, headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            })
        self.assertEqual(resp.status_code, 200)
        return seen, record

    def test_url_secret_path_identifies_the_owner(self):
        seen, _ = self._call("/mcp/testtoken/")
        self.assertEqual(seen, [index.OWNER_SUBJECT])

    def test_url_secret_owner_is_still_never_metered(self):
        _, record = self._call("/mcp/testtoken/")
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

    def test_trial_customer_passes(self):
        with patch.object(index.customers_mod, "get",
                          return_value={"id": "c", "status": "trial", "monthly_quota": None}):
            self.assertIsNone(index._customer_gate("c"))

    def test_unreachable_store_gets_503_not_402(self):
        # 402 account_inactive is a claim about the subscription. Answering it on
        # a Postgres blip told paying customers their account had lapsed.
        with patch.object(index.customers_mod, "get",
                          side_effect=index.customers_mod.LookupUnavailable("c")):
            self.assertEqual(index._customer_gate("c").status_code, 503)

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
             patch.object(index.customers_mod, "get",
                          return_value={"id": "cust_1"}), \
             patch.object(index.customers_mod, "set_status", return_value=True) as ss:
            self.assertEqual(index._apply_billing({}), 200)
            ss.assert_called_once_with("cust_1", "active")

    def test_unconfirmable_custom_data_id_falls_back_to_email(self):
        # A stale or typo'd checkout custom_data id used to skip the email
        # fallback entirely, update zero rows and return 500 — which Lemon
        # Squeezy retries forever while the real customer is never activated.
        with patch.object(index.billing_mod, "event_to_status",
                          return_value=("cust_gone", "a@b.co", "active")), \
             patch.object(index.customers_mod, "get", return_value=None), \
             patch.object(index.customers_mod, "get_by_email",
                          return_value={"id": "cust_9"}), \
             patch.object(index.customers_mod, "set_status", return_value=True) as ss:
            self.assertEqual(index._apply_billing({}), 200)
            ss.assert_called_once_with("cust_9", "active")

    def test_unconfirmable_id_with_no_email_match_acks_once(self):
        with patch.object(index.billing_mod, "event_to_status",
                          return_value=("cust_gone", None, "active")), \
             patch.object(index.customers_mod, "get", return_value=None), \
             patch.object(index.customers_mod, "set_status") as ss:
            self.assertEqual(index._apply_billing({}), 200)   # not 500 forever
            ss.assert_not_called()

    def test_unreachable_store_returns_500_so_ls_retries(self):
        # Distinct from "unknown customer": this one IS worth retrying.
        with patch.object(index.billing_mod, "event_to_status",
                          return_value=("cust_1", None, "active")), \
             patch.object(index.customers_mod, "get",
                          side_effect=index.customers_mod.LookupUnavailable("x")), \
             patch.object(index.customers_mod, "set_status") as ss:
            self.assertEqual(index._apply_billing({}), 500)
            ss.assert_not_called()

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
        # The customer resolves; it is the UPDATE that fails. Patch `get` too or
        # this asserts 500 via the unreachable-store path instead of the write.
        with patch.object(index.billing_mod, "event_to_status",
                          return_value=("cust_1", None, "active")), \
             patch.object(index.customers_mod, "get",
                          return_value={"id": "cust_1"}), \
             patch.object(index.customers_mod, "set_status", return_value=False) as ss:
            self.assertEqual(index._apply_billing({}), 500)
            ss.assert_called_once_with("cust_1", "active")


if __name__ == "__main__":
    unittest.main()
