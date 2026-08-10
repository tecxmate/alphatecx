"""w_remove's archive semantics (mcp_server/api/db_v2.py).

The UPDATE matching no row means two different things — already archived, or
never on the list — and answering ok:false to both broke the idempotency the
tool documents. A caller checking `ok` read a completed archive as a failed one
(observed live 2026-08-10). The cursor is substituted here because what matters
is the branch taken on each shape of result, not the SQL.
"""
import unittest
from importlib.util import find_spec
from unittest import mock

if find_spec("psycopg_pool"):
    from mcp_server.api import db_v2
else:
    db_v2 = None


def _pool_returning(*fetch_results):
    """A pool whose cursor yields `fetch_results` from successive fetchone()s."""
    cur = mock.MagicMock()
    cur.fetchone.side_effect = list(fetch_results)
    conn = mock.MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    pool = mock.MagicMock()
    pool.connection.return_value.__enter__.return_value = conn
    return mock.patch.object(db_v2, "pool", return_value=pool), cur


@unittest.skipIf(db_v2 is None, "psycopg_pool is not installed")
class WatchlistRemoveTests(unittest.TestCase):
    def test_archiving_an_active_row_succeeds(self):
        patcher, cur = _pool_returning(("聯發科",))
        with patcher:
            out = db_v2.mutate_watchlist_remove("2454")
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "archived")
        self.assertEqual(out["company"], "聯發科")
        self.assertNotIn("already_archived", out)
        # One statement only — no lookup needed when the UPDATE hit.
        self.assertEqual(cur.execute.call_count, 1)

    def test_second_removal_is_a_successful_no_op(self):
        # UPDATE hits nothing, but the row exists → already archived.
        patcher, _ = _pool_returning(None, ("聯發科",))
        with patcher:
            out = db_v2.mutate_watchlist_remove("2454")
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "archived")
        self.assertTrue(out["already_archived"])

    def test_a_ticker_never_on_the_watchlist_is_an_error(self):
        patcher, _ = _pool_returning(None, None)
        with patcher:
            out = db_v2.mutate_watchlist_remove("9999")
        self.assertFalse(out["ok"])
        self.assertIn("not on watchlist", out["error"])


if __name__ == "__main__":
    unittest.main()
