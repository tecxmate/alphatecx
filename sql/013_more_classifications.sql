-- alphatecx v2 — Adopt Gemini's supply_chain_analysis.txt findings
--
-- Three new classifications surfaced by Gemini's volume-rank scan of
-- unclassified dim_ticker rows, validated by direct correlation against
-- 2330 TSMC and 2382 Quanta:
--
--   1815 Fulltech 富喬     infrastructure / pcb-materials  (NEW node)
--   2313 Compeq 華通      infrastructure / high-speed-pcb
--   3706 MiTAC 神達       infrastructure / server-odm
--
-- pcb-materials is a new node — it captures the upstream raw materials
-- tier (Low Dk glass fiber for CCL/CoWoS, etc) that we hadn't tagged.
-- 1815 is currently the sole occupant; expect to add 6213 ITEQ etc here
-- in future passes if the taxonomy proves useful.

INSERT INTO dim_ticker (ticker_id, company_name, market, ai_pillar, node, us_partners)
VALUES
    ('1815', 'Fulltech Fiber Glass', 'TWSE', 'infrastructure', 'pcb-materials',
        ARRAY['AWS', 'Google', 'Meta']),
    ('2313', 'Compeq Manufacturing',  'TWSE', 'infrastructure', 'high-speed-pcb',
        ARRAY['AWS', 'Google', 'Meta']),
    ('3706', 'MiTAC Holdings',        'TWSE', 'infrastructure', 'server-odm',
        ARRAY['Intel', 'Oracle', 'OpenAI', 'AWS'])
ON CONFLICT (ticker_id) DO UPDATE SET
    company_name = EXCLUDED.company_name,
    ai_pillar    = EXCLUDED.ai_pillar,
    node         = EXCLUDED.node,
    us_partners  = EXCLUDED.us_partners,
    updated_at   = now();
