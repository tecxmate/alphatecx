-- alphatecx v2 — Watchlist write-grant re-apply (fix)
--
-- 003_rls.sql grants mcp_viewer INSERT+UPDATE on watchlist (line 119) so the
-- w_add / w_remove MCP tools can mutate it — but 003 ENDS with a blanket
-- `REVOKE INSERT, UPDATE, DELETE ON ALL TABLES` (line 154) that strips that very
-- grant. Same trap that hit rg_journal (018) and usage_monthly (020); those are
-- re-appended after 003 by apply_schema.py, but watchlist had no such re-append,
-- so after any `--rls` run w_add / w_remove failed with
-- `permission denied for table watchlist`.
--
-- Re-running 003 can't fix it (it would hit the REVOKE again at its own end), so
-- this separate file restores the grant and is re-appended after 003. The RLS
-- policies from 003 survive the REVOKE (policies are not privileges), so only
-- the GRANT needs re-issuing.
--
-- Role- and table-guarded + idempotent: a no-op before 003 creates mcp_viewer or
-- 007 creates watchlist, and safe to run twice.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer')
     AND EXISTS (SELECT FROM information_schema.tables
                 WHERE table_schema = 'public' AND table_name = 'watchlist') THEN
    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON watchlist TO mcp_viewer';
  END IF;
END$$;
