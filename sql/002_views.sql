-- alphatecx v2 — Materialized Views
-- Run after 001_schema.sql and after initial data load
-- see docs/wiki/topics/system-architecture.md

-- ============================================================================
-- view_sector_momentum — the magic layer
-- ============================================================================
-- Joins raw_twse_t86 with dim_ticker to aggregate institutional flows
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
    LEFT JOIN dim_ticker sc ON sc.ticker_id = t.ticker_id
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
,
  -- Pick top ticker per (pillar, node) once, with its name, in a single pass.
  -- Doing this as two separate correlated subqueries grouped on different
  -- keys could return a ticker_id and company_name from different rows when
  -- the same ticker has multiple display names in the data.
  ranked_tickers AS (
    SELECT
      ai_pillar, node, ticker_id, company_name,
      SUM(foreign_net) AS foreign_5d_ticker,
      ROW_NUMBER() OVER (
        PARTITION BY ai_pillar, node
        ORDER BY SUM(foreign_net) DESC
      ) AS rn
    FROM flows
    WHERE day_rank <= 5
    GROUP BY ai_pillar, node, ticker_id, company_name
  ),
  top_per_node AS (
    SELECT ai_pillar, node, ticker_id AS top_ticker_5d, company_name AS top_ticker_5d_name
    FROM ranked_tickers
    WHERE rn = 1
  )
SELECT
  sa.*,
  tpn.top_ticker_5d,
  tpn.top_ticker_5d_name,
  now() AS refreshed_at
FROM sector_agg sa
LEFT JOIN top_per_node tpn USING (ai_pillar, node)
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
    LEFT JOIN dim_ticker sc ON sc.ticker_id = t.ticker_id
  ),
  streaks AS (
    SELECT ticker_id, MIN(day_rank) AS first_non_buy_day
    FROM flows
    WHERE foreign_net <= 0
    GROUP BY ticker_id
  )
SELECT
  f.ticker_id,
  -- Name/market come from raw_twse_t86, which records whatever TWSE published on
  -- that date, so an issuer rename inside the 20-day window yields two spellings
  -- for one ticker. Grouping by them emits two rows and breaks the unique index
  -- on ticker_id alone (009805 新光→台新, 2026-07-13). Take the latest spelling.
  -- dim_ticker isn't the source because its LEFT JOIN would NULL out names for
  -- tickers it doesn't classify.
  (ARRAY_AGG(f.company_name ORDER BY f.date DESC))[1] AS company_name,
  (ARRAY_AGG(f.market       ORDER BY f.date DESC))[1] AS market,
  f.ai_pillar,
  f.node,
  -- Latest day
  SUM(CASE WHEN f.day_rank = 1 THEN f.foreign_net ELSE 0 END) AS foreign_1d,
  SUM(CASE WHEN f.day_rank = 1 THEN f.total_net   ELSE 0 END) AS total_1d,
  -- 3-day
  SUM(CASE WHEN f.day_rank <= 3 THEN f.foreign_net ELSE 0 END) AS foreign_3d,
  SUM(CASE WHEN f.day_rank <= 3 THEN f.total_net   ELSE 0 END) AS total_3d,
  -- 5-day
  SUM(CASE WHEN f.day_rank <= 5 THEN f.foreign_net ELSE 0 END) AS foreign_5d,
  SUM(CASE WHEN f.day_rank <= 5 THEN f.total_net   ELSE 0 END) AS total_5d,
  -- 10-day
  SUM(CASE WHEN f.day_rank <= 10 THEN f.foreign_net ELSE 0 END) AS foreign_10d,
  SUM(CASE WHEN f.day_rank <= 10 THEN f.total_net   ELSE 0 END) AS total_10d,
  -- 20-day
  SUM(f.foreign_net) AS foreign_20d,
  SUM(f.total_net)   AS total_20d,
  -- Consecutive buy days (foreign net > 0 streak from latest)
  COALESCE(MAX(s.first_non_buy_day) - 1, 20) AS consecutive_foreign_buy_days,
  now() AS refreshed_at
FROM flows f
LEFT JOIN streaks s ON s.ticker_id = f.ticker_id
GROUP BY f.ticker_id, f.ai_pillar, f.node
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
