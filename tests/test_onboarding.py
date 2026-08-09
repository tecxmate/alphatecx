"""Connector onboarding: server instructions (persona) + the start_here tool.

Both are read by the model, not a human, so the assertions check the load-bearing
content is present (the consultant framing, the plain-language menu, the glossary)
rather than exact wording.
"""
import os
import unittest
from importlib.util import find_spec

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


if __name__ == "__main__":
    unittest.main()
