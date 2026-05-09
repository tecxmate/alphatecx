-- alphatecx v2 — Valuation + sector indices
--
-- Two new raw tables harvested daily from TWSE:
--   raw_twse_valuation  per-ticker P/E, P/B, dividend yield (BWIBBU_d)
--   raw_twse_index      sector & cross-market indices (MI_INDEX type=IND)

CREATE TABLE IF NOT EXISTS raw_twse_valuation (
    date            DATE NOT NULL,
    ticker_id       TEXT NOT NULL,
    company_name    TEXT NOT NULL DEFAULT '',
    market          TEXT NOT NULL DEFAULT 'TWSE',
    close           REAL,
    dividend_yield  REAL,             -- 殖利率 %
    dividend_year   INT,              -- ROC year (e.g. 114 = 2025)
    pe_ratio        REAL,             -- 本益比, NULL when issuer reports no earnings
    pb_ratio        REAL,             -- 股價淨值比
    fiscal_period   TEXT,             -- e.g. '114/4' (ROC year/quarter of underlying report)
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (date, ticker_id)
);
CREATE INDEX IF NOT EXISTS idx_val_ticker ON raw_twse_valuation (ticker_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_val_date   ON raw_twse_valuation (date DESC);

CREATE TABLE IF NOT EXISTS raw_twse_index (
    date         DATE NOT NULL,
    index_name   TEXT NOT NULL,        -- e.g. '半導體類指數', '電子工業類指數', '發行量加權股價指數'
    close        REAL,
    change_pts   REAL,                 -- absolute points change vs prior close
    change_pct   REAL,                 -- percentage change vs prior close
    direction    TEXT,                 -- '+' or '-' (TWSE uses sign chars)
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (date, index_name)
);
CREATE INDEX IF NOT EXISTS idx_idx_date  ON raw_twse_index (date DESC);
CREATE INDEX IF NOT EXISTS idx_idx_name  ON raw_twse_index (index_name, date DESC);
