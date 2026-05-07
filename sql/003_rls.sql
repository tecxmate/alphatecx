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

-- Read-only on reference table + the filtered view layered on top
GRANT SELECT ON dim_ticker TO mcp_viewer;
GRANT SELECT ON dim_supply_chain TO mcp_viewer;

-- Read-only on raw tables (for drill-down, if needed)
GRANT SELECT ON raw_twse_t86 TO mcp_viewer;
GRANT SELECT ON raw_twse_holdings TO mcp_viewer;
GRANT SELECT ON raw_twse_margin TO mcp_viewer;
GRANT SELECT ON raw_twse_ohlcv TO mcp_viewer;
GRANT SELECT ON raw_monthly_revenue TO mcp_viewer;

-- ingestion_log: read access for the publicly-exposed sc_data_status tool.
-- Contents are benign (source, date, row counts, status, error_msg) — no PII or secrets.
GRANT SELECT ON ingestion_log TO mcp_viewer;

-- Quant signal layer (created by sql/004_quant.sql).
-- Wrapped in DO blocks so this RLS file can run before 004 if order is wrong.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='signal_value') THEN
    EXECUTE 'GRANT SELECT ON signal_value TO mcp_viewer';
    EXECUTE 'ALTER TABLE signal_value ENABLE ROW LEVEL SECURITY';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_matviews
             WHERE schemaname='public' AND matviewname='view_latest_signals') THEN
    EXECUTE 'GRANT SELECT ON view_latest_signals TO mcp_viewer';
  END IF;
END$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='signal_value') THEN
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_read_signal_value" ON signal_value';
    EXECUTE $POLICY$
      CREATE POLICY "mcp_viewer_read_signal_value"
        ON signal_value FOR SELECT TO mcp_viewer USING (true)
    $POLICY$;
  END IF;
END$$;

-- News (Phase 2a). Wrapped in DO so 003 can run even if 005 hasn't.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='raw_news') THEN
    EXECUTE 'GRANT SELECT ON raw_news TO mcp_viewer';
    EXECUTE 'ALTER TABLE raw_news ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_read_news" ON raw_news';
    EXECUTE $POLICY$
      CREATE POLICY "mcp_viewer_read_news"
        ON raw_news FOR SELECT TO mcp_viewer USING (true)
    $POLICY$;
  END IF;
END$$;

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
ALTER TABLE dim_ticker ENABLE ROW LEVEL SECURITY;
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

DROP POLICY IF EXISTS "mcp_viewer_read_ticker" ON dim_ticker;
CREATE POLICY "mcp_viewer_read_ticker"
  ON dim_ticker FOR SELECT TO mcp_viewer USING (true);
-- The dim_supply_chain view inherits this via security_invoker=true.

-- ingestion_log read policy — required by sc_data_status. error_msg fields
-- could in theory leak DSN fragments from a connection-error trace; keep
-- error_msg sanitized at write time (loader.log_ingestion takes str(e)).
DROP POLICY IF EXISTS "mcp_viewer_read_ingestion_log" ON ingestion_log;
CREATE POLICY "mcp_viewer_read_ingestion_log"
  ON ingestion_log FOR SELECT TO mcp_viewer USING (true);
