-- 014_dim_ticker_classify.sql
-- Allow mcp_viewer to classify tickers from the in-page graph UI:
-- POST /g/{TOKEN}/classify performs an UPSERT into dim_ticker setting
-- (ai_pillar, node). Without these grants/policies the call fails with
-- `InsufficientPrivilege: permission denied for table dim_ticker`.
--
-- Scope: INSERT + UPDATE on dim_ticker only. ai_pillar/node are free-form
-- text columns; the API layer enforces that ai_pillar ∈ {semiconductor,
-- equipment, infrastructure, energy} and node matches a tight regex.
--
-- Run:
--   psql "$DATABASE_URL" -f sql/014_dim_ticker_classify.sql

GRANT INSERT, UPDATE ON dim_ticker TO mcp_viewer;

DROP POLICY IF EXISTS "mcp_viewer_insert_ticker" ON dim_ticker;
CREATE POLICY "mcp_viewer_insert_ticker"
  ON dim_ticker FOR INSERT TO mcp_viewer WITH CHECK (true);

DROP POLICY IF EXISTS "mcp_viewer_update_ticker" ON dim_ticker;
CREATE POLICY "mcp_viewer_update_ticker"
  ON dim_ticker FOR UPDATE TO mcp_viewer USING (true) WITH CHECK (true);
