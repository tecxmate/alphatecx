#!/usr/bin/env python3
"""Seed the curated AI-supply-chain ticker classifications into dim_ticker.

These are the companies from the strategic map (docs/wiki/topics/taiwan-ai-supply-chain.md).
Ticker codes are best-effort; verify against TWSE/TPEX.

Run: python -m src.seed_supply_chain
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
    ("3661", "Alchip Technologies", "TWSE", "semiconductor", "asic-custom-ip", ["AWS", "Microsoft", "Intel"]),
    ("3443", "Global Unichip (GUC)", "TWSE", "semiconductor", "asic-custom-ip", ["AWS", "Microsoft"]),
    ("3035", "Faraday Technology", "TWSE", "semiconductor", "asic-custom-ip", ["Intel"]),
    ("3711", "ASE Technology", "TWSE", "semiconductor", "advanced-packaging", ["NVIDIA", "AMD"]),
    ("2325", "SPIL", "TWSE", "semiconductor", "advanced-packaging", ["NVIDIA", "AMD"]),

    # === 2. Semiconductor Equipment & Testing ===
    ("2449", "King Yuan Electronics (KYEC)", "TWSE", "equipment", "testing-probing", ["NVIDIA", "AMD", "Intel"]),
    ("6155", "Winway Technology", "TPEX", "equipment", "testing-probing", ["NVIDIA", "AMD"]),
    ("3664", "Marketech International", "TWSE", "equipment", "facility-cleanroom", ["Micron", "Applied Materials"]),
    ("2404", "United Integrated Services", "TWSE", "equipment", "facility-cleanroom", ["Micron"]),
    ("3583", "Scientech", "TWSE", "equipment", "equipment-materials", ["KLA", "Lam Research"]),
    ("6488", "GlobalWafers", "TWSE", "equipment", "equipment-materials", ["Texas Instruments"]),

    # === 3. AI Infrastructure: Servers, Cooling & Materials ===
    ("2382", "Quanta Computer", "TWSE", "infrastructure", "server-odm", ["Meta", "Google", "AWS", "Microsoft"]),
    ("3231", "Wistron", "TWSE", "infrastructure", "server-odm", ["Meta", "Google"]),
    ("2317", "Hon Hai (Foxconn)", "TWSE", "infrastructure", "server-odm", ["Apple", "NVIDIA", "AWS"]),
    ("3017", "Asia Vital Components (AVC)", "TWSE", "infrastructure", "thermal-cooling", ["NVIDIA", "Dell"]),
    ("3324", "Auras Technology", "TPEX", "infrastructure", "thermal-cooling", ["NVIDIA", "Supermicro"]),
    ("3553", "Jentech Precision", "TPEX", "infrastructure", "thermal-cooling", ["HPE"]),
    ("8046", "Elite Material (EMC)", "TWSE", "infrastructure", "high-speed-pcb", ["Broadcom", "NVIDIA"]),
    ("3037", "Unimicron", "TWSE", "infrastructure", "high-speed-pcb", ["Broadcom", "Arista Networks"]),
    ("4958", "Zhen Ding Technology", "TWSE", "infrastructure", "high-speed-pcb", ["NVIDIA"]),
    ("2399", "Aspeed Technology", "TWSE", "infrastructure", "bmc-management", ["Dell", "HPE", "Supermicro"]),

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
