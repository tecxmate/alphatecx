-- alphatecx v2 — Materialized Views
-- Run after 001_schema.sql and after initial data load
-- see docs/wiki/topics/system-architecture.md

-- ============================================================================
-- view_sector_momentum — the magic layer
-- ============================================================================
-- Joins raw_twse_t86 with dim_supply_chain to aggregate institutional flows
-- by AI pillar and supply chain node. This is what Claude queries.

-- Drop first so we can recreate cleanly
DROP MATERIALIZED VIEW IF EXISTS view_sector_momentum;

CREATE MATERIALIZED VIEW view_sector_momentum AS
WITH
  -- Last 5 trading days (by distinct date in data)
  recent_dates AS (
    SELECT DISTINCT date
    FROM raw_twse_t86
    ORDER BY date DESC
    LIMIT 20  -- grab extra for safety
  ),
  dated AS (
    SELECT
      date,
      ROW_NUMBER() OVER (ORDER BY date DESC) AS day_rank
    FROM recent_dates
  ),
  flows AS (
    SELECT
      t.date,
      d.day_rank,
      t.ticker_id,
      t.company_name,
      t.foreign_net,
      t.trust_net,
      t.dealer_net,
      t.total_net,
      COALESCE(sc.ai_pillar, 'unclassified') AS ai_pillar,
      COALESCE(sc.node, 'unclassified')      AS node
    FROM raw_twse_t86 t
    JOIN dated d ON d.date = t.date
    LEFT JOIN dim_supply_chain sc ON sc.ticker_id = t.ticker_id
  ),
  -- Aggregated by pillar + node
  sector_agg AS (
    SELECT
      ai_pillar,
      node,
      -- 1-day (latest)
      SUM(CASE WHEN day_rank = 1 THEN foreign_net ELSE 0 END) AS foreign_1d,
      SUM(CASE WHEN day_rank = 1 THEN total_net   ELSE 0 END) AS total_1d,
      -- 3-day
      SUM(CASE WHEN day_rank <= 3 THEN foreign_net ELSE 0 END) AS foreign_3d,
      SUM(CASE WHEN day_rank <= 3 THEN total_net   ELSE 0 END) AS total_3d,
      -- 5-day
      SUM(CASE WHEN day_rank <= 5 THEN foreign_net ELSE 0 END) AS foreign_5d,
      SUM(CASE WHEN day_rank <= 5 THEN total_net   ELSE 0 END) AS total_5d,
      -- 10-day
      SUM(CASE WHEN day_rank <= 10 THEN foreign_net ELSE 0 END) AS foreign_10d,
      SUM(CASE WHEN day_rank <= 10 THEN total_net   ELSE 0 END) AS total_10d,
      -- 20-day
      SUM(foreign_net) AS foreign_20d,
      SUM(total_net)   AS total_20d,
      -- Counts
      COUNT(DISTINCT CASE WHEN day_rank <= 5 THEN flows.ticker_id END) AS tickers_5d
    FROM flows
    GROUP BY ai_pillar, node
  )
SELECT
  sa.*,
  -- Top accumulated ticker in each node (by 5-day foreign net)
  (
    SELECT f.ticker_id
    FROM flows f
    WHERE f.ai_pillar = sa.ai_pillar
      AND f.node = sa.node
      AND f.day_rank <= 5
    GROUP BY f.ticker_id
    ORDER BY SUM(f.foreign_net) DESC
    LIMIT 1
  ) AS top_ticker_5d,
  (
    SELECT f.company_name
    FROM flows f
    WHERE f.ai_pillar = sa.ai_pillar
      AND f.node = sa.node
      AND f.day_rank <= 5
    GROUP BY f.ticker_id, f.company_name
    ORDER BY SUM(f.foreign_net) DESC
    LIMIT 1
  ) AS top_ticker_5d_name,
  now() AS refreshed_at
FROM sector_agg sa
ORDER BY foreign_5d DESC;

-- Unique index for concurrent refresh
CREATE UNIQUE INDEX IF NOT EXISTS idx_vsm_pillar_node
  ON view_sector_momentum (ai_pillar, node);

-- ============================================================================
-- view_ticker_momentum — per-ticker multi-day flows
-- ============================================================================
-- For drill-down queries: "show me all tickers in Liquid Cooling with 3-day
-- consecutive net buying"

DROP MATERIALIZED VIEW IF EXISTS view_ticker_momentum;

CREATE MATERIALIZED VIEW view_ticker_momentum AS
WITH
  recent_dates AS (
    SELECT DISTINCT date FROM raw_twse_t86 ORDER BY date DESC LIMIT 20
  ),
  dated AS (
    SELECT date, ROW_NUMBER() OVER (ORDER BY date DESC) AS day_rank
    FROM recent_dates
  ),
  flows AS (
    SELECT
      t.date, d.day_rank, t.ticker_id, t.company_name, t.market,
      t.foreign_net, t.trust_net, t.dealer_net, t.total_net,
      COALESCE(sc.ai_pillar, 'unclassified') AS ai_pillar,
      COALESCE(sc.node, 'unclassified') AS node
    FROM raw_twse_t86 t
    JOIN dated d ON d.date = t.date
    LEFT JOIN dim_supply_chain sc ON sc.ticker_id = t.ticker_id
  )
SELECT
  ticker_id,
  company_name,
  market,
  ai_pillar,
  node,
  -- Latest day
  SUM(CASE WHEN day_rank = 1 THEN foreign_net ELSE 0 END) AS foreign_1d,
  SUM(CASE WHEN day_rank = 1 THEN total_net   ELSE 0 END) AS total_1d,
  -- 3-day
  SUM(CASE WHEN day_rank <= 3 THEN foreign_net ELSE 0 END) AS foreign_3d,
  SUM(CASE WHEN day_rank <= 3 THEN total_net   ELSE 0 END) AS total_3d,
  -- 5-day
  SUM(CASE WHEN day_rank <= 5 THEN foreign_net ELSE 0 END) AS foreign_5d,
  SUM(CASE WHEN day_rank <= 5 THEN total_net   ELSE 0 END) AS total_5d,
  -- 10-day
  SUM(CASE WHEN day_rank <= 10 THEN foreign_net ELSE 0 END) AS foreign_10d,
  SUM(CASE WHEN day_rank <= 10 THEN total_net   ELSE 0 END) AS total_10d,
  -- 20-day
  SUM(foreign_net) AS foreign_20d,
  SUM(total_net)   AS total_20d,
  -- Consecutive buy days (foreign net > 0 streak from latest)
  (
    SELECT COUNT(*)
    FROM flows f2
    WHERE f2.ticker_id = flows.ticker_id
      AND f2.day_rank <= 20
      AND f2.foreign_net > 0
      AND NOT EXISTS (
        SELECT 1 FROM flows f3
        WHERE f3.ticker_id = f2.ticker_id
          AND f3.day_rank < f2.day_rank
          AND f3.foreign_net <= 0
      )
  ) AS consecutive_foreign_buy_days,
  now() AS refreshed_at
FROM flows
GROUP BY ticker_id, company_name, market, ai_pillar, node
ORDER BY foreign_5d DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_vtm_ticker
  ON view_ticker_momentum (ticker_id);

-- ============================================================================
-- Helper function to refresh both views (call after daily ingestion)
-- ============================================================================

CREATE OR REPLACE FUNCTION refresh_momentum_views()
RETURNS void AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY view_sector_momentum;
  REFRESH MATERIALIZED VIEW CONCURRENTLY view_ticker_momentum;
END;
$$ LANGUAGE plpgsql;
