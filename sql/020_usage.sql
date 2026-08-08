-- alphatecx v2 — Usage metering (commercial productization, Layer 1)
--
-- Per-customer monthly tool-call counts, one row per (customer, month). The MCP
-- server increments this from _stamp() on every metered tool response, and the
-- auth_gate middleware reads it to enforce customers.monthly_quota. See
-- docs/wiki/topics/commercial-productization.md.
--
-- Unlike almost everything else, the read-only server MUST write here — the
-- count is a side effect of a read. So mcp_viewer gets a NARROW SELECT+INSERT+
-- UPDATE grant on this ONE table, exactly the pattern and blast radius as
-- `watchlist` (sql/003_rls.sql).
--
-- ORDERING: 003 ends with `REVOKE INSERT, UPDATE, DELETE ON ALL TABLES` (line
-- 154), which strips any write grant made before it — the same trap that
-- required 018 to be re-applied after 003. apply_schema.py therefore re-appends
-- THIS file after 003 so the grant lands last. (The watchlist grant at 003:119
-- is itself stripped by that REVOKE with no re-append — a pre-existing bug, not
-- fixed here; this file just avoids repeating it.) Safe to run twice: CREATE
-- TABLE IF NOT EXISTS + role-guarded, idempotent DROP-then-CREATE policies.

CREATE TABLE IF NOT EXISTS usage_monthly (
    customer_id TEXT NOT NULL,
    yyyymm      TEXT NOT NULL,            -- Asia/Taipei calendar month, e.g. '2026-08'
    calls       BIGINT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (customer_id, yyyymm)
);

DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer') THEN
    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON usage_monthly TO mcp_viewer';
    EXECUTE 'ALTER TABLE usage_monthly ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_read_usage" ON usage_monthly';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_insert_usage" ON usage_monthly';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_update_usage" ON usage_monthly';
    EXECUTE $POLICY$
      CREATE POLICY "mcp_viewer_read_usage"
        ON usage_monthly FOR SELECT TO mcp_viewer USING (true)
    $POLICY$;
    EXECUTE $POLICY$
      CREATE POLICY "mcp_viewer_insert_usage"
        ON usage_monthly FOR INSERT TO mcp_viewer WITH CHECK (true)
    $POLICY$;
    EXECUTE $POLICY$
      CREATE POLICY "mcp_viewer_update_usage"
        ON usage_monthly FOR UPDATE TO mcp_viewer USING (true) WITH CHECK (true)
    $POLICY$;
  END IF;
END$$;
