"""Merchant-of-Record webhook logic (mcp_server/api/billing.py).

Pure and DB-free: signature verification and the LS-event → status mapping.
The HTTP glue and customer resolution are covered in test_stamp_and_subject
(ApplyBillingTests).
"""
import hashlib
import hmac
import os
import unittest
from importlib.util import find_spec

os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")

if find_spec("psycopg_pool"):
    from mcp_server.api import billing
else:
    billing = None


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@unittest.skipIf(billing is None, "psycopg_pool is not installed")
class VerifySignatureTests(unittest.TestCase):
    def test_valid_signature_passes(self):
        body = b'{"meta":{}}'
        self.assertTrue(billing.verify_signature(body, _sign(body, "s3cret"), "s3cret"))

    def test_tampered_body_is_rejected(self):
        sig = _sign(b'{"amount":1}', "s3cret")
        self.assertFalse(billing.verify_signature(b'{"amount":9999}', sig, "s3cret"))

    def test_wrong_secret_is_rejected(self):
        body = b'{"meta":{}}'
        self.assertFalse(billing.verify_signature(body, _sign(body, "s3cret"), "other"))

    def test_empty_secret_or_signature_fails_closed(self):
        body = b'{"meta":{}}'
        self.assertFalse(billing.verify_signature(body, _sign(body, "s"), ""))
        self.assertFalse(billing.verify_signature(body, "", "s"))


def _payload(ls_status=None, customer_id=None, email=None):
    attrs = {}
    if ls_status is not None:
        attrs["status"] = ls_status
    if email:
        attrs["user_email"] = email
    payload = {"data": {"attributes": attrs}}
    if customer_id:
        payload["meta"] = {"custom_data": {"customer_id": customer_id}}
    return payload


@unittest.skipIf(billing is None, "psycopg_pool is not installed")
class EventToStatusTests(unittest.TestCase):
    def test_active_maps_active_and_reads_custom_data(self):
        cid, email, status = billing.event_to_status(_payload("active", customer_id="cust_1"))
        self.assertEqual((cid, status), ("cust_1", "active"))

    def test_on_trial_is_active(self):
        self.assertEqual(billing.event_to_status(_payload("on_trial"))[2], "active")

    def test_cancelled_and_past_due_suspend(self):
        self.assertEqual(billing.event_to_status(_payload("cancelled"))[2], "suspended")
        self.assertEqual(billing.event_to_status(_payload("past_due"))[2], "suspended")

    def test_email_fallback_when_no_custom_data(self):
        cid, email, status = billing.event_to_status(_payload("active", email="a@b.co"))
        self.assertIsNone(cid)
        self.assertEqual(email, "a@b.co")

    def test_non_subscription_event_returns_none(self):
        # e.g. an order_created payload with no subscription status
        self.assertIsNone(billing.event_to_status(_payload()))
        self.assertIsNone(billing.event_to_status({}))


if __name__ == "__main__":
    unittest.main()
