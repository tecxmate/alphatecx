"""sc_capabilities must describe every tool the server actually registers.

The server instructions tell the model this is "the full technical map", so a
tool missing from it is, in practice, a tool the model has been told does not
exist. It had silently drifted to 33 of 48 — every quant tool past q_backtest,
the whole onboarding/profile layer, and ticker_lookup, the usual first step in
any chain. Nothing failed loudly; the model just stopped reaching for them.

Asserted against the live FastMCP registry rather than a hand-kept list, so
adding a tool without describing it fails here.
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


def _registered() -> set:
    """Tool names FastMCP actually serves."""
    return {t.name for t in index.mcp._tool_manager.list_tools()}


def _advertised() -> set:
    return {t["name"] for t in index.sc_capabilities()["tools"]}


@unittest.skipIf(index is None, "server deps not installed")
class CapabilitiesCoverageTests(unittest.TestCase):
    def test_every_registered_tool_is_advertised(self):
        missing = _registered() - _advertised()
        self.assertEqual(missing, set(),
                         f"registered but absent from sc_capabilities: {sorted(missing)}")

    def test_nothing_advertised_that_does_not_exist(self):
        # The other direction: a renamed or removed tool still listed here sends
        # the model at a name that will fail.
        stale = _advertised() - _registered()
        self.assertEqual(stale, set(),
                         f"advertised but not registered: {sorted(stale)}")

    def test_every_entry_explains_what_it_is_for(self):
        for entry in index.sc_capabilities()["tools"]:
            self.assertTrue(entry.get("purpose", "").strip(),
                            f"{entry['name']} has no purpose")


if __name__ == "__main__":
    unittest.main()
