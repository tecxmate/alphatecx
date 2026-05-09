-- alphatecx v2 — Supply Chain Revamp (2026-05-10)
-- See docs/wiki/topics/supply-chain-audit-2026-05-10.md for rationale.
--
-- This migration:
--   1. Fixes 4 ticker-code errors in Gemini's seed (2399/6155/3553/6923)
--      by NULLing out their classification (preserves OHLCV history).
--   2. Reclassifies 6488 from equipment-materials → silicon-wafer.
--   3. Inserts/updates ~28 expansion tickers across new and existing nodes.
--   4. Creates the sc_edges table and seeds ~30 high-confidence edges.
--
-- Idempotent: safe to re-run. Uses INSERT ... ON CONFLICT for upserts.

BEGIN;

-- ────────────────────────────────────────────────────────────────────────────
-- 1. Audit corrections — NULL out misclassified entries
-- ────────────────────────────────────────────────────────────────────────────
-- These rows stay in dim_ticker (OHLCV history preserved) but drop out of
-- dim_supply_chain since ai_pillar IS NULL.

UPDATE dim_ticker
   SET ai_pillar = NULL, node = NULL, us_partners = NULL, updated_at = now()
 WHERE ticker_id IN (
   '2399',  -- BIOSTAR (motherboards) — Gemini wrote 2399 thinking it was Aspeed
   '6155',  -- Junpao (ferrite cores) — Gemini wrote 6155 thinking it was WinWay
   '3553',  -- (no data on TWSE/TPEX) — Gemini wrote 3553 thinking it was Jentech
   '6923'   -- 中台 (refractories) — Gemini labeled this "HDRE" which doesn't exist
);

-- ────────────────────────────────────────────────────────────────────────────
-- 2. Reclassify 6488 GlobalWafers
-- ────────────────────────────────────────────────────────────────────────────
UPDATE dim_ticker
   SET ai_pillar = 'semiconductor', node = 'silicon-wafer', updated_at = now()
 WHERE ticker_id = '6488';

-- ────────────────────────────────────────────────────────────────────────────
-- 3. Expansion tickers — UPSERT
-- ────────────────────────────────────────────────────────────────────────────
-- (ticker_id, company_name, market, ai_pillar, node, us_partners)
INSERT INTO dim_ticker (ticker_id, company_name, market, ai_pillar, node, us_partners)
VALUES
    -- Corrected versions of the four bogus seeds (now with the right codes)
    ('5274', 'Aspeed Technology',         'TPEX', 'infrastructure', 'bmc-management',     ARRAY['Dell','HPE','Supermicro','Lenovo','Inspur']),
    ('6515', 'WinWay Technology',         'TPEX', 'equipment',      'testing-probing',    ARRAY['NVIDIA','AMD']),
    ('3653', 'Jentech Precision',         'TPEX', 'infrastructure', 'thermal-cooling',    ARRAY['HPE']),
    ('3576', 'United Renewable Energy',   'TWSE', 'energy',         'green-energy',       ARRAY['Google']),

    -- Server ODMs
    ('6669', 'Wiwynn',                    'TWSE', 'infrastructure', 'server-odm',         ARRAY['Meta','Microsoft']),
    ('2356', 'Inventec',                  'TWSE', 'infrastructure', 'server-odm',         ARRAY['AWS','HPE']),

    -- Networking & connectors
    ('2345', 'Accton Technology',         'TWSE', 'infrastructure', 'networking-switch',  ARRAY['Meta','Microsoft','Cisco']),
    ('3533', 'Lotes',                     'TWSE', 'infrastructure', 'connectors-cables',  ARRAY['NVIDIA','Intel','AMD']),
    ('3665', 'BizLink',                   'TWSE', 'infrastructure', 'connectors-cables',  ARRAY['NVIDIA','Tesla']),

    -- Optical / CPO
    ('3081', 'LandMark Optoelectronics',  'TPEX', 'infrastructure', 'optical-cpo',        ARRAY['Lumentum','Coherent']),
    ('3450', 'Luxnet',                    'TPEX', 'infrastructure', 'optical-cpo',        ARRAY['various']),
    ('3363', 'Foci Fiber Optic',          'TPEX', 'infrastructure', 'optical-cpo',        ARRAY['various']),

    -- CCL (copper-clad laminate) — new node
    ('6213', 'ITEQ',                      'TPEX', 'infrastructure', 'ccl-laminate',       ARRAY['NVIDIA-via-PCB']),
    ('6274', 'Taiwan Union Technology',   'TPEX', 'infrastructure', 'ccl-laminate',       ARRAY['NVIDIA-via-PCB','Broadcom-via-PCB']),
    ('2383', 'Elite Material',            'TWSE', 'infrastructure', 'ccl-laminate',       ARRAY['NVIDIA-via-PCB','Meta-via-PCB']),
    -- Note: 8046 in DB had label "Elite Material (EMC)" but 8046 is actually Nan Ya PCB.
    -- Fix that name too.

    -- IC substrate (third leg)
    ('3189', 'Kinsus Interconnect',       'TWSE', 'infrastructure', 'high-speed-pcb',     ARRAY['Intel','AMD']),

    -- Memory
    ('2408', 'Nanya Technology',          'TWSE', 'semiconductor',  'memory-dram',        ARRAY['edge-AI','data-center']),
    ('2344', 'Winbond Electronics',       'TWSE', 'semiconductor',  'memory-dram',        ARRAY['auto','AI-PC']),
    ('2337', 'Macronix International',    'TWSE', 'semiconductor',  'memory-flash',       ARRAY['industrial','auto']),

    -- Mature foundry
    ('5347', 'Vanguard International',    'TWSE', 'semiconductor',  'mature-foundry',     ARRAY['TI','NXP']),

    -- Additional ASIC IP
    ('8261', 'eMemory Technology',        'TPEX', 'semiconductor',  'asic-custom-ip',     ARRAY['TSMC-IP-licensees']),

    -- Testing / equipment
    ('6147', 'King Yuan Electronics',     'TWSE', 'equipment',      'testing-probing',    ARRAY['NVIDIA','AMD','Qualcomm']),
    ('6223', 'MPI Corporation',           'TPEX', 'equipment',      'testing-probing',    ARRAY['IDMs']),
    ('3535', 'Chroma ATE',                'TWSE', 'equipment',      'testing-probing',    ARRAY['Tesla','NVIDIA']),
    ('3680', 'Gudeng Precision',          'TPEX', 'equipment',      'equipment-materials',ARRAY['ASML','TSMC']),
    ('5536', 'Acter',                     'TPEX', 'equipment',      'facility-cleanroom', ARRAY['TSMC','Micron']),
    ('6125', 'Kenmec Mechanical',         'TWSE', 'equipment',      'equipment-materials',ARRAY['TSMC','Samsung']),

    -- Heavy electrical
    ('1503', 'Shihlin Electric',          'TWSE', 'energy',         'heavy-electrical',   ARRAY['TPC','US-utilities'])
ON CONFLICT (ticker_id) DO UPDATE SET
    company_name = EXCLUDED.company_name,
    market       = EXCLUDED.market,
    ai_pillar    = EXCLUDED.ai_pillar,
    node         = EXCLUDED.node,
    us_partners  = EXCLUDED.us_partners,
    updated_at   = now();

-- Fix wrong company_name on 8046 (it's Nan Ya PCB, not "Elite Material")
UPDATE dim_ticker
   SET company_name = 'Nan Ya Printed Circuit Board', updated_at = now()
 WHERE ticker_id = '8046';

-- ────────────────────────────────────────────────────────────────────────────
-- 4. sc_edges — explicit supplier→customer relationships
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sc_edges (
    edge_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    upstream_id      TEXT NOT NULL REFERENCES dim_ticker(ticker_id),
    downstream_id    TEXT NOT NULL REFERENCES dim_ticker(ticker_id),
    relationship     TEXT NOT NULL DEFAULT 'supplies',  -- 'supplies' | 'partners-with' | 'competes-with'
    strength         REAL DEFAULT 1.0,
    source           TEXT,
    confidence       TEXT NOT NULL DEFAULT 'medium',    -- 'high' | 'medium' | 'low'
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (upstream_id, downstream_id, relationship)
);
CREATE INDEX IF NOT EXISTS idx_sc_edges_up   ON sc_edges (upstream_id);
CREATE INDEX IF NOT EXISTS idx_sc_edges_down ON sc_edges (downstream_id);

-- Seed high-confidence edges
INSERT INTO sc_edges (upstream_id, downstream_id, relationship, confidence, source) VALUES
    -- Foundry → packaging / ASIC
    ('2330','3711','supplies','high','TSMC fabs wafers ASE packages — public'),
    ('2330','3661','supplies','high','TSMC foundry → Alchip ASIC'),
    ('2330','3443','supplies','high','TSMC foundry → GUC ASIC'),
    ('2330','3035','supplies','high','TSMC foundry → Faraday ASIC'),
    ('2330','5274','supplies','high','TSMC fabs Aspeed BMC'),
    ('2330','8261','partners-with','high','TSMC IP partner via eMemory'),

    -- Substrate → foundry/packager
    ('3037','2330','supplies','high','Unimicron substrates → TSMC'),
    ('8046','2330','supplies','high','Nan Ya PCB substrates → TSMC'),
    ('4958','2330','supplies','high','Zhen Ding substrates → TSMC'),
    ('3189','2330','supplies','medium','Kinsus IC substrate → TSMC'),

    -- Silicon wafer → foundry
    ('6488','2330','supplies','high','GlobalWafers silicon → TSMC'),

    -- Packaging → ODM
    ('3711','2317','supplies','high','ASE packaged chip → Hon Hai'),
    ('3711','2382','supplies','high','ASE → Quanta'),
    ('3711','6669','supplies','high','ASE → Wiwynn'),
    ('3711','3231','supplies','high','ASE → Wistron'),

    -- PSU → ODM
    ('2308','2382','supplies','high','Delta PSU → Quanta'),
    ('2308','6669','supplies','high','Delta PSU → Wiwynn'),
    ('2301','2317','supplies','high','LiteOn PSU → Hon Hai'),

    -- Cooling → ODM
    ('3017','2382','supplies','high','AVC cooling → Quanta'),
    ('3017','6669','supplies','high','AVC cooling → Wiwynn'),
    ('3324','2382','supplies','high','Auras cooling → Quanta'),
    ('3324','6669','supplies','high','Auras cooling → Wiwynn'),
    ('3653','2382','supplies','medium','Jentech thermal → ODM'),

    -- CCL → PCB
    ('2383','3037','supplies','high','EMC CCL → Unimicron'),
    ('6213','3037','supplies','medium','ITEQ CCL → Unimicron'),
    ('6274','8046','supplies','medium','Taiwan Union CCL → Nan Ya PCB'),

    -- Connectors → ODM
    ('3533','2382','supplies','high','Lotes sockets → Quanta'),
    ('3533','6669','supplies','high','Lotes sockets → Wiwynn'),
    ('3665','6669','supplies','medium','BizLink cables → Wiwynn'),
    ('3665','2382','supplies','medium','BizLink cables → Quanta'),

    -- Equipment / facility → foundry
    ('3680','2330','supplies','high','Gudeng EUV pods → TSMC'),
    ('2404','2330','partners-with','high','HanTang cleanroom → TSMC'),
    ('3664','2330','partners-with','medium','Marketech cleanroom'),
    ('5536','2330','partners-with','medium','Acter cleanroom → TSMC'),

    -- Heavy electrical → fab/grid
    ('1519','2330','partners-with','medium','Fortune Electric → TSMC fab power'),
    ('1503','2330','partners-with','medium','Shihlin Electric → fab power')
ON CONFLICT (upstream_id, downstream_id, relationship) DO NOTHING;

COMMIT;
