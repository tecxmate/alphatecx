---
title: Taiwan AI Supply Chain Map
type: topic
slug: taiwan-ai-supply-chain
date: 2026-05-07
updated: 2026-05-07
belongs_to: [niko]
source: chat
status: active
tags: [strategy, supply-chain, semiconductor, ai-infrastructure, ai-energy]
related: [alphatecx, system-architecture]
---

## Summary

A comprehensive mapping of Taiwan's AI supply chain across 4 pillars, linking Taiwanese companies to their US customers and identifying strategic catalysts. This map is the strategic backbone of alphatecx — it defines which sectors and tickers to track, and how to interpret institutional flows.

## The 4 Pillars

### 1. Semiconductor: Foundry & Custom ASIC

| Node | Key TW Companies | US Customers | Catalyst |
|------|-------------------|--------------|----------|
| Advanced Foundry | TSMC | NVIDIA, AMD, Apple, Broadcom | ~30% sales growth 2026; watch monthly revenue (10th) |
| ASIC / Custom IP | Alchip, GUC, Faraday | AWS (Trainium), Microsoft (Maia), Intel | High-margin custom silicon for hyperscaler proprietary chips |
| Advanced Packaging | ASE, SPIL | NVIDIA, AMD | CoWoS capacity remains a global bottleneck |

### 2. Semiconductor Equipment & Testing

| Node | Key TW Companies | US Customers | Catalyst |
|------|-------------------|--------------|----------|
| Testing & Probing | KYEC, Winway | NVIDIA, AMD, Intel | Longer testing times for complex AI chips |
| Facility & Cleanroom | Marketech, United Integrated | Micron, Applied Materials | Global fab expansion (CHIPS Act) |
| Equipment / Materials | Scientech, GlobalWafers | KLA, Lam Research, TI | EUV support, silicon wafers |

### 3. AI Infrastructure: Servers, Cooling & Materials

| Node | Key TW Companies | US Customers | Catalyst |
|------|-------------------|--------------|----------|
| Server ODMs | Quanta, Wistron, Foxconn | Meta, Google, AWS, Microsoft | GB200 NVL72 rack assembly |
| Thermal / Cooling | AVC, Auras Tech, Jentech | NVIDIA, Dell, HPE, Supermicro | Air → liquid cooling transition; highest premiums |
| High-Speed PCBs | EMC, Unimicron, Zhen Ding | Broadcom, Arista, NVIDIA | Fiberglass/copper substrate shortages |
| BMC | Aspeed Technology | Entire US server market | Near-monopoly on server management chips |

### 4. AI Energy: Power Supplies & Grid Infrastructure

| Node | Key TW Companies | US Customers | Catalyst |
|------|-------------------|--------------|----------|
| Server Power Supply | Delta Electronics, Lite-On | Global DCs, Meta, AWS | Upgrading to 5,000W+ AI-grade PSUs |
| Heavy Electrical | Fortune Electric, Chung-Hsin | US utilities, Tesla | Exporting transformers for US grid rebuild |
| Green Energy / Smart Grid | HDRE, Century Wind Power | Google, Microsoft (ESG) | Renewable credits, grid stabilization |

## Trading the Map (3-Month Horizon)

1. **Track the "Trickle Down"**: Banks buy TSMC first → Server ODMs → Components → Equipment/Energy. Use T86 to track which layer FINI is accumulating.
2. **Monitor US CapEx**: Quarterly earnings of MSFT, META, GOOG, AMZN drive the entire map. CapEx increase → look at Server ODMs and Cooling next morning.
3. **Watch Bottlenecks**: 2026 constraints = CoWoS packaging, liquid cooling, transformers. Bottleneck-solvers (Auras, Fortune Electric) decouple from market dips.

## Next-Day Tactical Workflow

- **15:00 CST**: Analyze T86 for abnormal 3–5 day accumulation during price consolidation
- **Overnight**: Compare TW heavyweights vs US ADRs + SOX; gap-up probability
- **Liquidity filter**: TWD/USD strengthening → FINI buying wave incoming

## Open Questions

- Exact TWSE ticker codes for each company in the map (needed for `dim_supply_chain` table)
- How to handle companies that span multiple pillars (e.g., TSMC touches Foundry + Equipment)?
- Vietnam "+1" factor — monitor FDI trends between Taiwan and SEA?

## History

- 2026-05-07: Map ingested from Gemini chat. Attributed to [gemini-agent], directed by [niko].
