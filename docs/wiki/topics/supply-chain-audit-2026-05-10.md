---
title: Supply Chain Audit & Expansion Proposal — May 2026
type: topic
slug: supply-chain-audit-2026-05-10
date: 2026-05-10
updated: 2026-05-10
attributed_to: [claude-code]
belongs_to: [taiwan-ai-supply-chain]
source: chat
status: proposed
tags: [supply-chain, audit, expansion, classification]
related: [taiwan-ai-supply-chain, alphatecx]
---

# Supply Chain Audit & Expansion Proposal

Triggered by: user request 2026-05-10 — "my supply chain is not well mapped out yet, can you help me improve on that?" Scope: audit the 26 classified tickers from Gemini's v2 seeding, propose corrections, propose ~50 expansion candidates with sourcing, and propose a `sc_edges` schema for explicit supplier→customer links.

---

## Part 1 — Audit of existing 26 (corrections needed)

### Critical: misclassifications to fix

| Ticker | Current | Issue | Proposed |
|---|---|---|---|
| **2399 BIOSTAR** | infrastructure / bmc-management | BIOSTAR is a motherboard / IPC manufacturer (PCs, AI workstations, EV chargers). NOT a BMC chip vendor. Partner list (Dell/HPE/Supermicro) is fabricated. | **REMOVE** from supply chain. Replace with **5274 信驊 ASPEED** (TPEX) — the actual TW BMC fabless IC designer (BMC, KVM-over-IP). Dominant share in server BMC; real customers include Dell, HPE, Supermicro, Inspur, Lenovo. |
| **6155 鈞寶 Junpao** | equipment / testing-probing | Junpao makes ferrite cores and EMI suppression passives (chip beads, precision coils). NOT testing-probing. | **REMOVE** from this node. Optionally reclassify under a new `passive-components` node, but I'd recommend just removing — passives aren't a high-conviction AI-supply-chain story. |
| **6923 中台 Zhongtai** | energy / green-energy | 中台資源 is a small refractories/recycling company. The Google/Microsoft partner attribution looks fabricated; no public evidence of a data-center renewable-PPA relationship. | **REMOVE**. If a green-energy DC ticker is wanted, candidates are 3576 URE (the ticker Google literally bought a stake in for TW renewables). |

### Verify-before-trusting (lower priority)

| Ticker | Current | Note |
|---|---|---|
| **3553 Jentech** | infrastructure / thermal-cooling | Need to verify — `company_name` shows English string, not 中文 like the rest. May be a typo of 矽格 6257 or another name. Also "HPE" partner is unusual for a TW thermal vendor — typical thermal customers are NVIDIA/Supermicro. |
| **3035 智原 Faraday** | semiconductor / asic-custom-ip | Real but partner list says "Intel" — Faraday's main customer base is Asia/diversified, less Intel-centric than 3661 Alchip or 3443 GUC. Cosmetic, not wrong. |
| **6488 環球晶 GlobalWafers** | equipment / equipment-materials | This is a SILICON WAFER maker, not equipment. Should be **`semiconductor` / `silicon-wafer`** instead. Partner is real (TI, also Micron, Infineon). |

### Coverage gaps in existing nodes

| Node | Current | Notable missing |
|---|---|---|
| advanced-foundry | 2330 only | OK as-is (TSMC has 95%+ leading-edge share). But **8261 力旺 eMemory** (IP) and **5347 Vanguard 世界先進** (mature foundry) often co-move with TSMC. |
| advanced-packaging | 3711 ASE only | **6147 King Yuan 京元電** (testing) is in but no other ATM. **2329 華泰 Orient Semi** (ATM) and **8081 致新 GMT** are smaller but real. |
| asic-custom-ip | 3035, 3443, 3661 | Solid. **6573 Faraday-related** N/A. Could add **8016 矽創 Sitronix** (display driver IC) — adjacent. |
| testing-probing | 2449 only (after Junpao removal) | **6147 King Yuan**, **6531 Aspeed-related** N/A; real probe-card name is **6223 旺矽 MPI**. **3535 Chroma 致茂** (test instruments). |
| equipment-materials | 6488 → moves to silicon-wafer; 3583 only | **5536 聖暉 Acter** (cleanroom), **3680 家登 Gudeng** (EUV pod), **6125 廣運 Kenmec** (semi automation). |
| facility-cleanroom | 2404, 3664 | Reasonable. **5536 Acter** could also fit here. |
| high-speed-pcb | 3037, 4958, 8046 | Strong already. Add **3189 Kinsus 景碩** (IC substrate, third leg with Unimicron/Nan Ya PCB), **6669 Wiwynn 緯穎** is a server ODM not PCB — keep separate. |
| server-odm | 2317, 2382, 3231 | Missing **6669 Wiwynn** (THE pure-play AI server ODM, Meta/Microsoft) and **2356 Inventec 英業達** (Tier-2 ODM, AWS). |
| thermal-cooling | 3017, 3324, 3553(?) | Could add **6285 Asia Vital 元山** (small) and **3413 京鼼 Jingyou** N/A. Existing three are right names. |
| bmc-management | (after fix) 5274 only | OK. BMC is concentrated. |
| server-power-supply | 2301, 2308 | **6669 N/A**. **6803 ABF Group** N/A. Existing two are correct. |
| heavy-electrical | 1519, 1560 | **1503 中興電 Shihlin Electric** is the other major TW switchgear/transformer name. |
| green-energy | (after fix) — | Add **3576 URE 聯合再生** (Google-invested) if user wants this node populated. Otherwise drop the node. |

---

## Part 2 — Expansion proposal: ~50 new tickers

Organized by **proposed new pillar/node structure** (some new nodes added). Each entry: ticker, company, ai_pillar, node, us_partners (most-cited only), source.

### New nodes proposed

- `semiconductor` / `silicon-wafer` (move 6488 here)
- `semiconductor` / `memory-dram` (NEW)
- `semiconductor` / `memory-flash` (NEW)
- `semiconductor` / `mature-foundry` (NEW)
- `semiconductor` / `power-semi` (NEW)
- `infrastructure` / `networking-switch` (NEW)
- `infrastructure` / `optical-cpo` (NEW)
- `infrastructure` / `connectors-cables` (NEW)
- `infrastructure` / `ccl-laminate` (NEW — currently buried)

### Proposed expansion tickers (high-conviction, sourced)

| Ticker | Company | Pillar / Node | US Partners | Notes / Source |
|---|---|---|---|---|
| **5274** | 信驊 ASPEED | infrastructure / bmc-management | NVIDIA, Dell, HPE, Supermicro, Lenovo | Dominant TW BMC fabless. Replaces 2399. |
| **6669** | 緯穎 Wiwynn | infrastructure / server-odm | Meta, Microsoft | Pure-play AI/hyperscale server ODM. Spun out of Wistron. |
| **2356** | 英業達 Inventec | infrastructure / server-odm | AWS, HPE | Tier-2 ODM, growing AI-server share. |
| **2345** | 智邦 Accton | infrastructure / networking-switch | Meta, Microsoft, Cisco | 100/400/800G switches for hyperscalers. White-box leader. |
| **3033** | 威健 Weikeng | infrastructure / networking-switch | various | Distributor — skip unless we want context. **Drop.** |
| **6285** | 啟碁 Sercomm | infrastructure / networking-switch | various carriers | Mostly CPE/edge, marginal AI fit. **Optional.** |
| **3665** | BizLink | infrastructure / connectors-cables | NVIDIA (DGX cabling), Tesla | DAC/AOC cables, CPO entrant via SENKO/ficonTEC partnership (Sep 2025). |
| **3533** | 嘉澤 Lotes | infrastructure / connectors-cables | NVIDIA, Intel, AMD | CPU/GPU socket connectors — every Xeon/EPYC socket. |
| **6803** | 崇越 N/A | — | — | Skip. |
| **3081** | 聯亞 LandMark Optoelectronics | infrastructure / optical-cpo | Lumentum, Coherent | Epi-wafers for VCSEL/datacom optics. |
| **3450** | 聯鈞 Luxnet | infrastructure / optical-cpo | various optical-module makers | Optical components. |
| **3363** | 上詮 Foci Fiber | infrastructure / optical-cpo | various | Optical transceivers/components. |
| **6213** | ITEQ 聯茂 | infrastructure / ccl-laminate | indirect (NVIDIA via PCB chain) | Top-3 TW CCL maker. AI-server CCL boom. |
| **6274** | 台燿 Taiwan Union Tech | infrastructure / ccl-laminate | indirect (NVIDIA, Broadcom) | Top-3 TW CCL maker, Oct 2025 record revenue +40% YoY. |
| **2383** | 台光電 EMC | infrastructure / ccl-laminate | indirect (NVIDIA, Meta) | THE high-end CCL maker for AI servers. M6/M7/M8 grades. |
| **3189** | 景碩 Kinsus | infrastructure / high-speed-pcb | Intel, AMD | IC substrate (third leg with 3037/8046). |
| **2408** | 南亞科 Nanya Tech | semiconductor / memory-dram | (commodity) | DDR4/5 DRAM. Custom HBM for edge AI starting late 2026 (per TrendForce). |
| **2344** | 華邦電 Winbond | semiconductor / memory-dram | (auto, edge AI) | Specialty DRAM, mobile/auto/AI-PC. |
| **2337** | 旺宏 Macronix | semiconductor / memory-flash | (industrial, auto) | NOR Flash leader. Less AI-server but real semis exposure. |
| **5347** | 世界先進 Vanguard | semiconductor / mature-foundry | TI, NXP | Mature-node foundry, TSMC affiliate. |
| **8261** | 力旺 eMemory | semiconductor / asic-custom-ip | TSMC IP-licensee customers | NeoFuse / NeoBit IP. Pure-play IP. |
| **6147** | 京元電 King Yuan Elec | equipment / testing-probing | NVIDIA, AMD, Qualcomm | THE TW back-end testing house for AI silicon. (Distinct from 2449 京元電子.) |
| **6223** | 旺矽 MPI | equipment / testing-probing | various IDMs | Probe cards & analytical probers. |
| **3535** | 致茂 Chroma | equipment / testing-probing | Tesla, NVIDIA | Test instruments — auto/EV mostly, AI cooling/power test secondary. |
| **3680** | 家登 Gudeng | equipment / equipment-materials | ASML, TSMC | EUV pods — moat-y. |
| **5536** | 聖暉 Acter | equipment / facility-cleanroom | TSMC, Micron | Cleanroom integrator. |
| **6125** | 廣運 Kenmec | equipment / equipment-materials | TSMC, Samsung | Wafer-handling automation. |
| **1503** | 中興電 Shihlin | energy / heavy-electrical | TPC, US utilities | Switchgear/transformers for grid + DC. |
| **3576** | 聯合再生 URE | energy / green-energy | Google (equity stake) | Solar, Google bought minority stake for TW renewables. |

**Bonus context tickers (for graph background, not classification — TWSE's most-traded large caps):** 2412 中華電 (telco), 2882 國泰金 (financial), 1101 台泥 (cement), 1303 南亞 (plastics), 2002 中鋼 (steel), 1216 統一 (consumer), 2891 中信金, 2884 玉山金 — these go into the OHLCV backfill but stay `ai_pillar=NULL` so the graph shows them as a grey background cluster, contrasting against the AI ecosystem.

**Final classified target:** 26 existing − 3 removals (2399, 6155, 6923) + 1 reclassify (6488 to silicon-wafer) + ~25 expansion = **~48 classified tickers**, plus ~150 grey context names = **~200 tickers in OHLCV backfill**.

---

## Part 3 — `sc_edges` schema proposal

Right now we have pillar/node tags (categorical) but no explicit supplier→customer relationships. For the 3D graph, we want edges to draw real supply links — e.g., 2330 → 3711 (TSMC fabs → ASE packages), 3037 → 2330 (Unimicron substrates → TSMC).

### Schema (new file: `sql/009_sc_edges.sql`)

```sql
CREATE TABLE IF NOT EXISTS sc_edges (
    edge_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    upstream_id      TEXT NOT NULL REFERENCES dim_ticker(ticker_id),  -- supplier
    downstream_id    TEXT NOT NULL REFERENCES dim_ticker(ticker_id),  -- customer
    relationship     TEXT NOT NULL DEFAULT 'supplies',  -- 'supplies', 'partners-with', 'competes-with'
    strength         REAL DEFAULT 1.0,  -- 0..1, optional weighting (% of revenue, materiality)
    source           TEXT,              -- citation (URL, doc, "user-asserted")
    confidence       TEXT NOT NULL DEFAULT 'medium',  -- 'high', 'medium', 'low'
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (upstream_id, downstream_id, relationship)
);
CREATE INDEX IF NOT EXISTS idx_sc_edges_up   ON sc_edges (upstream_id);
CREATE INDEX IF NOT EXISTS idx_sc_edges_down ON sc_edges (downstream_id);
```

### Seed (the obvious ~30 high-confidence edges)

```
2330 (TSMC) ──supplies──> 3711 (ASE)               # foundry → packaging
2330 (TSMC) ──supplies──> 3661 (Alchip)            # foundry → ASIC
2330 (TSMC) ──supplies──> 3443 (GUC)               # foundry → ASIC
2330 (TSMC) ──supplies──> 3035 (Faraday)           # foundry → ASIC
3037 (Unimicron) ──supplies──> 2330 (TSMC)         # substrate → foundry
8046 (Nan Ya PCB) ──supplies──> 2330 (TSMC)
4958 (Zhen Ding) ──supplies──> 2330 (TSMC)
3189 (Kinsus) ──supplies──> 2330 (TSMC)
6488 (GlobalWafers) ──supplies──> 2330 (TSMC)      # silicon → foundry
3680 (Gudeng) ──supplies──> 2330 (TSMC)            # EUV pods
3711 (ASE) ──supplies──> 2317 (Hon Hai)            # packaged chip → ODM
3711 (ASE) ──supplies──> 2382 (Quanta)
3711 (ASE) ──supplies──> 6669 (Wiwynn)
2330 (TSMC) ──supplies──> 5274 (Aspeed)            # foundry → BMC
2308 (Delta) ──supplies──> 2382 (Quanta)           # PSU → ODM
2308 (Delta) ──supplies──> 6669 (Wiwynn)
2301 (LiteOn) ──supplies──> 2317 (Hon Hai)
3017 (AVC) ──supplies──> 2382 (Quanta)             # cooling → ODM
3017 (AVC) ──supplies──> 6669 (Wiwynn)
3324 (Auras) ──supplies──> 2382 (Quanta)
3324 (Auras) ──supplies──> 6669 (Wiwynn)
2383 (EMC) ──supplies──> 3037 (Unimicron)          # CCL → PCB
6213 (ITEQ) ──supplies──> 3037 (Unimicron)
6274 (Taiwan Union) ──supplies──> 8046 (Nan Ya PCB)
3533 (Lotes) ──supplies──> 2382 (Quanta)           # connectors → ODM
3533 (Lotes) ──supplies──> 6669 (Wiwynn)
3665 (BizLink) ──supplies──> 6669 (Wiwynn)         # cables → ODM
2345 (Accton) ──supplies──> [meta, microsoft]      # leaves the TW universe
1519 (Hua Eng) ──partners-with──> 2330 (TSMC)      # heavy electrical for fabs
1503 (Shihlin) ──partners-with──> 2330 (TSMC)
2404 (HanTang) ──partners-with──> 2330 (TSMC)      # cleanroom for fabs
3664 (AnRui) ──partners-with──> 2330 (TSMC)
```

(Some destinations are non-TW US partners — those don't need rows in `sc_edges` since both endpoints must be in `dim_ticker`. They're already captured in `us_partners` array.)

### Why this schema

- One row per directional edge keeps queries simple.
- `strength` lets us later weight edges by revenue concentration if we ever get that granularity.
- `confidence` distinguishes "publicly disclosed customer" (high) vs "industry-known but not company-confirmed" (medium) vs "speculative" (low). I'd seed conservative — only 'high' for the obvious foundry/packaging/PCB chain.
- `source` is a free-text citation field. Ideally a URL.
- Unique constraint prevents duplicates if we re-seed.

---

## Part 4 — What I propose to do next (pending user sign-off)

1. Write `sql/009_sc_edges.sql` (schema + seed) and apply it.
2. Apply DB updates: remove 3 misclassified, reclassify 6488, insert ~25 new classified tickers (with `us_partners`).
3. Add ~150 context tickers to `dim_ticker` with `ai_pillar=NULL` so they appear in the OHLCV target list but stay grey in the graph.
4. Modify `src/backfill/run.py:_ohlcv_targets()` to read from `dim_ticker` (any row) instead of just classified — or alternatively pull the full TWSE/TPEX listing.
5. Run a 3-month OHLCV backfill (~30 min, ~200 × 3 monthly fetches).
6. Then proceed to: correlation snapshot pipeline → /graph viewer → discovery query.

**Ask:** approve the audit corrections (remove 2399 / 6155 / 6923), the reclassification (6488 → silicon-wafer), the ~25 expansion tickers, and the `sc_edges` schema. Once approved, I'll execute and move to the graph build.
