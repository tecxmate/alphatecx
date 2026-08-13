#!/usr/bin/env python3
"""[DEPRECATED — historical record only, do not run.]

This was the v1 seeder for AI-supply-chain ticker classifications.
The authoritative source is now `dim_ticker` / `dim_supply_chain`,
managed via SQL migrations:

    sql/009_sc_revamp.sql         classifications + sc_edges
    sql/012_gemini_additions.sql  MediaTek 2454, MTI 2314, 8046 reclassify

Running this script would conflict with those migrations (it asserts an
older taxonomy with several wrong ticker codes — see audit at
docs/wiki/topics/supply-chain-audit-2026-05-10.md). The SUPPLY_CHAIN
list below is preserved as a record of the original Gemini-era
classification only.
"""

from __future__ import annotations

import logging

from src.harvester.loader import cur, log_ingestion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("seed")

# ── Known AI Supply Chain Map ───────────────────────────────────────────────
# Format: (ticker_id, company_name, market, ai_pillar, node, us_partners)

SUPPLY_CHAIN = [
    # === 1. Semiconductor: Foundry & Custom ASIC ===
    ("2330", "TSMC", "TWSE", "semiconductor", "advanced-foundry", ["NVIDIA", "AMD", "Apple", "Broadcom"]),
    ("2454", "MediaTek", "TWSE", "semiconductor", "ic-design", ["NVIDIA", "Arm"]),
    ("3661", "Alchip Technologies", "TWSE", "semiconductor", "asic-custom-ip", ["AWS", "Microsoft", "Intel"]),
    ("3443", "Global Unichip (GUC)", "TWSE", "semiconductor", "asic-custom-ip", ["AWS", "Microsoft"]),
    ("3035", "Faraday Technology", "TWSE", "semiconductor", "asic-custom-ip", ["Intel"]),
    ("3711", "ASE Technology", "TWSE", "semiconductor", "advanced-packaging", ["NVIDIA", "AMD"]),
    ("2408", "Nanya Technology", "TWSE", "semiconductor", "dram-memory", ["Kingston"]),
    # 2325 SPIL removed — acquired by ASE Technology (3711) in 2018, no longer publicly traded.

    # === 2. Semiconductor Equipment & Testing ===
    ("2449", "King Yuan Electronics (KYEC)", "TWSE", "equipment", "testing-probing", ["NVIDIA", "AMD", "Intel"]),
    ("6155", "Winway Technology", "TWSE", "equipment", "testing-probing", ["NVIDIA", "AMD"]),
    ("3664", "Marketech International", "TPEX", "equipment", "facility-cleanroom", ["Micron", "Applied Materials"]),
    ("2404", "United Integrated Services", "TWSE", "equipment", "facility-cleanroom", ["Micron"]),
    ("3583", "Scientech", "TWSE", "equipment", "equipment-materials", ["KLA", "Lam Research"]),
    ("6488", "GlobalWafers", "TPEX", "equipment", "equipment-materials", ["Texas Instruments"]),

    # === 3. AI Infrastructure: Servers, Cooling & Materials ===
    ("2382", "Quanta Computer", "TWSE", "infrastructure", "server-odm", ["Meta", "Google", "AWS", "Microsoft"]),
    ("3231", "Wistron", "TWSE", "infrastructure", "server-odm", ["Meta", "Google"]),
    ("2317", "Hon Hai (Foxconn)", "TWSE", "infrastructure", "server-odm", ["Apple", "NVIDIA", "AWS"]),
    ("3017", "Asia Vital Components (AVC)", "TWSE", "infrastructure", "thermal-cooling", ["NVIDIA", "Dell"]),
    ("3324", "Auras Technology", "TPEX", "infrastructure", "thermal-cooling", ["NVIDIA", "Supermicro"]),
    # 3553 Jentech Precision: TODO — code returns no data on TWSE/TPEX
    # OHLCV endpoints, and is absent from T86. Likely on Emerging Stock
    # Market (興櫃) which our fetcher doesn't cover, or the code is wrong.
    # Kept here as a known-incomplete entry; quant tools will skip it.
    ("3553", "Jentech Precision", "TPEX", "infrastructure", "thermal-cooling", ["HPE"]),
    ("2383", "Elite Material (EMC)", "TWSE", "infrastructure", "high-speed-pcb", ["Broadcom", "NVIDIA"]),
    ("8046", "Nan Ya PCB", "TWSE", "semiconductor", "ic-substrate", ["Intel", "AMD"]),
    ("3037", "Unimicron", "TWSE", "infrastructure", "high-speed-pcb", ["Broadcom", "Arista Networks"]),
    ("4958", "Zhen Ding Technology", "TWSE", "infrastructure", "high-speed-pcb", ["NVIDIA"]),
    ("2399", "Aspeed Technology", "TWSE", "infrastructure", "bmc-management", ["Dell", "HPE", "Supermicro"]),
    ("2345", "Accton Technology", "TWSE", "infrastructure", "network-switches", ["AWS", "Meta"]),
    ("2314", "MTI", "TWSE", "infrastructure", "network-communication", ["Dish Network"]),

    # === 4. AI Energy: Power Supplies & Grid Infrastructure ===
    ("2308", "Delta Electronics", "TWSE", "energy", "server-power-supply", ["Meta", "AWS"]),
    ("2301", "Lite-On Technology", "TWSE", "energy", "server-power-supply", ["Global Data Centers"]),
    ("1519", "Fortune Electric", "TWSE", "energy", "heavy-electrical", ["US Utility Companies", "Tesla"]),
    ("1560", "Chung-Hsin Electric", "TWSE", "energy", "heavy-electrical", ["US Utility Companies"]),
    ("6923", "HDRE", "TWSE", "energy", "green-energy", ["Google", "Microsoft"]),
]


def main():
    sql = """
        INSERT INTO dim_ticker (ticker_id, company_name, market,
                                ai_pillar, node, us_partners)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker_id) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            market = EXCLUDED.market,
            ai_pillar = EXCLUDED.ai_pillar,
            node = EXCLUDED.node,
            us_partners = EXCLUDED.us_partners,
            updated_at = now()
    """
    count = 0
    with cur() as c:
        for ticker_id, name, market, pillar, node, partners in SUPPLY_CHAIN:
            c.execute(sql, (ticker_id, name, market, pillar, node, partners))
            count += 1

    log.info("Seeded %d supply chain entries", count)
    log_ingestion("seed_supply_chain", None, count)


if __name__ == "__main__":
    main()
