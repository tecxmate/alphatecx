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
        self.assertFalse(is_authorized_path("/bot/webhook", "secret"))

    def test_token_matches_rejects_empty_server_token(self):
        self.assertTrue(token_matches("secret", "secret"))
        self.assertFalse(token_matches("secret", ""))
        self.assertFalse(token_matches("other", "secret"))
