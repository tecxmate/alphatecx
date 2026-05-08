-- alphatecx v2 — Watchlist (Phase 3.5)
--
-- Names being actively monitored but not yet at thesis stage. Source of
-- truth is this table; briefs + MCP read from here; the Telegram bot
-- writes here. The previous docs/watchlist/active.md file is replaced
-- by this table — no on-disk mirror, simpler architecture.
--
-- Lifecycle (per docs/watchlist/README.md): names should escalate to
-- thesis or get dropped within ~5 trading days. status='active'
-- captures live entries; 'archived' is for historical record.

CREATE TABLE IF NOT EXISTS watchlist (
    ticker_id           TEXT PRIMARY KEY,
    company_name        TEXT NOT NULL,         -- denormalised from dim_supply_chain at add-time
    ai_pillar           TEXT,
    node                TEXT,
    reason              TEXT,                  -- one-line free-form
    escalation_trigger  TEXT,                  -- specific data condition that promotes to thesis
    added_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    status              TEXT NOT NULL DEFAULT 'active'  -- 'active' | 'archived'
);

CREATE INDEX IF NOT EXISTS idx_watchlist_status_added
    ON watchlist (status, added_at DESC);

-- ============================================================================
-- Seed: migrate the two rows currently in docs/watchlist/active.md
-- ============================================================================

INSERT INTO watchlist (ticker_id, company_name, ai_pillar, node,
                       reason, escalation_trigger, added_at)
VALUES
  ('6488', 'GlobalWafers', 'equipment', 'equipment-materials',
   'foreign_z = +4.25 (5d cum +9.24M shares), at 52w high, RSI 77, BB %B 1.08. But total_net_z20 = -4.25 — foreigners buying at extremes while domestic trust+dealer net sells. Mixed institutional read.',
   'If foreign_z stays > 1.5 for 2 more sessions OR domestic flow flips positive → run decide-on-ticker',
   '2026-05-08 12:00:00+00'),
  ('3324', 'Auras Technology', 'infrastructure', 'thermal-cooling',
   'foreign_z = +4.25 today, but 5d cum is still -2.96M (today was a sharp reversal). RSI 49, 12.3% off 52w high, total_net_z20 = +4.25 (all institutions aligned today). Possible accumulation start after weakness.',
   'Confirmation needed: another foreign net-buy day in next 3 sessions AND price reclaims SMA-50 (1041) → run decide-on-ticker',
   '2026-05-08 12:00:00+00')
ON CONFLICT (ticker_id) DO NOTHING;
