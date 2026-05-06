-- alphatecx v2 — Row-Level Security
-- Run after 001_schema.sql
-- see docs/wiki/topics/system-architecture.md (MCP Security section)

-- ============================================================================
-- Read-only role for MCP (Claude)
-- ============================================================================

-- Create the role if it doesn't exist
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer') THEN
    CREATE ROLE mcp_viewer WITH LOGIN PASSWORD 'CHANGE_ME_IN_SUPABASE';
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

-- Allow mcp_viewer to read all rows from data tables
CREATE POLICY IF NOT EXISTS "mcp_viewer_read_t86"
  ON raw_twse_t86 FOR SELECT TO mcp_viewer USING (true);
CREATE POLICY IF NOT EXISTS "mcp_viewer_read_holdings"
  ON raw_twse_holdings FOR SELECT TO mcp_viewer USING (true);
CREATE POLICY IF NOT EXISTS "mcp_viewer_read_margin"
  ON raw_twse_margin FOR SELECT TO mcp_viewer USING (true);
CREATE POLICY IF NOT EXISTS "mcp_viewer_read_ohlcv"
  ON raw_twse_ohlcv FOR SELECT TO mcp_viewer USING (true);
CREATE POLICY IF NOT EXISTS "mcp_viewer_read_revenue"
  ON raw_monthly_revenue FOR SELECT TO mcp_viewer USING (true);
CREATE POLICY IF NOT EXISTS "mcp_viewer_read_supply_chain"
  ON dim_supply_chain FOR SELECT TO mcp_viewer USING (true);

-- Block mcp_viewer from seeing ingestion_log (internal only)
-- No policy = no access when RLS is enabled
