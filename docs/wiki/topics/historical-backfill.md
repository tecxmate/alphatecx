---
title: Historical Data Backfill Strategy
type: topic
slug: historical-backfill
date: 2026-05-07
updated: 2026-06-11
belongs_to: [system-architecture]
source: chat
status: active
tags: [data, backfill, twse, prediction]
related: [system-architecture, taiwan-ai-supply-chain, 2026-05-07-v2-implementation-decisions]
---

## Summary

On bootstrap, the system backfills ~90 trading days of historical TWSE/TPEX data so that materialized views and trend analysis are useful from day one. Without backfill, the system would need to accumulate data for weeks before producing meaningful signals.

## Why Backfill Matters

- **5-day net flow** needs 5 days minimum; 90 days gives 18 rolling windows for baseline calibration
- **"Abnormal" accumulation** can only be detected against a historical norm — you need to know what "normal" 3-day FINI flow looks like for Auras Tech before flagging a spike
- **Sector rotation patterns** (the "trickle down" from TSMC → ODMs → Components → Energy) take weeks to play out — need at least one full cycle in history
- **Seasonal patterns**: month-end rebalancing, ex-dividend dates, options expiry all create recurring flow patterns visible only with >30 days of data

## Backfill Plan

### Priority 1: T86 Institutional Flow (90 trading days)
- **Source**: `https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD` 
- **Rate limit**: ~3 sec between requests to avoid throttling
- **Data per day**: ~1000 rows (all listed stocks) × 19 columns
- **Total**: ~90 requests to TWSE + ~90 to TPEX = ~180 requests over ~10 minutes
- **Storage**: ~90K rows × ~10 fields = very small (well within Neon free tier)

### Priority 2: MI_QFIIS Foreign Holdings (30 trading days)
- Tracks % of shares held by foreigners — slower-moving, 30 days sufficient
- Useful for "headroom" analysis: is foreign ownership already at ceiling?

### Priority 3: Margin Balance (30 trading days)
- Detects retail leverage buildup and short-squeeze setups
- 30 days captures recent margin trends

### Priority 4: OHLCV Daily Bars (90 trading days)
- Price context for the flow data — needed to compute price-adjusted flow significance
- Already well-supported by v1's `twse_daily_history()` function

### Priority 5: Monthly Revenue (12 months)
- MOPS data; only updates once/month; 12 months gives YoY context
- Simple single API call per market (TWSE + TPEX)

## Rate Limit Strategy

TWSE throttles aggressively. The backfill script must:
1. Sleep 3 seconds between requests
2. Retry on 429/503 with exponential backoff
3. Cache responses locally so failed runs can resume
4. Run during off-peak hours (after 18:00 CST or weekends)

## Storage Estimate (Neon Free Tier)

| Dataset | Rows | Est. Size |
|---------|------|-----------|
| T86 × 90 days | ~90K | ~20 MB |
| MI_QFIIS × 30 days | ~30K | ~8 MB |
| Margin × 30 days | ~30K | ~10 MB |
| OHLCV × 90 days | ~90K | ~15 MB |
| Monthly revenue × 12 | ~3K | ~1 MB |
| **Total** | ~243K | **~54 MB** |

Well within the 500MB free tier. Even with a year of daily accumulation, total stays under 200MB.

## Open Questions

- Should backfill run as a one-time script, or as a GitHub Action that detects gaps and fills them?
- Do we backfill TPEX (上櫃) with the same depth, or focus on TWSE (上市) first?
- Should we store the raw JSON responses as well, or only the parsed/normalized rows?

## Retention Policy

- 2026-06-11 — After Neon hit the free-tier storage cap, current retention was tightened to 60 trading days for `raw_twse_t86`, `raw_twse_valuation`, and `raw_twse_index`; 30 trading days for `raw_twse_holdings` and `raw_twse_margin`; latest 3 `lead_lag` snapshots; and 2026+ news. Long `raw_twse_ohlcv` history remains because it is small and supports indicators/backtests ([decision](../decisions/2026-06-11-neon-retention-prune.md)).
