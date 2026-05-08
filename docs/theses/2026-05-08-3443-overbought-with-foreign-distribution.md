---
ticker: 3443
company: Global Unichip (GUC) / 創意
opened: 2026-05-08
status: active
last_review: 2026-05-08
horizon: 1-3 weeks
catalyst: foreign_net_z20 recovers to >0 within 5 trading days (flow absorption confirmed)
invalidation: close < SMA-50 (3034) OR foreign_net_5d_sum stays < -3M shares for another 5 days (sustained distribution)
inputs: [sc_supply_chain_map, q_indicators, sc_ticker_momentum, raw_flow_history, sc_sector_momentum, q_backtest_compound]
sources_naive: [q_*, sc_*, raw_flow_history]
sources_aware: pending Phase 2b news pipeline
naive_conviction: 2
aware_conviction: n/a
disagreement: n/a (aware pass deferred)
---

# Global Unichip (3443) — Overbought + foreign distribution: discipline tool flipped the intuition

## TL;DR

The naive scan showed extreme RSI (87 yesterday, 79 today) and three days
of accelerating foreign selling — what looked like a textbook
distribution-into-strength setup. **The backtest harness contradicts that
read.** In this universe and regime, the same combination
(RSI > 75 AND foreign_net_z20 < −1) has historically produced **+12.4% avg
return over 5d (87.5% hit rate, n=8)** and **+32.7% over 10d (n=3)**.
The signal-pattern, as seen on prior trigger dates, has been continuation
not reversal. **But:** sample is thin and 3443's flow pattern (three
consecutive sustained-foreign-sell days) is qualitatively different
from the single-day triggers in the backtest population.

Verdict: **mildly long-biased with conviction 2/5**, watching whether
the absorption that started today (total_net flipped positive on 2026-05-08
even with foreigners still selling) sustains.

## What the data says (naive pass)

### Position in supply chain
- Pillar: semiconductor / Node: asic-custom-ip
- Peers in node: 3035 智原 (currently leading 5d foreign flow at +509K
  for the node aggregate), 3661 Alchip
- Whole semiconductor pillar except asic-custom-ip is bleeding
  (foundry −4.6M 5d, packaging −8.3M 5d). The node 3443 sits in is the
  one positive island.

### Indicator stack (2026-05-08 close)

| Indicator | Value | Reading |
|---|---|---|
| RSI-14 | 79.4 | Down from 87.8 yesterday — extreme is cooling |
| MACD line | 634.9 | Strongly positive |
| MACD histogram | 130.9 | Down from 143 — momentum starting to roll over but still positive |
| BB %B | 0.90 | Near upper band |
| ATR-14 | 289 | High volatility — 9.5% of price |
| SMA-50 | 3034 | Current price ~$5,200ish — far above |
| SMA-200 | 2074 | Long-term uptrend intact |
| pct_below_52w_high | −4.4% | Slight pullback from high |
| RS vs market 60d | 1.47 | Outperforming TWSE-50 by 47% over 60 days |
| **foreign_net_z20** | **−0.26** | **Improved from −1.82 yesterday — selling pressure easing** |
| total_net_z20 | +0.18 | Total institutional flow turned mildly positive |
| foreign_net_5d_sum | −1.98M | Five-day cumulative foreign sell |

### Flow pattern (last 30 days, key dates)

The foreign-selling story:
- **2026-05-04**: foreign −407K, total −400K (selling ramps)
- **2026-05-05**: foreign −861K, total −547K (peak day; trust +336K absorbing some)
- **2026-05-06**: foreign −645K, total −123K (selling continues but trust +605K absorbing more)
- **2026-05-08**: foreign −177K, total **+74K** (foreign selling moderated, trust +367K, total flow flips positive)

The pattern reads: foreign desks distributed aggressively for 3 days,
domestic trust funds + dealers stepped up, today's session shows
total flow positive even with foreigners still selling. **Absorption
narrative confirmed by the data.**

## Signal pattern that matches now

`RSI_14 > 75 AND foreign_net_z20 < −1 (with macd_histogram > 0)`

This is the rule the morning's quant digest implicitly flagged as
distribution-into-strength.

## Backtest grounding

Single-threshold and compound rules tested via `q_backtest_compound`
on the 25-ticker classified universe (~6 months OHLCV + ~45 days
T86 — sample is thin, treat as illustrative).

| Rule | Forward | n | Hit rate | Avg return | Worst |
|---|---|---|---|---|---|
| RSI > 75 AND foreign_z < −1 | 5d | 8 | 87.5% | **+12.4%** | −0.7% |
| RSI > 75 AND foreign_z < −1 AND MACD hist > 0 | 5d | 8 | 87.5% | +12.4% | −0.7% |
| RSI > 75 AND foreign_z < −1 | 10d | 3 | 100% | **+32.7%** | +19.1% |

**Sample warnings** included verbatim from the harness:
> Only 8 obs — illustrative.
> Only 3 obs — illustrative.

Per-ticker triggers in the population: 4958 (3), 8046 (2), 2330/3443/3711 (1 each).
**3443 is one of those historical triggers** — and the prior trigger date
played out positively for it specifically. Doesn't confirm the future
but raises the prior on continuation.

The historical pattern is opposite to the naive intuition: in this
strong-uptrend regime, "extreme RSI + foreign selling" has been a
*continuation* signal, not a reversal one. Likely interpretation:
foreign desks take profits at extension; domestic capital absorbs;
the trend resumes. The data is honest that 8 trigger dates is not
enough to bet the farm on, but it's enough to not assume the
opposite.

## Naive verdict

- **Direction**: mildly long-biased
- **Conviction**: 2/5 — limited by sample size and the unusual
  *sustained-3-day-sell* shape (vs. single-day trigger in backtest population)
- **Catalyst (data-only)**: foreign_net_z20 flips back > 0 within 5
  trading days, OR foreign_net_5d_sum reverses to > 0. Either confirms
  absorption thesis.
- **Invalidation (data-only)**: close breaks below SMA-50 (3034), OR
  foreign_net_5d_sum stays below −3M shares for another 5 days
  (= sustained distribution different from the historical pattern).
- **Honest gaps from the naive pass**:
  - Why are foreigners selling? Earnings reaction? Regional rotation?
    Specific news? Cannot answer from data alone.
  - Is the 3-consecutive-day sell pattern qualitatively different from
    the historical 1-day triggers, or just bigger? The backtest harness
    can't slice on "consecutive days" yet.
  - 3035 智原 is leading the asic-custom-ip node. Is capital rotating
    *within* the node (out of 3443 into 3035), or is this a sector-wide
    move? Worth a per-ticker comparison run.

## What the narrative sees (aware pass)

**Pending Phase 2b news pipeline.** Until entity-extraction populates
ticker_mentions on raw_news rows, the naive pass operates as the final
view. When Phase 2b lands, re-open this thesis as a `last_review`
entry that adds the news context — particularly any earnings
announcement, peer disclosures, or rotation narrative around 3035.

## The reconciliation

Single-pass thesis (no aware view to reconcile against). The
*internal* tension is the interesting part:
- Surface intuition (morning quant digest): bearish — distribution into strength
- Backtest harness: bullish — pattern has been continuation
- Flow shape today: ambiguous — foreign still selling but total flow positive

The discipline tool's role here is concrete: it stopped me from
acting on a plausible-sounding bearish intuition that the historical
data does not support. That's exactly why this discipline rule exists.

## Position sizing

**Not sized — analytical only.** This thesis is the system's first
real output; treat it as a calibration run. A real entry would
require the aware pass plus the deeper news context to confirm
neither earnings risk nor a specific catalyst is being missed.

## Catalyst & invalidation summary

- **Catalyst**: foreign_net_z20 > 0 within 5 trading days, OR
  foreign_net_5d_sum reversal to > 0. Confirms absorption.
- **Invalidation**: close < SMA-50 (3034), OR sustained foreign sell
  another 5 days (foreign_net_5d_sum < −3M). Distribution is real.
- **Next review**: 2026-05-15 (5 trading days from now), or earlier
  if either trigger fires.
