-- alphatecx v2 — Unified universe view
--
-- One row per classified ticker, joining static knowledge (pillar/node/
-- US partners) with dynamic state (watchlist status, latest signals).
-- Watched names sort first. Underlying tables stay single-responsibility:
--   dim_ticker        = static curated knowledge
--   watchlist         = dynamic attention state (bot writes here)
--   view_latest_signals = computed indicator stack
-- This view is the read layer that pulls them together.

CREATE OR REPLACE VIEW view_universe AS
SELECT
    dt.ticker_id,
    dt.company_name,
    dt.market,
    dt.ai_pillar,
    dt.node,
    dt.us_partners,

    -- Watch state. LEFT JOIN with status='active' filter — null = unwatched.
    COALESCE(w.status, 'unwatched')   AS watch_status,
    w.reason                          AS watch_reason,
    w.escalation_trigger              AS watch_trigger,
    w.added_at                        AS watching_since,

    -- Latest signal stack (denormalised so one read returns everything).
    ls.as_of                          AS signals_as_of,
    ls.rsi_14,
    ls.macd_line,
    ls.macd_histogram,
    ls.bb_pct_b,
    ls.atr_14,
    ls.sma_50,
    ls.sma_200,
    ls.rs_vs_market_60,
    ls.pct_below_52w_high,
    ls.foreign_net_z20,
    ls.foreign_net_5d_sum,
    ls.total_net_z20

FROM dim_ticker dt
LEFT JOIN watchlist w
       ON w.ticker_id = dt.ticker_id AND w.status = 'active'
LEFT JOIN view_latest_signals ls
       ON ls.ticker_id = dt.ticker_id
WHERE dt.ai_pillar IS NOT NULL
ORDER BY
    CASE WHEN w.status = 'active' THEN 0 ELSE 1 END,  -- watched first
    dt.ai_pillar, dt.node, dt.ticker_id;
