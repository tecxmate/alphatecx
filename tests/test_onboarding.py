"""Connector onboarding: server instructions (persona) + the start_here tool.

Both are read by the model, not a human, so the assertions check the load-bearing
content is present (the consultant framing, the plain-language menu, the glossary)
rather than exact wording.
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
class ServerInstructionsTests(unittest.TestCase):
    def test_instructions_are_set_on_the_server(self):
        self.assertTrue(index.mcp.instructions)

    def test_instructions_carry_the_consultant_framing(self):
        text = index.mcp.instructions.lower()
        # persona, the onboarding pointer, and the compliance boundary
        self.assertIn("not investment advice", text)
        self.assertIn("start_here", text)
        self.assertIn("plain", text)

    def test_instructions_establish_the_risk_profile(self):
        text = index.mcp.instructions.lower()
        self.assertIn("my_profile", text)
        self.assertIn("conservative", text)
        self.assertIn("aggressive", text)


@unittest.skipIf(index is None, "server deps not installed")
class StartHereToolTests(unittest.TestCase):
    def test_returns_a_usable_menu(self):
        out = index.start_here()
        self.assertTrue(out["what_you_can_ask"])
        # every menu row names a tool to use and the question it answers
        for row in out["what_you_can_ask"]:
            self.assertIn("ask", row)
            self.assertIn("use", row)

    def test_glossary_defines_beginner_terms(self):
        gloss = index.start_here()["glossary"]
        self.assertIn("P/E ratio", gloss)
        self.assertIn("Foreign flow", gloss)

    def test_carries_the_disclaimer_stamp(self):
        # goes through _stamp, so the compliance line rides along like any tool
        self.assertIn("_disclaimer", index.start_here())


@unittest.skipIf(index is None, "server deps not installed")
class RiskProfileToolTests(unittest.TestCase):
    def setUp(self):
        # These set a customer, and the tools go through _stamp, which meters via
        # usage.record — patch it so metering never hits a real DB.
        p = patch.object(index.usage_mod, "record")
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        index.current_customer.set(None)

    def test_my_profile_returns_saved_tier_with_adaptation(self):
        index.current_customer.set("cust_1")
        with patch.object(index.customers_mod, "get_risk",
                          return_value={"risk_profile": "conservative", "risk_note": None}):
            out = index.my_profile()
        self.assertEqual(out["risk_profile"], "conservative")
        self.assertIn("preservation", out["how_to_adapt"].lower())

    def test_my_profile_unset_tells_model_to_ask(self):
        index.current_customer.set("cust_1")
        with patch.object(index.customers_mod, "get_risk", return_value={}):
            out = index.my_profile()
        self.assertIsNone(out["risk_profile"])
        self.assertIn("ask", out["how_to_adapt"].lower())

    def test_owner_session_has_no_stored_profile(self):
        index.current_customer.set("owner")
        self.assertIsNone(index.my_profile()["risk_profile"])

    def test_set_valid_profile_persists(self):
        index.current_customer.set("cust_1")
        with patch.object(index.customers_mod, "set_risk_profile", return_value=True) as ss:
            out = index.set_my_risk_profile("Aggressive")
        ss.assert_called_once_with("cust_1", "aggressive", None)
        self.assertTrue(out["saved"])

    def test_set_invalid_profile_is_rejected(self):
        index.current_customer.set("cust_1")
        out = index.set_my_risk_profile("yolo")
        self.assertFalse(out["saved"])

    def test_set_on_owner_session_does_not_persist(self):
        index.current_customer.set("owner")
        self.assertFalse(index.set_my_risk_profile("conservative")["saved"])


if __name__ == "__main__":
    unittest.main()
