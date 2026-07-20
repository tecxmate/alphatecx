-- alphatecx v2 — Market trading calendar
--
-- Backs session_state(): weekends are excluded in code, but statutory holidays
-- and ad-hoc typhoon closures need an authoritative table. Populated from the
-- TWSE published holiday schedule (rwd/zh/holidaySchedule), plus manual inserts
-- for typhoon days TWSE announces out of band.
--
-- A row is stored for every schedule entry; `is_closed` distinguishes real
-- closures ('依規定放假', '市場無交易', 補假, 春節) from the open reference days
-- the schedule also lists ('開始交易日', '最後交易日'), which trade normally.
-- is_trading_day(date) = weekday<5 AND NOT EXISTS(closed row for date).

CREATE TABLE IF NOT EXISTS market_holidays (
    cal_date     DATE NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    is_closed    BOOLEAN NOT NULL DEFAULT true,   -- false = open reference day
    note         TEXT,
    source       TEXT NOT NULL DEFAULT 'twse',    -- 'twse' | 'manual' (typhoon)
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cal_date)
);

CREATE INDEX IF NOT EXISTS idx_market_holidays_closed
    ON market_holidays (cal_date) WHERE is_closed;

-- Read access for the MCP read-only role (mirrors sql/003_rls.sql), guarded so
-- this file still applies on a DB where mcp_viewer was never created.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer') THEN
    EXECUTE 'GRANT SELECT ON market_holidays TO mcp_viewer';
    EXECUTE 'ALTER TABLE market_holidays ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_read_calendar" ON market_holidays';
    EXECUTE 'CREATE POLICY "mcp_viewer_read_calendar" '
            'ON market_holidays FOR SELECT TO mcp_viewer USING (true)';
  END IF;
END $$;
