-- alphatecx v2 — Quant signal layer (Phase 1)
-- Indicator + signal storage. Computed by src/quant/signals.py.
-- Backtest queries read raw_twse_ohlcv joined with signal_value.

-- ============================================================================
-- signal_value — one row per (signal, ticker, date)
-- ============================================================================
-- Multi-line indicators (e.g. MACD) split into separate signal_names rather
-- than a JSONB blob: simpler queries, single index covers everything.
CREATE TABLE IF NOT EXISTS signal_value (
    signal_name  TEXT NOT NULL,    -- e.g. 'rsi_14', 'macd_line', 'bb_pct_b'
    ticker_id    TEXT NOT NULL,
    date         DATE NOT NULL,
    value        DOUBLE PRECISION,
    computed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (signal_name, ticker_id, date)
);

-- "Show me the latest indicator stack for ticker X" — common query shape.
CREATE INDEX IF NOT EXISTS idx_sv_ticker_date
    ON signal_value (ticker_id, date DESC);

-- "Run a backtest on signal Y over the last N days" — common query shape.
CREATE INDEX IF NOT EXISTS idx_sv_signal_date
    ON signal_value (signal_name, date DESC);

-- ============================================================================
-- view_latest_signals — wide-form snapshot, one row per ticker
-- ============================================================================
-- Pivots signal_value so callers can read RSI/MACD/etc together. Materialized
-- because we read it more than we write it (signals computed daily, queries
-- many times). Refresh via refresh_quant_views() after compute_signals.
-- CASCADE because view_universe (sql/008) depends on this matview; on a re-run
-- against a populated DB a bare DROP fails ("other objects depend on it"). 008
-- recreates view_universe afterwards, so cascading is safe and keeps
-- apply_schema.py idempotent.
DROP MATERIALIZED VIEW IF EXISTS view_latest_signals CASCADE;

CREATE MATERIALIZED VIEW view_latest_signals AS
WITH ranked AS (
    SELECT
        signal_name, ticker_id, date, value,
        ROW_NUMBER() OVER (
            PARTITION BY signal_name, ticker_id ORDER BY date DESC
        ) AS rn
    FROM signal_value
),
latest AS (
    SELECT signal_name, ticker_id, date, value FROM ranked WHERE rn = 1
)
SELECT
    ticker_id,
    MAX(date) AS as_of,
    MAX(CASE WHEN signal_name = 'rsi_14'              THEN value END) AS rsi_14,
    MAX(CASE WHEN signal_name = 'macd_line'           THEN value END) AS macd_line,
    MAX(CASE WHEN signal_name = 'macd_signal_line'    THEN value END) AS macd_signal_line,
    MAX(CASE WHEN signal_name = 'macd_histogram'      THEN value END) AS macd_histogram,
    MAX(CASE WHEN signal_name = 'bb_pct_b'            THEN value END) AS bb_pct_b,
    MAX(CASE WHEN signal_name = 'atr_14'              THEN value END) AS atr_14,
    MAX(CASE WHEN signal_name = 'sma_50'              THEN value END) AS sma_50,
    MAX(CASE WHEN signal_name = 'sma_200'             THEN value END) AS sma_200,
    MAX(CASE WHEN signal_name = 'rs_vs_market_60'     THEN value END) AS rs_vs_market_60,
    MAX(CASE WHEN signal_name = 'pct_below_52w_high'  THEN value END) AS pct_below_52w_high,
    MAX(CASE WHEN signal_name = 'foreign_net_z20'     THEN value END) AS foreign_net_z20,
    MAX(CASE WHEN signal_name = 'foreign_net_5d_sum'  THEN value END) AS foreign_net_5d_sum,
    MAX(CASE WHEN signal_name = 'total_net_z20'       THEN value END) AS total_net_z20
FROM latest
GROUP BY ticker_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_vls_ticker
    ON view_latest_signals (ticker_id);

-- ============================================================================
-- Refresh helper
-- ============================================================================
CREATE OR REPLACE FUNCTION refresh_quant_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY view_latest_signals;
END;
$$ LANGUAGE plpgsql;

-- mcp_viewer grants for signal_value + view_latest_signals live in 003_rls.sql
-- so this file can run standalone without the RLS role existing.
