-- alphatecx v2 — Risk Guard (RISK_GUARD_PRD.md v1.1)
--
-- A post-close risk system whose only job is to stop the operator losing money.
-- Every table is `rg_` prefixed so Risk Guard state is separable from the
-- market-data layer it reads (raw_twse_*, dim_*) and can be dropped wholesale
-- without touching ingestion.
--
-- Phase 1 scope: M1 risk light, M2 stop alerts, M2b settlement check,
-- M5 held_pct snapshot, M7 no-trade days, decision journal.
-- Tables for M3 (sector strength) are created now because the daily snapshot
-- has to start accumulating history before the module that reads it exists.

-- ── Monitored names: positions and watch-only ────────────────────────────────
-- One table for both because M2 (stop alerts) and M4 (intraday anomaly) walk
-- the same list; `kind` decides whether stop lines are enforced.
CREATE TABLE IF NOT EXISTS rg_positions (
    id            SERIAL PRIMARY KEY,
    ticker_id     TEXT NOT NULL,
    name          TEXT,
    kind          TEXT NOT NULL DEFAULT 'position',   -- position | watch
    cost          NUMERIC,
    qty_lots      NUMERIC,
    warn_price    NUMERIC,          -- 警戒線 — halve the position
    exit_price    NUMERIC,          -- 出場線 — exit in full
    hard_stop_pct NUMERIC DEFAULT 10,
    note          TEXT,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- /setpos and /watch upsert by ticker, so one row per ticker.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rg_positions_ticker
    ON rg_positions (ticker_id);
CREATE INDEX IF NOT EXISTS idx_rg_positions_active
    ON rg_positions (active) WHERE active;

-- ── M1: daily market risk light ──────────────────────────────────────────────
-- `reasons` holds the per-subitem breakdown (points + inputs + data_missing
-- flags) so a light is always explainable after the fact, and so a threshold
-- change can be replayed against stored inputs rather than re-fetched.
CREATE TABLE IF NOT EXISTS rg_market_daily (
    date               DATE PRIMARY KEY,
    taiex_close        NUMERIC,
    taiex_pct          NUMERIC,
    taiex_ma20         NUMERIC,
    taiex_ma60         NUMERIC,
    taiex_ret_5d_pct   NUMERIC,
    adv_count          INT,
    dec_count          INT,
    adv_ratio_5d       NUMERIC,
    margin_balance     NUMERIC,
    margin_chg_5d_pct  NUMERIC,
    fut_foreign_net_oi INT,
    risk_light         TEXT,        -- green | yellow | red
    risk_score         INT,
    reasons            JSONB,
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Alert event stream ───────────────────────────────────────────────────────
-- Every push is written here first and marked `pushed` after Telegram accepts
-- it. A crashed pipeline therefore loses at most the send, never the event —
-- and a critical alert can be re-sent by clearing `pushed`.
CREATE TABLE IF NOT EXISTS rg_alerts (
    id         SERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    date       DATE NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Taipei')::date,
    kind       TEXT NOT NULL,
    ticker_id  TEXT,
    -- What makes this alert distinct within (date, kind). Usually the ticker,
    -- but settlement alerts key on the settlement date and light changes on
    -- the new colour — both are ticker-less and must still de-dup.
    dedup_key  TEXT NOT NULL DEFAULT '',
    severity   TEXT NOT NULL DEFAULT 'info',   -- info | warn | critical
    payload    JSONB,
    message    TEXT,
    pushed     BOOLEAN NOT NULL DEFAULT FALSE,
    pushed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rg_alerts_ts ON rg_alerts (ts DESC);
CREATE INDEX IF NOT EXISTS idx_rg_alerts_unpushed ON rg_alerts (id) WHERE NOT pushed;

-- De-dup guard ("觸發後標記不重複轟炸"): one alert per (day, kind, subject).
-- Re-running the post-close pipeline, or a workflow retry, then records and
-- pushes nothing a second time. NOT NULL + '' default rather than a nullable
-- column, because NULLs are distinct from each other in a unique index and
-- ticker-less alerts would slip through.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rg_alerts_daily_kind
    ON rg_alerts (date, kind, dedup_key);

-- ── M5 groundwork: foreign holding % daily snapshot ──────────────────────────
-- Started in Phase 1 purely to accumulate the history the Phase 3 intent score
-- needs; nothing reads it yet.
CREATE TABLE IF NOT EXISTS rg_foreign_holdings_daily (
    date      DATE NOT NULL,
    ticker_id TEXT NOT NULL,
    held_pct  NUMERIC,
    PRIMARY KEY (date, ticker_id)
);

-- ── M3 groundwork: sector strength daily ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS rg_sector_daily (
    date        DATE NOT NULL,
    sector_id   TEXT NOT NULL,
    rs_20d      NUMERIC,
    inst_net_5d NUMERIC,
    rank        INT,
    PRIMARY KEY (date, sector_id)
);

-- ── M2b: settlement schedule ─────────────────────────────────────────────────
-- net_amount is signed TWD: negative = cash owed on that date.
CREATE TABLE IF NOT EXISTS rg_settlements (
    date       DATE PRIMARY KEY,
    net_amount NUMERIC NOT NULL DEFAULT 0,
    note       TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Individual fills, kept so a settlement row can be rebuilt or corrected.
CREATE TABLE IF NOT EXISTS rg_trades (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    trade_date  DATE NOT NULL,
    settle_date DATE NOT NULL,
    ticker_id   TEXT NOT NULL,
    side        TEXT NOT NULL,     -- buy | sell
    price       NUMERIC NOT NULL,
    lots        NUMERIC NOT NULL,
    net_amount  NUMERIC NOT NULL,  -- signed, fees included
    note        TEXT
);

CREATE INDEX IF NOT EXISTS idx_rg_trades_settle ON rg_trades (settle_date);

-- Manually reported settlement-account cash (`/balance <amount>`). Append-only
-- so a stale balance is visibly stale rather than silently overwritten.
CREATE TABLE IF NOT EXISTS rg_balances (
    id     SERIAL PRIMARY KEY,
    ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
    amount NUMERIC NOT NULL,
    note   TEXT
);

-- ── Decision journal (rg_journal_add) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rg_journal (
    id        SERIAL PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    text      TEXT NOT NULL,
    ticker_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_rg_journal_ts ON rg_journal (ts DESC);

-- ── M7: rhythm layer veto ────────────────────────────────────────────────────
-- Read ONLY by checklist Q5 and the pre-market note. PRD §5 M7 makes it a
-- code-review acceptance condition that this table never feeds a score, a
-- light, or an alert trigger.
CREATE TABLE IF NOT EXISTS rg_no_trade_days (
    date   DATE PRIMARY KEY,
    reason TEXT
);

-- ── Grants for the read-only MCP role ────────────────────────────────────────
-- Mirrors sql/003_rls.sql. `rg_journal` additionally needs INSERT because the
-- rg_journal_add tool writes through the MCP connection (same precedent as
-- watchlist / w_add). Guarded so this file still applies where mcp_viewer was
-- never created.
--
-- NOTE: 003_rls.sql ends with `REVOKE INSERT, UPDATE, DELETE ON ALL TABLES ...`
-- placed *after* its own watchlist grant. Re-running 003 after this file
-- therefore strips rg_journal's INSERT. Apply order is 003 last only with
-- --rls; apply_schema.py appends it, so run this file (018) after any --rls run.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer') THEN
    EXECUTE 'GRANT SELECT ON rg_positions, rg_market_daily, rg_alerts,
                              rg_foreign_holdings_daily, rg_sector_daily,
                              rg_settlements, rg_trades, rg_balances,
                              rg_journal, rg_no_trade_days
             TO mcp_viewer';
    EXECUTE 'GRANT INSERT ON rg_journal TO mcp_viewer';
    EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE rg_journal_id_seq TO mcp_viewer';

    EXECUTE 'ALTER TABLE rg_journal ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_read_rg_journal" ON rg_journal';
    EXECUTE 'CREATE POLICY "mcp_viewer_read_rg_journal"
               ON rg_journal FOR SELECT TO mcp_viewer USING (true)';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_insert_rg_journal" ON rg_journal';
    EXECUTE 'CREATE POLICY "mcp_viewer_insert_rg_journal"
               ON rg_journal FOR INSERT TO mcp_viewer WITH CHECK (true)';
  END IF;
END$$;

-- ── Seed: watch list (PRD §4 v1.1 — operator is currently 100% cash) ─────────
INSERT INTO rg_positions (ticker_id, name, kind, note) VALUES
 ('2344','華邦電','watch','記憶體主攻候選。進場三開關:大盤連2日站穩 + 回踩不破 + 外資連買。回踩參考區收盤後更新'),
 ('2324','仁寶','watch','副線。復活條件:收復34箱底 + 外資回買 + 相對大盤不轉弱(記憶體漲價=其成本,標準加嚴)'),
 ('8299','群聯','watch','NAND控制晶片,次選'),
 ('2408','南亞科','watch','族群風向指標,資金不足整張,僅觀察')
ON CONFLICT (ticker_id) DO NOTHING;

-- 拉黑名單 — stored inactive so /check can warn on them without them entering
-- the monitored set. Never buy-suggested; the note is the whole point.
INSERT INTO rg_positions (ticker_id, name, kind, active, note) VALUES
 ('2327','國巨','watch',FALSE,'拉黑:2026/7 週期 -55%'),
 ('2338','光罩','watch',FALSE,'拉黑:2026/7 週期重挫'),
 ('6239','力成','watch',FALSE,'拉黑:<320 不碰'),
 ('2303','聯電','watch',FALSE,'拉黑:<130 不碰'),
 ('3374','精材','watch',FALSE,'拉黑')
ON CONFLICT (ticker_id) DO NOTHING;
