"""OAuth 2.1 + PKCE surface for cloud connectors (mcp_server/api/oauth.py).

Stateless by design: tokens are HMAC-signed and carry their own claims, so
nothing is persisted. That is what lets these tests run with no DB and no
network, same as the rest of the suite — and it is why the unresolved
question of which Postgres instance is authoritative does not block this.

The one piece of state is a process-local set of consumed authorization
codes. A signature cannot make a code single-use, and a replayable code is
an auth bug, so it is tested explicitly.
"""
import base64
import hashlib
import os
import unittest

os.environ.setdefault("OAUTH_SIGNING_KEY", "test-signing-key-not-a-real-secret")
os.environ.setdefault("OAUTH_PASSWORD", "test-password")
os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")

from mcp_server.api import oauth, security  # noqa: E402


def _pkce(verifier: str = "verifier-string-long-enough-to-be-valid-0123456789"):
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


class TokenSigningTests(unittest.TestCase):
    def test_roundtrip_returns_the_claims(self):
        tok = oauth.issue("access", ttl=60, sub="owner")
        self.assertEqual(oauth.verify(tok, "access")["sub"], "owner")

    def test_tampered_payload_is_rejected(self):
        # The signature is the only thing between the internet and the read
        # surface once bare /mcp answers 401 instead of 404.
        tok = oauth.issue("access", ttl=60, sub="owner")
        _, sig = tok.split(".", 1)
        forged = base64.urlsafe_b64encode(
            b'{"kind":"access","sub":"attacker","exp":9999999999}'
        ).decode().rstrip("=")
        self.assertIsNone(oauth.verify(f"{forged}.{sig}", "access"))

    def test_expired_token_is_rejected(self):
        self.assertIsNone(oauth.verify(oauth.issue("access", ttl=-1), "access"))

    def test_a_code_does_not_validate_as_an_access_token(self):
        # Kind confusion would let a 60s code be replayed at the resource as
        # a bearer credential.
        self.assertIsNone(oauth.verify(oauth.issue("code", ttl=60), "access"))

    def test_garbage_is_rejected_without_raising(self):
        for bad in ("", "notatoken", "a.b.c", "...."):
            self.assertIsNone(oauth.verify(bad, "access"))


class SingleUseCodeTests(unittest.TestCase):
    def setUp(self):
        oauth._CONSUMED.clear()

    def test_a_code_can_only_be_redeemed_once(self):
        code = oauth.issue("code", ttl=60, jti="abc")
        self.assertTrue(oauth.consume(code))
        self.assertFalse(oauth.consume(code))

    def test_consume_rejects_an_invalid_code(self):
        self.assertFalse(oauth.consume("garbage"))


class ClientRegistrationTests(unittest.TestCase):
    def test_client_id_is_derived_from_the_redirect_uris(self):
        uris = ["https://claude.ai/api/mcp/auth_callback"]
        self.assertEqual(oauth.client_id_for(uris), oauth.client_id_for(uris))

    def test_different_redirect_uris_get_different_client_ids(self):
        self.assertNotEqual(
            oauth.client_id_for(["https://claude.ai/cb"]),
            oauth.client_id_for(["https://evil.example/cb"]),
        )

    def test_client_id_verifies_against_its_own_redirect_uris(self):
        uris = ["https://claude.ai/cb"]
        cid = oauth.client_id_for(uris)
        self.assertTrue(oauth.client_id_matches(cid, uris))
        self.assertFalse(oauth.client_id_matches(cid, ["https://evil.example/cb"]))


class AuthorizeTests(unittest.TestCase):
    def setUp(self):
        oauth._CONSUMED.clear()
        self.uris = ["https://claude.ai/api/mcp/auth_callback"]
        self.cid = oauth.client_id_for(self.uris)

    def test_issues_a_code_bound_to_the_redirect_uri_and_challenge(self):
        _, challenge = _pkce()
        claims = oauth.verify(oauth.make_code(self.cid, self.uris[0], challenge), "code")
        self.assertEqual(claims["redirect_uri"], self.uris[0])
        self.assertEqual(claims["code_challenge"], challenge)

    def test_rejects_a_redirect_uri_not_bound_to_the_client_id(self):
        # The entire security boundary for a public client.
        self.assertFalse(oauth.client_id_matches(self.cid, ["https://evil.example/cb"]))

    def test_password_check_rejects_wrong_values(self):
        self.assertTrue(oauth.password_ok("test-password"))
        self.assertFalse(oauth.password_ok("wrong"))
        self.assertFalse(oauth.password_ok(""))


class TokenExchangeTests(unittest.TestCase):
    def setUp(self):
        oauth._CONSUMED.clear()
        self.uris = ["https://claude.ai/cb"]
        self.cid = oauth.client_id_for(self.uris)
        self.verifier, self.challenge = _pkce()
        self.code = oauth.make_code(self.cid, self.uris[0], self.challenge)

    def test_happy_path_returns_access_and_refresh_tokens(self):
        result = oauth.exchange_code(self.code, self.verifier, self.uris[0])
        self.assertIsNotNone(result)
        self.assertIsNotNone(oauth.verify(result["access_token"], "access"))
        self.assertIsNotNone(oauth.verify(result["refresh_token"], "refresh"))
        self.assertEqual(result["token_type"], "Bearer")

    def test_rejects_a_mismatched_code_verifier(self):
        self.assertIsNone(oauth.exchange_code(self.code, "wrong-verifier", self.uris[0]))

    def test_rejects_a_mismatched_redirect_uri(self):
        # Re-checked at /token, not only at /authorize.
        self.assertIsNone(
            oauth.exchange_code(self.code, self.verifier, "https://evil.example/cb")
        )

    def test_rejects_a_replayed_code(self):
        self.assertIsNotNone(oauth.exchange_code(self.code, self.verifier, self.uris[0]))
        self.assertIsNone(oauth.exchange_code(self.code, self.verifier, self.uris[0]))

    def test_refresh_returns_a_fresh_access_token(self):
        first = oauth.exchange_code(self.code, self.verifier, self.uris[0])
        self.assertIsNotNone(oauth.verify(oauth.refresh(first["refresh_token"])["access_token"],
                                          "access"))

    def test_refresh_rejects_an_access_token(self):
        first = oauth.exchange_code(self.code, self.verifier, self.uris[0])
        self.assertIsNone(oauth.refresh(first["access_token"]))


class DiscoveryDocumentTests(unittest.TestCase):
    BASE = "https://alphatecx-mcp.zeabur.app"

    def test_protected_resource_points_at_this_host(self):
        doc = oauth.protected_resource_metadata(self.BASE)
        self.assertEqual(doc["resource"], f"{self.BASE}/mcp")
        self.assertIn(self.BASE, doc["authorization_servers"])

    def test_authorization_server_advertises_pkce_s256_only(self):
        doc = oauth.authorization_server_metadata(self.BASE)
        self.assertEqual(doc["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(doc["issuer"], self.BASE)
        for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
            self.assertTrue(doc[key].startswith(self.BASE), key)


class SecurityGateTests(unittest.TestCase):
    """The regression guard that matters most: the existing URL-as-secret
    path must keep working with no bearer header, or Claude Code and the
    Desktop bridge both die."""

    TOKEN = "testtoken"

    def test_oauth_discovery_paths_are_public(self):
        # If these 404, the connector never gets far enough to register.
        for path in (
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-protected-resource",
            "/register",
            "/authorize",
            "/token",
        ):
            self.assertTrue(security.is_authorized_path(path, self.TOKEN), path)

    def test_url_secret_mcp_path_still_passes_without_a_bearer(self):
        self.assertTrue(security.is_authorized_path(f"/mcp/{self.TOKEN}/", self.TOKEN))

    def test_hidden_surfaces_still_404_without_the_url_secret(self):
        for path in ("/g/", "/d/", "/h/", "/t/", "/g/wrong"):
            self.assertFalse(security.is_authorized_path(path, self.TOKEN), path)

    def test_bare_mcp_is_not_authorized_by_path_alone(self):
        # Must fall through to the bearer check, which answers 401.
        self.assertFalse(security.is_authorized_path("/mcp", self.TOKEN))
        self.assertFalse(security.is_authorized_path("/mcp/", self.TOKEN))

    def test_bearer_validation_accepts_only_a_signed_access_token(self):
        tok = oauth.issue("access", ttl=60, sub="owner")
        self.assertTrue(security.bearer_token_valid(f"Bearer {tok}"))
        self.assertFalse(security.bearer_token_valid("Bearer garbage"))
        self.assertFalse(security.bearer_token_valid(""))
        self.assertFalse(security.bearer_token_valid(tok))  # missing scheme

    def test_bearer_validation_rejects_a_refresh_token(self):
        self.assertFalse(security.bearer_token_valid(f"Bearer {oauth.issue('refresh', ttl=60)}"))


class SigningKeyRequiredTests(unittest.TestCase):
    def test_missing_signing_key_is_fatal_rather_than_defaulted(self):
        # Same discipline index.py applies to an empty MCP_BEARER_TOKEN: a
        # defaulted signing key would make every forged token valid.
        with self.assertRaises(RuntimeError):
            oauth._require_key("")


if __name__ == "__main__":
    unittest.main()
