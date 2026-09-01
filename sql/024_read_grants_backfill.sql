-- alphatecx v2 — Read-grant backfill for tables added after 003_rls.sql
--
-- 003 grants mcp_viewer SELECT on an ENUMERATED list of tables (lines 33-149).
-- Every table created by a later migration therefore needs its own grant, and
-- two things went wrong with that:
--
--   * 010 (lead_lag) and 011 (raw_twse_valuation, raw_twse_index) ship no grant
--     block at all;
--   * 015 (market_holidays), 016 (raw_twse_dividend) and 017 (raw_finmind_*) do
--     grant correctly — but behind `IF EXISTS (… rolname = 'mcp_viewer')`, and
--     apply_schema.py runs them in the BASE pass, before 003 creates that role.
--     On a database whose mcp_viewer was created by the same --rls run the guard
--     is false and the grant silently no-ops. Unlike 018/019/020/021/022/023,
--     none of these files is re-appended after 003, so it never lands.
--
-- The symptom is a read tool that fails with `permission denied for table …`
-- while the table itself is fully populated. Observed live 2026-08-10: the five
-- valuation/dividend tools (q_valuation, dividend_calendar, beginner_stock_card
-- among them) were dead, and session_state degraded to weekend-only because it
-- could not read market_holidays.
--
-- This file is the single place that re-grants everything the read path touches
-- and that 003 does not already cover. It is re-appended after 003 by
-- apply_schema.py and applied standalone by apply_delta.py. SELECT survives
-- 003's blanket `REVOKE INSERT, UPDATE, DELETE`, so — unlike the write grants —
-- ordering against that REVOKE does not matter here; ordering against role
-- CREATION does, which is the whole reason this exists.
--
-- Idempotent and both role- and table-guarded: a no-op before 003 creates
-- mcp_viewer, a no-op for a table a given database has not created yet, and safe
-- to run any number of times.

DO $$
DECLARE
  t TEXT;
  -- Every table read by mcp_server/api (db_v2.py + rg/) that 003 does not grant.
  -- Keep in sync when a migration adds a table the MCP server reads.
  tables TEXT[] := ARRAY[
    'lead_lag',                     -- 010, q_lead_lag
    'raw_twse_valuation',           -- 011, q_valuation / beginner_stock_card
    'raw_twse_index',               -- 011, q_index_history / rg TAIEX series
    'market_holidays',              -- 015, session_state trading calendar
    'raw_twse_dividend',            -- 016, dividend_calendar
    'raw_finmind_dividend',         -- 017, dividend fill
    'raw_finmind_news',             -- 017, news fallback
    'raw_macro'                     -- 026, q_macro / pre-market brief
  ];
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer') THEN
    RETURN;
  END IF;

  FOREACH t IN ARRAY tables LOOP
    IF EXISTS (SELECT FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = t) THEN
      EXECUTE format('GRANT SELECT ON %I TO mcp_viewer', t);
      EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
      -- DROP-then-CREATE rather than CREATE POLICY IF NOT EXISTS, which only
      -- landed in PG15 and this schema still targets older servers.
      EXECUTE format('DROP POLICY IF EXISTS "mcp_viewer_read_%s" ON %I', t, t);
      EXECUTE format(
        'CREATE POLICY "mcp_viewer_read_%s" ON %I FOR SELECT TO mcp_viewer USING (true)',
        t, t);
    END IF;
  END LOOP;
END$$;
