-- alphatecx v2 — Database Schema
-- Run against Supabase (PostgreSQL 15+)
-- see docs/wiki/topics/system-architecture.md

-- ============================================================================
-- 1. dim_ticker — universe of every ticker we've ever seen on TWSE/TPEX
-- ============================================================================
-- Auto-discovered: each T86 fetch upserts every ticker it returns. Most rows
-- are unclassified (ETFs, small caps, anything that ever traded). The 27
-- supply-chain-relevant tickers carry ai_pillar + node; everything else has
-- those columns NULL. The `dim_supply_chain` view below filters to the
-- classified subset, which is what callers usually mean by "supply chain".

CREATE TABLE IF NOT EXISTS dim_ticker (
    ticker_id    TEXT PRIMARY KEY,            -- e.g. '2330'
    company_name TEXT NOT NULL DEFAULT '',
    market       TEXT NOT NULL DEFAULT 'TWSE', -- 'TWSE' or 'TPEX'
    ai_pillar    TEXT,                         -- 'semiconductor', 'equipment', 'infrastructure', 'energy', NULL = unclassified
    node         TEXT,                         -- e.g. 'advanced-foundry', 'liquid-cooling'
    us_partners  TEXT[],                       -- US customer/partner companies
    tags         TEXT[],                       -- freeform tags
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dt_pillar ON dim_ticker (ai_pillar);
CREATE INDEX IF NOT EXISTS idx_dt_node   ON dim_ticker (node);

-- Filtered view — the 27-ish classified rows, named for what callers expect.
-- security_invoker=true keeps RLS on dim_ticker enforced under the caller.
CREATE OR REPLACE VIEW dim_supply_chain WITH (security_invoker = true) AS
SELECT ticker_id, company_name, market, ai_pillar, node, us_partners,
       created_at, updated_at
FROM dim_ticker
WHERE ai_pillar IS NOT NULL;

-- ============================================================================
-- 2. raw_twse_t86 — daily institutional net buy/sell (Priority 1)
-- ============================================================================
-- One row per ticker per trading day. Core data for sector momentum.

CREATE TABLE IF NOT EXISTS raw_twse_t86 (
    date         DATE NOT NULL,
    ticker_id    TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    market       TEXT NOT NULL DEFAULT 'TWSE',  -- 'TWSE' or 'TPEX'
    foreign_net  BIGINT NOT NULL DEFAULT 0,     -- 外資買賣超 (shares)
    trust_net    BIGINT NOT NULL DEFAULT 0,     -- 投信買賣超 (shares)
    dealer_net   BIGINT NOT NULL DEFAULT 0,     -- 自營商買賣超 (shares)
    total_net    BIGINT NOT NULL DEFAULT 0,     -- 三大法人買賣超 (shares)
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (date, ticker_id)
);

CREATE INDEX IF NOT EXISTS idx_t86_ticker ON raw_twse_t86 (ticker_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_t86_date   ON raw_twse_t86 (date DESC);

-- ============================================================================
-- 3. raw_twse_holdings — MI_QFIIS foreign holding % (Priority 2)
-- ============================================================================

CREATE TABLE IF NOT EXISTS raw_twse_holdings (
    date                  DATE NOT NULL,
    ticker_id             TEXT NOT NULL,
    company_name          TEXT NOT NULL DEFAULT '',
    market                TEXT NOT NULL DEFAULT 'TWSE',
    shares_outstanding    BIGINT,
    foreign_held_shares   BIGINT,
    foreign_held_pct      REAL,        -- percentage, e.g. 76.5
    foreign_room_pct      REAL,        -- remaining headroom %
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (date, ticker_id)
);

CREATE INDEX IF NOT EXISTS idx_hold_ticker ON raw_twse_holdings (ticker_id, date DESC);

-- ============================================================================
-- 4. raw_twse_margin — 融資融券 margin/short balance (Priority 3)
-- ============================================================================

CREATE TABLE IF NOT EXISTS raw_twse_margin (
    date                  DATE NOT NULL,
    ticker_id             TEXT NOT NULL,
    company_name          TEXT NOT NULL DEFAULT '',
    market                TEXT NOT NULL DEFAULT 'TWSE',
    margin_balance        BIGINT NOT NULL DEFAULT 0,     -- 融資餘額 (張)
    margin_change         BIGINT NOT NULL DEFAULT 0,     -- daily change
    margin_limit          BIGINT,
    short_balance         BIGINT NOT NULL DEFAULT 0,     -- 融券餘額 (張)
    short_change          BIGINT NOT NULL DEFAULT 0,     -- daily change
    short_limit           BIGINT,
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (date, ticker_id)
);

CREATE INDEX IF NOT EXISTS idx_margin_ticker ON raw_twse_margin (ticker_id, date DESC);

-- ============================================================================
-- 5. raw_twse_ohlcv — daily price bars (Priority 4)
-- ============================================================================

CREATE TABLE IF NOT EXISTS raw_twse_ohlcv (
    date            DATE NOT NULL,
    ticker_id       TEXT NOT NULL,
    market          TEXT NOT NULL DEFAULT 'TWSE',
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    volume_shares   BIGINT,
    turnover_twd    BIGINT,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (date, ticker_id)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker ON raw_twse_ohlcv (ticker_id, date DESC);

-- ============================================================================
-- 6. raw_monthly_revenue — MOPS monthly revenue (Priority 5)
-- ============================================================================

CREATE TABLE IF NOT EXISTS raw_monthly_revenue (
    ym              TEXT NOT NULL,           -- 'YYYY-MM'
    ticker_id       TEXT NOT NULL,
    company_name    TEXT NOT NULL DEFAULT '',
    market          TEXT NOT NULL DEFAULT 'TWSE',
    industry        TEXT,
    revenue_k_twd   BIGINT,                 -- 千元 (thousands TWD)
    mom_pct         REAL,
    yoy_pct         REAL,
    ytd_revenue     BIGINT,
    ytd_prev_year   BIGINT,
    ytd_yoy_pct     REAL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (ym, ticker_id)
);

CREATE INDEX IF NOT EXISTS idx_rev_ticker ON raw_monthly_revenue (ticker_id, ym DESC);

-- ============================================================================
-- 7. ingestion_log — track what was ingested and when
-- ============================================================================

CREATE TABLE IF NOT EXISTS ingestion_log (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source       TEXT NOT NULL,              -- 'twse_t86', 'tpex_t86', 'twse_holdings', etc.
    target_date  DATE,                       -- the trading date being ingested
    rows_upserted INT NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'ok', -- 'ok', 'error', 'partial'
    error_msg    TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ingest_source ON ingestion_log (source, target_date DESC);
