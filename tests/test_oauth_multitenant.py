"""Multi-tenant subject flow through OAuth (mcp_server/api/oauth.py).

Single-tenant OAuth hardcoded sub="owner"; the paid connector needs each
customer's token to carry sub=<customer_id>. The subject is decided at authorize
time but the token is minted at /token, so it has to ride inside the code and
survive refresh. These guard that path — still stateless, still no DB, same as
test_oauth.
"""
import base64
import hashlib
import os
import unittest

os.environ.setdefault("OAUTH_SIGNING_KEY", "test-signing-key-not-a-real-secret")
os.environ.setdefault("OAUTH_PASSWORD", "test-password")
os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")

from mcp_server.api import oauth  # noqa: E402


def _pkce(verifier: str = "verifier-string-long-enough-to-be-valid-0123456789"):
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


class MultiTenantSubjectTests(unittest.TestCase):
    def setUp(self):
        oauth._CONSUMED.clear()

    def test_code_carries_sub_into_access_and_refresh(self):
        verifier, challenge = _pkce()
        code = oauth.make_code("cid", "https://cb", challenge, sub="cust_42")
        resp = oauth.exchange_code(code, verifier, "https://cb")
        self.assertEqual(oauth.verify(resp["access_token"], "access")["sub"], "cust_42")
        self.assertEqual(oauth.verify(resp["refresh_token"], "refresh")["sub"], "cust_42")

    def test_refresh_preserves_the_subject(self):
        # A customer's refresh must not silently downgrade them to owner.
        rt = oauth.issue("refresh", ttl=60, sub="cust_9")
        resp = oauth.refresh(rt)
        self.assertEqual(oauth.verify(resp["access_token"], "access")["sub"], "cust_9")
        self.assertEqual(oauth.verify(resp["refresh_token"], "refresh")["sub"], "cust_9")

    def test_default_subject_is_owner_back_compat(self):
        verifier, challenge = _pkce()
        code = oauth.make_code("cid", "https://cb", challenge)  # no sub
        resp = oauth.exchange_code(code, verifier, "https://cb")
        self.assertEqual(oauth.verify(resp["access_token"], "access")["sub"], "owner")

    def test_legacy_refresh_without_sub_defaults_owner(self):
        rt = oauth.issue("refresh", ttl=60)  # pre-multitenant token, no sub claim
        resp = oauth.refresh(rt)
        self.assertEqual(oauth.verify(resp["access_token"], "access")["sub"], "owner")


if __name__ == "__main__":
    unittest.main()
