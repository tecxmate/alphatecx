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

    def test_token_matches_rejects_empty_server_token(self):
        self.assertTrue(token_matches("secret", "secret"))
        self.assertFalse(token_matches("secret", ""))
        self.assertFalse(token_matches("other", "secret"))
