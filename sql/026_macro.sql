-- Macro series — the overnight forces a beta market wakes up to.
--
-- Taiwan trades as a high-beta expression of the US semiconductor cycle and
-- the dollar: SOX and the TSMC ADR set the open's gap, the 10Y sets the
-- liquidity regime, USD/TWD is the foreign-flow tell. Everything else in this
-- schema is Taiwan-domestic and T+1; this is the one table whose data is
-- ALREADY KNOWN before the Taipei open, which is the whole point of it.
--
-- Shape mirrors raw_twse_index (date + name PK, one row per series per day)
-- rather than inventing a wide table with a column per series: a new series is
-- then a row, not a migration.
--
-- Deliberately NOT a trading-day oracle. `raw_twse_index` is what
-- loader.margin_sessions_missing and riskguard.store.last_trading_day use to
-- answer "did Taiwan trade" — and it must stay that way, because macro rows
-- exist for US sessions on days the TWSE was closed. Never join this table to
-- infer a Taiwan calendar.
CREATE TABLE IF NOT EXISTS raw_macro (
    date         DATE NOT NULL,
    series       TEXT NOT NULL,           -- sox | tsm_adr | us10y | dxy | usdtwd
    close        REAL,
    prev_close   REAL,
    pct_change   REAL,                    -- vs prev_close, stored so readers agree
    source       TEXT NOT NULL,           -- yahoo_chart_v8 | fred_csv
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (date, series)
);

CREATE INDEX IF NOT EXISTS idx_raw_macro_date ON raw_macro (date DESC);
CREATE INDEX IF NOT EXISTS idx_raw_macro_series_date ON raw_macro (series, date DESC);

-- NOTE ON GRANTS, deliberately absent here.
--
-- The mcp_viewer SELECT grant for this table lives in sql/024, NOT in this
-- file, and that is not an oversight. CLAUDE.md documents two traps that both
-- fail silently and look identical live (a populated table the server answers
-- `permission denied` on):
--
--   1. sql/003_rls.sql ENDS with a blanket `REVOKE INSERT, UPDATE, DELETE`,
--      so any write grant made before it is stripped.
--   2. A grant here would be wrapped in `IF EXISTS (… rolname='mcp_viewer')`,
--      which is FALSE during the base pass — 003 has not created the role yet —
--      so it no-ops, and not being re-appended it never lands. That cost read
--      access to everything 010/011/015/016/017 created until 024 backfilled it.
--
-- 024 runs in the --rls branch after the role exists. Put the grant there.
