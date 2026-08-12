"""/health: shallow liveness vs `?deep=1` DB probe (index.py).

The permission-denied outage (2026-08-10) was invisible from outside: /health
said ok while every data tool failed. The deep form exists so an uptime monitor
can see that state. It is also PUBLIC, so it must be rate-bounded — the cache
means hammering it costs one query per window, not one per request.
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
class HealthTests(unittest.TestCase):
    def setUp(self):
        # Expire the cache so each test drives its own probe.
        index._deep_health_cache.update(at=-1e9, db=False)

    def test_shallow_health_never_touches_the_db(self):
        with patch.object(index.db_v2, "_fetch") as fetch:
            out = index.health()
        self.assertTrue(out["ok"])
        fetch.assert_not_called()

    def test_deep_health_reports_a_live_db(self):
        with patch.object(index.db_v2, "_fetch", return_value=[{"?column?": 1}]):
            out = index.health(deep=True)
        self.assertEqual((out["ok"], out["db"]), (True, True))

    def test_deep_health_answers_503_when_the_db_is_down(self):
        with patch.object(index.db_v2, "_fetch", side_effect=RuntimeError("down")):
            resp = index.health(deep=True)
        self.assertEqual(resp.status_code, 503)

    def test_probe_is_cached_within_the_window(self):
        # Public endpoint: N requests inside the TTL must cost one query.
        with patch.object(index.db_v2, "_fetch", return_value=[{"?column?": 1}]) as fetch:
            index.health(deep=True)
            index.health(deep=True)
            index.health(deep=True)
        self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
