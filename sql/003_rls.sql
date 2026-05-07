-- alphatecx v2 — Row-Level Security
-- Run after 001_schema.sql
-- see docs/wiki/topics/system-architecture.md (MCP Security section)

-- ============================================================================
-- Read-only role for MCP (Claude)
-- ============================================================================

-- Create the role if it doesn't exist.
-- The password MUST be set out-of-band before this file runs, e.g.:
--   psql "$DATABASE_URL" -v mcp_viewer_pw="$MCP_VIEWER_PASSWORD" -f sql/003_rls.sql
-- A literal placeholder password used to live here and was a real footgun.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer') THEN
    EXECUTE format('CREATE ROLE mcp_viewer WITH LOGIN PASSWORD %L',
                   current_setting('mcp_viewer.password', true));
  END IF;
END
$$;

-- Grant connect
GRANT CONNECT ON DATABASE postgres TO mcp_viewer;
GRANT USAGE ON SCHEMA public TO mcp_viewer;

-- Read-only on materialized views (what Claude should query)
GRANT SELECT ON view_sector_momentum TO mcp_viewer;
GRANT SELECT ON view_ticker_momentum TO mcp_viewer;

-- Read-only on reference table
GRANT SELECT ON dim_supply_chain TO mcp_viewer;

-- Read-only on raw tables (for drill-down, if needed)
GRANT SELECT ON raw_twse_t86 TO mcp_viewer;
GRANT SELECT ON raw_twse_holdings TO mcp_viewer;
GRANT SELECT ON raw_twse_margin TO mcp_viewer;
GRANT SELECT ON raw_twse_ohlcv TO mcp_viewer;
GRANT SELECT ON raw_monthly_revenue TO mcp_viewer;

-- Explicitly deny writes
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM mcp_viewer;

-- ============================================================================
-- Enable RLS on all tables
-- ============================================================================
-- Even though mcp_viewer only has SELECT, RLS adds defense-in-depth.

ALTER TABLE raw_twse_t86 ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_twse_holdings ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_twse_margin ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_twse_ohlcv ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_monthly_revenue ENABLE ROW LEVEL SECURITY;
ALTER TABLE dim_supply_chain ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_log ENABLE ROW LEVEL SECURITY;

-- Allow mcp_viewer to read all rows from data tables.
-- DROP-then-CREATE keeps this idempotent on Postgres < 15
-- (CREATE POLICY IF NOT EXISTS only landed in PG15).
DROP POLICY IF EXISTS "mcp_viewer_read_t86" ON raw_twse_t86;
CREATE POLICY "mcp_viewer_read_t86"
  ON raw_twse_t86 FOR SELECT TO mcp_viewer USING (true);

DROP POLICY IF EXISTS "mcp_viewer_read_holdings" ON raw_twse_holdings;
CREATE POLICY "mcp_viewer_read_holdings"
  ON raw_twse_holdings FOR SELECT TO mcp_viewer USING (true);

DROP POLICY IF EXISTS "mcp_viewer_read_margin" ON raw_twse_margin;
CREATE POLICY "mcp_viewer_read_margin"
  ON raw_twse_margin FOR SELECT TO mcp_viewer USING (true);

DROP POLICY IF EXISTS "mcp_viewer_read_ohlcv" ON raw_twse_ohlcv;
CREATE POLICY "mcp_viewer_read_ohlcv"
  ON raw_twse_ohlcv FOR SELECT TO mcp_viewer USING (true);

DROP POLICY IF EXISTS "mcp_viewer_read_revenue" ON raw_monthly_revenue;
CREATE POLICY "mcp_viewer_read_revenue"
  ON raw_monthly_revenue FOR SELECT TO mcp_viewer USING (true);

DROP POLICY IF EXISTS "mcp_viewer_read_supply_chain" ON dim_supply_chain;
CREATE POLICY "mcp_viewer_read_supply_chain"
  ON dim_supply_chain FOR SELECT TO mcp_viewer USING (true);

-- Block mcp_viewer from seeing ingestion_log (internal only)
-- No policy = no access when RLS is enabled
