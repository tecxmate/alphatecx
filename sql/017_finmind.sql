-- alphatecx v2 — FinMind enrichment (Tool Review v2 Phase 2)
--
-- Wires three FinMind (finmind.github.io, free tier) datasets into Neon so the
-- flow_leaders_scan enrichment can answer questions TWSE-native data can't:
--   * cash vs stock dividend split (v2 #1 full)  → raw_finmind_dividend
--   * 填息 (dividend gap-refill) probability (v2 #2) → raw_finmind_dividend_result
--       + finmind_fill_stats (precomputed fill_probability_5y)
--   * material / governance news overlay (v2 #4)  → raw_finmind_news
--
-- The MCP read path never calls FinMind (600 req/hr, latency); a nightly
-- harvester loads these tables and the scanner reads from Neon.

-- ── Dividend policy: cash / stock split per year ────────────────────────────
-- FinMind TaiwanStockDividend. cash_dividend = CashEarningsDistribution +
-- CashStatutorySurplus; stock_dividend = StockEarningsDistribution +
-- StockStatutorySurplus. cash_ex_date / stock_ex_date are the per-leg ex trading
-- dates (a name can pay cash and stock on different days).
CREATE TABLE IF NOT EXISTS raw_finmind_dividend (
    ticker_id        TEXT NOT NULL,
    year             INTEGER NOT NULL,        -- dividend fiscal year (Gregorian)
    cash_dividend    REAL,                    -- 元/股
    stock_dividend   REAL,                    -- 元/股 (面額10 → shares = /10)
    cash_ex_date     DATE,
    stock_ex_date    DATE,
    announcement_date DATE,
    source           TEXT NOT NULL DEFAULT 'finmind',
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker_id, year)
);
CREATE INDEX IF NOT EXISTS idx_fm_div_ticker ON raw_finmind_dividend (ticker_id, year DESC);

-- ── Dividend result: one row per ex event, for 填息 history ──────────────────
-- FinMind TaiwanStockDividendResult. A dividend "fills" (填息) when the price
-- recovers to the pre-ex close; `max_price` is the post-ex high within the
-- result window, so filled ⇔ max_price >= before_price.
CREATE TABLE IF NOT EXISTS raw_finmind_dividend_result (
    ticker_id        TEXT NOT NULL,
    ex_date          DATE NOT NULL,
    before_price     REAL,                    -- 除權息前收盤
    after_price      REAL,                    -- 除權息參考價 (open of ex day basis)
    reference_price  REAL,
    max_price        REAL,                    -- post-ex high in the result window
    min_price        REAL,
    source           TEXT NOT NULL DEFAULT 'finmind',
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker_id, ex_date)
);
CREATE INDEX IF NOT EXISTS idx_fm_divres_ticker ON raw_finmind_dividend_result (ticker_id, ex_date DESC);

-- ── Precomputed 填息 probability per ticker ─────────────────────────────────
-- Derived nightly from raw_finmind_dividend_result over the trailing 5 years by
-- the loader's pure fill_probability(); stored so the scan is a cheap join and
-- the definition lives in one tested place (src/harvester/finmind.fill_probability).
CREATE TABLE IF NOT EXISTS finmind_fill_stats (
    ticker_id          TEXT PRIMARY KEY,
    fill_probability_5y REAL,                 -- 0..1, NULL if no events in window
    events_5y          INTEGER NOT NULL DEFAULT 0,
    last_ex_date       DATE,
    computed_as_of     DATE,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Material / governance news ──────────────────────────────────────────────
-- FinMind TaiwanStockNews. `is_governance` is set at load time when the title
-- matches the governance-risk watchlist (洗錢/掏空/內線/財報不實/下市/違約交割/
-- 搜索/起訴) — surfaced for human judgement, never auto-downgrades triage.
CREATE TABLE IF NOT EXISTS raw_finmind_news (
    ticker_id     TEXT NOT NULL,
    news_date     DATE NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    title_hash    TEXT NOT NULL,              -- md5(title), for a stable PK
    news_source   TEXT,
    url           TEXT,
    is_governance BOOLEAN NOT NULL DEFAULT false,
    source        TEXT NOT NULL DEFAULT 'finmind',
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker_id, news_date, title_hash)
);
CREATE INDEX IF NOT EXISTS idx_fm_news_ticker ON raw_finmind_news (ticker_id, news_date DESC);

-- ── Read access for the MCP read-only role (see sql/003_rls.sql), guarded ────
DO $$
DECLARE t TEXT;
BEGIN
  IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer') THEN
    FOREACH t IN ARRAY ARRAY['raw_finmind_dividend', 'raw_finmind_dividend_result',
                             'finmind_fill_stats', 'raw_finmind_news'] LOOP
      EXECUTE format('GRANT SELECT ON %I TO mcp_viewer', t);
      EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('DROP POLICY IF EXISTS "mcp_viewer_read_%s" ON %I', t, t);
      EXECUTE format('CREATE POLICY "mcp_viewer_read_%s" ON %I '
                     'FOR SELECT TO mcp_viewer USING (true)', t, t);
    END LOOP;
  END IF;
END $$;
