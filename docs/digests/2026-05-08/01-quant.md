---
date: 2026-05-08
task: 01-quant
inputs: [sc_sector_momentum, q_screener, q_indicators]
generated_by: antigravity-agent (worked example; future runs will be a Claude Scheduled Task)
data_as_of: 2026-05-07
---

# 2026-05-08 — Quant snapshot

## TL;DR
Foreign capital is rotating **out of foundry** (TSMC, ASE) and **into the
server build-out stack** — Foxconn, Lite-On, Delta lead with 5-day
z-scores >1.0. Universe is uniformly bullish (every classified ticker is
at or within ~5% of its 52-week high). Strongest pure-momentum signal:
GUC 3443 with RSI 88 and MACD histogram 143 — but foreign flow is
*opposite* (z=-1.82). Watch the divergence.

## Sector rotation (5-day foreign net flows)

The pillar/node ordering on `sc_sector_momentum` makes the rotation
obvious:

| Pillar | Node | Top ticker | Foreign 5d | Foreign 20d | Direction |
|---|---|---|---|---|---|
| infrastructure | server-odm | 2317 Foxconn | **+275.9M** | +541.8M | strong inflow |
| energy | server-power-supply | 2301 Lite-On | +40.0M | +107.3M | inflow |
| equipment | equipment-materials | 6488 GlobalWafers | +8.5M | +35.0M | inflow |
| semiconductor | asic-custom-ip | 3661 Alchip | -1.0M | +11.7M | mixed (3-week +, last week -) |
| semiconductor | advanced-packaging | 3711 ASE | -0.6M | -21.1M | outflow |
| semiconductor | **advanced-foundry** | 2330 TSMC | **-3.8M** | **-50.4M** | **biggest outflow** |

The pattern is clean: foundry distribution → server-stack accumulation.
TSMC's 20-day foreign net is -50M shares; Foxconn's is **+541.8M**.
Roughly an order of magnitude difference in opposite directions on the
same desk.

## Foreign-buying surge (foreign_net_z20 > 1.0)

Six names showing 20-day-z >1.0 on daily foreign flow — meaningful
deviation from their own recent baseline:

| Ticker | Company | Pillar / Node | z-score | 5d shares | RSI |
|---|---|---|---|---|---|
| 2317 | Foxconn | infrastructure / server-odm | **2.93** | +216.4M | 75 |
| 2301 | Lite-On | energy / server-power-supply | **2.74** | +45.6M | 73 |
| 3231 | Wistron | infrastructure / server-odm | 1.54 | +39.3M | 63 |
| 4958 | Zhen Ding | infrastructure / high-speed-pcb | 1.36 | -17.8M | 79 |
| 2382 | Quanta | infrastructure / server-odm | 1.30 | +14.1M | 65 |
| 2308 | Delta | energy / server-power-supply | 1.19 | -3.7M | 77 |

**4 of 6 are server-ODM infrastructure**. The thesis writes itself:
foreigners are paying for the server-build-out, not the silicon
upstream of it. Worth running `q_backtest_compound` rules on this
combination tomorrow.

## Overheated names (RSI > 70 AND above SMA-200)

9 names. Sorted by attention-grabbing readings:

| Ticker | Company | RSI | MACD hist | Foreign z | Notes |
|---|---|---|---|---|---|
| 3443 | Global Unichip | **87.8** | **143.2** | **-1.82** | **divergence** — euphoric technicals, foreign selling |
| 4958 | Zhen Ding | 78.9 | 7.6 | 1.36 | aligned: technicals + foreign flow both bullish |
| 2308 | Delta | 76.9 | 11.4 | 1.19 | aligned, at 52w high |
| 6488 | GlobalWafers | 76.7 | 19.3 | n/a | at 52w high, foreign z is null (TPEX sparse) |
| 3711 | ASE | 76.9 | 3.5 | -0.13 | technicals strong but foreign flat-to-out |
| 3661 | Alchip | 76.5 | 80.9 | 0.73 | aligned, near 52w high |
| 2317 | Foxconn | 75.5 | 4.2 | **2.93** | strongest naive-bullish read in universe |
| 2301 | Lite-On | 73.1 | 3.0 | **2.74** | aligned, at 52w high |
| 3037 | Unimicron | 72.2 | 9.3 | -0.42 | technicals strong, flow neutral-to-bearish |
| 8046 | Elite Material | 70.2 | 5.8 | 0.30 | mild |

**3443 GUC is the standout disagreement** — RSI 88 + MACD hist 143 are
extreme even by AI-rally standards, yet foreign flow z is -1.82
(foreigners are *selling* into this rip). Classic distribution-into-strength
profile. Worth running `decide-on-ticker` for a structured deep dive
once Phase 2 news lands.

## Oversold candidates

`q_screener(rsi_below=40, macd_hist_above=0)`: **0 matches**.

Nothing in the classified universe is oversold within an uptrend right
now. Consistent with the regime read: every name is bid up.

## What didn't show up but is worth flagging

- **All `pct_below_52w_high` readings are between 0.0 and -8%.** The
  one name >5% off its high is 3231 Wistron (-7.9%). Universe is
  uniformly elevated — typical late-stage rally compression.
- **Foundry rotation has been running 20 days.** TSMC's foreign net is
  negative on 5/10/20-day all three windows. This isn't a one-day
  noise event.
- **3553 Jentech still has no data** (no T86, no OHLCV from our
  endpoints). It's classified in dim_supply_chain but invisible to
  every q_* tool. Logged TODO: verify the code is correct or that the
  company is on Emerging Stock Market (興櫃).

## Suggested follow-ups for tomorrow

1. Run `q_backtest_compound` for "RSI > 70 AND foreign_z > 1.5" on
   forward 5d / 10d horizons — the "overbought + accumulating" combo
   on this universe.
2. Watch 3443 GUC for foreign-flow regime change. If z stays < -1 for
   another 5 days, the divergence sharpens into a credible distribution
   signal.
3. Check whether 2317 Foxconn's +216M shares 5-day inflow is a single
   block trade or sustained — `raw_flow_history(ticker_id="2317",
   days=10)` will show.
