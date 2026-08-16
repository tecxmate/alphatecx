import unittest

from mcp_server.api.security import is_authorized_path, token_matches


class SecurityTests(unittest.TestCase):
    def test_public_paths_do_not_need_token(self):
        self.assertTrue(is_authorized_path("/", ""))
        self.assertTrue(is_authorized_path("/health", ""))

    def test_secret_prefixes_are_segment_aware(self):
        self.assertTrue(is_authorized_path("/mcp/secret", "secret"))
        self.assertTrue(is_authorized_path("/mcp/secret/", "secret"))
        self.assertTrue(is_authorized_path("/g/secret/data.json", "secret"))
        self.assertTrue(is_authorized_path("/d/secret/t/2330", "secret"))
        self.assertTrue(is_authorized_path("/h/secret/", "secret"))
        self.assertTrue(is_authorized_path("/t/secret/", "secret"))

        self.assertFalse(is_authorized_path("/mcp/secretevil", "secret"))
        self.assertFalse(is_authorized_path("/g/secretevil/data.json", "secret"))
        self.assertFalse(is_authorized_path("/d/secretevil", "secret"))
        self.assertFalse(is_authorized_path("/h/secretevil", "secret"))
        self.assertFalse(is_authorized_path("/t/secretevil", "secret"))

    def test_secret_routes_reject_missing_or_wrong_token(self):
        self.assertFalse(is_authorized_path("/mcp/secret", ""))
        self.assertFalse(is_authorized_path("/mcp/secret", "other"))

    def test_bot_paths_bypass_the_url_secret_gate(self):
        # /bot/* authenticates itself: the webhook checks Telegram's
        # X-Telegram-Bot-Api-Secret-Token header, then gates on the owner's
        # chat_id. It carries no URL secret and must not be judged by one.
        # On Vercel these were a separate function that never reached this
        # middleware; running one uvicorn process makes the exemption explicit.
        self.assertTrue(is_authorized_path("/bot/webhook", "secret"))
        self.assertTrue(is_authorized_path("/bot/health", ""))

    def test_bot_prefix_is_segment_aware(self):
        self.assertFalse(is_authorized_path("/botevil", "secret"))
        self.assertFalse(is_authorized_path("/botevil/webhook", "secret"))

    def test_billing_paths_bypass_the_url_secret_gate(self):
        # /billing/* authenticates itself via the MoR's HMAC signature over the
        # raw body, so it does not carry the URL secret.
        self.assertTrue(is_authorized_path("/billing/lemonsqueezy", "secret"))
        self.assertTrue(is_authorized_path("/billing/lemonsqueezy", ""))

    def test_billing_prefix_is_segment_aware(self):
        self.assertFalse(is_authorized_path("/billingevil", "secret"))
        self.assertFalse(is_authorized_path("/billingevil/hook", "secret"))

    def test_token_matches_rejects_empty_server_token(self):
        self.assertTrue(token_matches("secret", "secret"))
        self.assertFalse(token_matches("secret", ""))
        self.assertFalse(token_matches("other", "secret"))


class TestConsoleTokenSplit:
    """`/mcp` and the console must be able to use different secrets.

    They shared one string until 2026-08-16, which made the dashboard URL an
    API credential: anyone shown the console could also call all 49 tools,
    several of which write. The split is opt-in via CONSOLE_TOKEN so an
    environment that has not set it cannot break.
    """

    API = "apitoken"
    CONSOLE = "consoletoken"

    def test_console_token_does_not_open_the_api(self):
        """The point of the whole change."""
        assert not is_authorized_path(
            f"/mcp/{self.CONSOLE}/", self.API, self.CONSOLE
        )

    def test_api_token_does_not_open_the_console(self):
        assert not is_authorized_path(
            f"/d/{self.API}/", self.API, self.CONSOLE
        )

    def test_each_token_opens_its_own_surface(self):
        assert is_authorized_path(f"/mcp/{self.API}/", self.API, self.CONSOLE)
        for prefix in ("/d", "/g", "/h", "/t"):
            assert is_authorized_path(
                f"{prefix}/{self.CONSOLE}/", self.API, self.CONSOLE
            ), prefix

    def test_omitting_console_token_preserves_old_behaviour(self):
        """Unset CONSOLE_TOKEN must behave exactly as the single-secret gate.

        This is what makes the change safe to deploy before anyone configures
        anything: production keeps working untouched until the operator opts in.
        """
        for prefix in ("/mcp", "/d", "/g", "/h", "/t"):
            assert is_authorized_path(f"{prefix}/{self.API}/", self.API)
            assert is_authorized_path(f"{prefix}/{self.API}/", self.API, "")

    def test_split_does_not_weaken_segment_matching(self):
        """The prefix guard must still not match a token that is merely a prefix."""
        assert not is_authorized_path(
            f"/d/{self.CONSOLE}evil", self.API, self.CONSOLE
        )

    def test_public_and_signature_authenticated_paths_unaffected(self):
        for path in ("/", "/health", "/bot/webhook", "/billing/hook"):
            assert is_authorized_path(path, self.API, self.CONSOLE), path
