-- alphatecx v2 — Adopt good ideas from Gemini's seed_supply_chain.py edits
-- See docs/wiki/log.md 2026-05-10 entry.
--
-- Three changes:
--   1. Add 2454 MediaTek (semiconductor / ic-design) — the major TW AI-chip
--      designer; was missing entirely from our classified universe.
--   2. Reclassify 8046 Nan Ya PCB from infrastructure/high-speed-pcb to
--      semiconductor/ic-substrate — Gemini's call is technically more
--      accurate (ABF substrates are chip-level interconnect, directly
--      upstream of advanced packaging, not board-level PCBs).
--   3. Add 2314 MTI (infrastructure / network-communication) — small TW
--      networking name, marginal AI exposure but useful for completeness.
--
-- 2383 EMC remains where 009 placed it (infrastructure/ccl-laminate);
-- our taxonomy is more granular than Gemini's lumped "high-speed-pcb".

BEGIN;

-- 1. MediaTek
INSERT INTO dim_ticker (ticker_id, company_name, market, ai_pillar, node, us_partners)
VALUES ('2454', 'MediaTek', 'TWSE', 'semiconductor', 'ic-design',
        ARRAY['NVIDIA', 'Arm', 'Meta'])
ON CONFLICT (ticker_id) DO UPDATE SET
    company_name = EXCLUDED.company_name,
    ai_pillar    = EXCLUDED.ai_pillar,
    node         = EXCLUDED.node,
    us_partners  = EXCLUDED.us_partners,
    updated_at   = now();

-- 2. Reclassify 8046 to semiconductor / ic-substrate
UPDATE dim_ticker
   SET ai_pillar = 'semiconductor',
       node      = 'ic-substrate',
       updated_at = now()
 WHERE ticker_id = '8046';

-- 3. MTI (2314)
INSERT INTO dim_ticker (ticker_id, company_name, market, ai_pillar, node, us_partners)
VALUES ('2314', 'MTI', 'TWSE', 'infrastructure', 'network-communication',
        ARRAY['Dish Network'])
ON CONFLICT (ticker_id) DO UPDATE SET
    company_name = EXCLUDED.company_name,
    ai_pillar    = EXCLUDED.ai_pillar,
    node         = EXCLUDED.node,
    us_partners  = EXCLUDED.us_partners,
    updated_at   = now();

COMMIT;
