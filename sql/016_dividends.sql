-- alphatecx v2 — Ex-dividend / ex-rights calendar
--
-- Backs dividend_calendar(): answers "does a buyer today still receive the
-- dividend?" — the exact question that produced the 華碩 error (its 6% yield
-- was quoted as forward after it had already gone ex on 2026-07-01).
--
-- Sourced from TWSE TWT49U (除權除息計算結果表, actual ex-dates) for the past
-- window and TWT48U (除權除息預告表, upcoming forecast). `ex_date` is the ex
-- trading date: buy on or after it and you do NOT get the distribution.
--
-- `ex_type` is TWSE's 權/息: '息' cash dividend, '權' stock rights, '權息' both.
-- `cash_value` is 權值+息值 (combined for 權息; equals the cash dividend for 息).

CREATE TABLE IF NOT EXISTS raw_twse_dividend (
    ex_date        DATE NOT NULL,
    ticker_id      TEXT NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    ex_type        TEXT,                    -- 息 | 權 | 權息
    cash_value     REAL,                    -- 權值+息值 (元/股)
    pre_ex_close   REAL,                    -- 除權息前收盤價
    reference_price REAL,                   -- 除權息參考價
    status         TEXT NOT NULL DEFAULT 'actual',   -- 'actual' (TWT49U) | 'forecast' (TWT48U)
    source         TEXT NOT NULL DEFAULT 'twse',
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ex_date, ticker_id)
);

CREATE INDEX IF NOT EXISTS idx_dividend_ticker ON raw_twse_dividend (ticker_id, ex_date DESC);

-- Read access for the MCP read-only role (see sql/003_rls.sql), guarded.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer') THEN
    EXECUTE 'GRANT SELECT ON raw_twse_dividend TO mcp_viewer';
    EXECUTE 'ALTER TABLE raw_twse_dividend ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_read_dividend" ON raw_twse_dividend';
    EXECUTE 'CREATE POLICY "mcp_viewer_read_dividend" '
            'ON raw_twse_dividend FOR SELECT TO mcp_viewer USING (true)';
  END IF;
END $$;
