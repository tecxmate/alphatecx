-- alphatecx v2 — lead-lag correlation table
-- Stores cross-correlation between pairs of tickers at multiple lags.
-- A row says: "returns of upstream_id at day t correlate with returns
-- of downstream_id at day t+lag_days, with strength `correlation`,
-- computed over `n_obs` trading days ending `asof`."
--
-- We keep one snapshot per asof date; cron regenerates after OHLCV.

CREATE TABLE IF NOT EXISTS lead_lag (
    asof          DATE NOT NULL,
    upstream_id   TEXT NOT NULL,
    downstream_id TEXT NOT NULL,
    lag_days      INT  NOT NULL,
    correlation   REAL NOT NULL,
    n_obs         INT  NOT NULL,
    window_days   INT  NOT NULL,
    PRIMARY KEY (asof, upstream_id, downstream_id, lag_days)
);

CREATE INDEX IF NOT EXISTS idx_leadlag_up ON lead_lag (upstream_id, asof DESC);
CREATE INDEX IF NOT EXISTS idx_leadlag_down ON lead_lag (downstream_id, asof DESC);

-- View: best forward lag per pair (lag > 0, max correlation, classified tickers).
CREATE OR REPLACE VIEW view_lead_lag_best AS
WITH ranked AS (
    SELECT
        ll.*,
        ROW_NUMBER() OVER (
            PARTITION BY upstream_id, downstream_id, asof
            ORDER BY correlation DESC
        ) AS rn
    FROM lead_lag ll
    WHERE lag_days > 0
)
SELECT asof, upstream_id, downstream_id, lag_days, correlation, n_obs, window_days
FROM ranked
WHERE rn = 1;
