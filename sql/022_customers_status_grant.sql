-- alphatecx v2 — Customers status write grant (billing webhook, Layer 1)
--
-- The Merchant-of-Record webhook (/billing/lemonsqueezy) flips customers.status
-- when a subscription starts/lapses. It runs inside the read-only MCP server, so
-- mcp_viewer needs a WRITE on customers — but scoped as tightly as possible:
-- a COLUMN-level `UPDATE (status, updated_at)` only, never INSERT/DELETE and
-- never other columns (secret_hash, email, quota stay owner-only via
-- provision()). Same scoped-write pattern as watchlist/usage.
--
-- 019 already created customers, enabled RLS, and added the SELECT policy; this
-- file adds only the UPDATE grant + UPDATE policy. Like 018/020/021 the grant is
-- stripped by 003's blanket REVOKE, so apply_schema.py re-appends this after 003.
-- Role-guarded + idempotent.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer')
     AND EXISTS (SELECT FROM information_schema.tables
                 WHERE table_schema = 'public' AND table_name = 'customers') THEN
    EXECUTE 'GRANT UPDATE (status, updated_at) ON customers TO mcp_viewer';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_update_customers" ON customers';
    EXECUTE $POLICY$
      CREATE POLICY "mcp_viewer_update_customers"
        ON customers FOR UPDATE TO mcp_viewer USING (true) WITH CHECK (true)
    $POLICY$;
  END IF;
END$$;
