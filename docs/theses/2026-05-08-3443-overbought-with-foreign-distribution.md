---
ticker: 3443
company: Global Unichip (GUC) / 創意
opened: 2026-05-08
status: active
last_review: 2026-05-08
horizon: 1-3 weeks
catalyst: foreign_net_z20 recovers to >0 within 5 trading days (flow absorption confirmed) OR a second foreign-broker upgrade / earnings beat that re-rates the name
invalidation: close < SMA-50 (3034) OR foreign_net_5d_sum stays < -3M shares for another 5 days (sustained distribution) OR a downgrade walking back the 2026-05-06 upgrade
inputs: [sc_supply_chain_map, q_indicators, sc_ticker_momentum, raw_flow_history, sc_sector_momentum, q_backtest_compound, n_for_ticker, n_source_status]
sources_naive: [q_*, sc_*, raw_flow_history]
sources_aware: [n_for_ticker, n_source_status, q_indicators, sc_ticker_momentum, sc_sector_momentum, raw_flow_history, q_backtest_compound]
naive_conviction: 2
aware_conviction: 3
disagreement: agree
---

# Global Unichip (3443) — Overbought + foreign distribution: discipline tool flipped the intuition

## TL;DR

The naive scan showed extreme RSI (87 → 79) plus three days of accelerating
foreign selling — what looked like textbook distribution-into-strength.
The backtest harness already contradicted that read (RSI > 75 AND
foreign_z < −1 has historically been continuation, +12.4%/5d, n=8). The
**aware pass closes the naive pass's biggest honest gap directly**: a
2026-05-06 Economic Daily News article reports that foreign brokers
upgraded target prices on 3443 (alongside Kinsus and 8 other names) with
the largest hike in the cohort up to 194%. So the apparent paradox is
just sell-side-research vs. buy-side-flow within the same foreign
houses — a structural, not thesis-breaking, split.

A regime-qualified rule (`RSI > 75 AND foreign_z < −1 AND
rs_vs_market_60 > 1.3`) tightens the data signal further: 100% hit rate,
+16.6% / 5d (n=5, illustrative). Combined with the upgrade catalyst and
the absorption signal (5/8 total flow flipped positive even with
foreigners still selling), the aware pass nudges conviction to 3/5.

Verdict: **bullish, conviction 3/5** (naive 2/5 → aware 3/5 = agree on
direction, +1 notch on size). Capped below 4 because (1) one article in
14 days is thin narrative, (2) we cannot tell whether foreign-flow
selling was front-running the upgrade or unrelated unwind, (3) intra-node
rotation has the marginal foreign buyer choosing 3035 智原, not 3443.

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

Run 2026-05-08, after `n_for_ticker` came online. The 14-day window
returned **exactly one** article matching 3443:

> **2026-05-06, Economic Daily News (via gnews-tw-stocks-zh)** —
> 「景碩、創意等十檔個股獲外資法人上調目標價最多 調幅最高達194%」
> *(Kinsus, Global Unichip and 8 other names received the largest
> foreign-broker target-price upgrades; biggest hike up to 194%.)*

That single article carries most of the aware-pass weight because it
**directly answers the naive pass's #1 honest gap**: foreigners aren't
all selling — foreign **broker** desks (sell-side research) put through
an aggressive target-price upgrade, while foreign **flow** desks
(buy-side trading) have been distributing into the resulting rip. Same
firms, different teams, opposite views. Flow data sees this cleanly
because it measures execution, not opinion.

The news vacuum around 3443 is itself informative. 12 sources are live
and fresh (latest fetched 2026-05-08T10:37:46Z, ~1,100+ articles ingested
across the relevant windows), and the 3443 / 創意 token only matched once.
The morning's quant↔news disagreement digest was correct: narrative
cover is thin and what cover does exist is sell-side broker action — not
earnings commentary, not retail-driven hype, not a sector-wide
narrative.

**Closes naive gap #3 (intra-node rotation):** asic-custom-ip is the
only positive node in the semiconductor pillar over 5 days (foreign
+509K, total +1.57M), but **3443 itself contributes negative 5d flow**
(foreign −2.09M). The node is being accumulated; the marginal foreign
buyer is choosing **3035 智原** (top 5d ticker in the node), not 3443.
Capital rotates *within* the node, out of 3443 and into 3035. That is
a real datapoint for sizing the long.

**Aware-pass refinement of the data signal.** Re-running the backtest
with a relative-strength qualifier (3443 currently sits at
rs_vs_market_60 = 1.47):

| Rule | Forward | n | Hit | Avg | Worst | Best |
|---|---|---|---|---|---|---|
| RSI > 75 AND foreign_z < −1 AND **rs_vs_market_60 > 1.3** | 5d | 5 | **100%** | **+16.6%** | +9.2% | +25.1% |
| Same rule | 10d | 2 | 100% | +25.0% | +19.1% | +30.8% |

Sample warnings (verbatim from the harness):
> - "Only 5 obs — illustrative"
> - "Only 2 obs — illustrative"

The RS-qualified rule is *cleaner* than the naive rule's same-pattern
backtest (n=8 / 87.5% / +12.4%): hit rate to 100%, avg to +16.6%, worst
case from −0.7% to +9.2%. The "this regime has historically been
continuation" read survives the news layer and tightens once we
condition on the regime 3443 is actually in. Per-ticker triggers in the
RS-qualified population: 4958 (3), 8046 (2). 3443 itself is NOT in the
RS-qualified population — its prior trigger date didn't satisfy
RS > 1.3 — so the historical data is analogous, not direct.

**Pre-publication selling — the new honest gap.** Foreign-flow selling
started **2026-05-04**, two trading days before the upgrade article
published on 5/6 evening Taipei. Either the trading desks (a) front-ran
the upgrade publication knowing retail/domestic capital would chase it
(bullish read — they're done selling), or (b) unwound for an unrelated
reason like regional rotation, mandate change, redemptions (bearish
read — selling continues past the upgrade). One article cannot
distinguish (a) from (b). Tracking foreign_net_z20 over the next 5
sessions resolves this.

## The reconciliation

| | Naive | Aware |
|---|---|---|
| Direction | mildly long | bullish |
| Conviction | 2/5 | 3/5 |
| Catalyst | foreign_net_z20 flips +ve in 5d | second upgrade / earnings beat / foreign flow flip |
| Invalidation | close < SMA-50 OR foreign_net_5d < −3M for 5 more days | + downgrade walking back the 5/6 upgrade |
| Biggest gap | "why are foreigners selling?" | front-run vs. unrelated-unwind ambiguity |

**Classification: agree.** Both passes point bullish; conviction nudges
+1 notch. The aware pass closes the naive pass's #1 and #3 honest gaps
directly (the news catalyst explains the run; sector data confirms
intra-node rotation to 3035). The remaining caveats are different in
kind from the naive pass's caveats, which is healthy — the gap structure
is moving forward, not in circles.

The shared blind spot — the standard "agree" risk — is **regime**: both
passes lean on the strong-uptrend Taiwan AI environment. Three things
would have to break simultaneously to flip the read: (1) the foreign-broker
upgrade cycle stalls or reverses, (2) the absorption pattern fails (trust
funds turn sellers too), and (3) the relative-strength advantage decays.
Until any of those crack, agree-bullish is the read.

The discipline tool's continued role: the surface intuition was bearish
(distribution-into-strength); the historical data said continuation; the
news layer explained the price action AND tightened the data read in the
same direction. The aware pass is doing the work it was designed for —
not paraphrasing the news, but using it to close gaps the data couldn't
close on its own.

## Position sizing

**Still not sized — analytical only.** Aware pass complete; the system
now has a two-pass read on this name. A real entry decision requires
explicit user direction on book size and risk budget, plus a check
against the broader portfolio's existing AI / Taiwan-semiconductor
exposure (the thesis lives inside an already-tilted regime, so the
shared-blind-spot risk above is binding for sizing).

If sized, the aware-pass-conditional approach would be: scale into
3443 only after foreign_net_z20 prints positive on at least one of the
next 5 sessions (resolves the front-run vs. unrelated-unwind gap on the
bullish side); cap allocation to keep the *combined* 3443 + 3035 +
3661 (asic-custom-ip node) exposure within node-level risk budget,
since the intra-node rotation says the marginal foreign buyer prefers
3035.

## Catalyst & invalidation summary

- **Catalyst**:
  - foreign_net_z20 > 0 within 5 trading days, OR foreign_net_5d_sum
    reversal to > 0 (resolves the new gap on the bullish side)
  - OR a *second* foreign-broker target-price upgrade article, OR an
    earnings beat that re-rates the name (compounds the 5/6 catalyst)
- **Invalidation**:
  - close < SMA-50 (3034), OR foreign_net_5d_sum stays < −3M for
    another 5 days (resolves the new gap on the bearish side)
  - OR a downgrade walking back the 2026-05-06 upgrade (the narrative
    catalyst flips)
- **Next review**: 2026-05-15 (5 trading days from now), or earlier
  if any trigger fires.
