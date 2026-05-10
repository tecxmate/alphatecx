---
ticker: 3231
company: Wistron / 緯創
opened: 2026-05-07
status: active
last_review: 2026-05-10
horizon: 2-6 weeks
entry: 147.00
catalyst: continuation breakout — close > 149 with foreign 5d sum staying > +50M shares (sustained accumulation) AND a second confirming AI-server narrative item OR a 4Q earnings beat re-rates the name toward the 161 52w-high magnet
invalidation: close < SMA-50 (134) OR foreign_net_5d_sum flips < -50M shares for 3 consecutive trading days (flow reversal) OR margin balance accelerates while foreign turns net seller (retail-trap setup)
inputs: [sc_supply_chain_map, q_indicators, raw_flow_history, q_valuation, q_index_history, n_for_ticker]
sources_naive: [q_*, sc_*, raw_flow_history, q_valuation]
sources_aware: [n_for_ticker, q_indicators, q_valuation, raw_flow_history, q_lead_lag]
naive_conviction: 3
aware_conviction: 3
disagreement: agree
factor_alpha_t_stat: 0.17
factor_alpha_annualised: 0.114
factor_r_squared: 0.44
factor_disclosure: Idiosyncratic alpha is statistically indistinguishable from zero (q_factor_alpha 2026-05-10, n=51, window=90d). The trade rides market β=0.55 + sector β=0.37, not a special-name alpha. Conviction reduced from 4 → 3.
---

# Wistron (3231) — AI server-ODM cluster, foreign accumulation confirmed

## TL;DR

Position opened at NT$147 on Thursday 2026-05-07. Friday closed 146.50.
The trade is **flat** but the supporting evidence is unusually clean.

Bull case (high conviction):
- **Earnings already triple YoY**: March 2026 monthly revenue +117.7% YoY,
  YTD +144.3% YoY. DigiTimes 2026-05-09 explicitly: "Wistron profit triples
  on server surge."
- **Foreign accumulation is large and recent**: 20-day foreign net buy
  +169M shares; foreign holdings rose from 28.28% → 29.36% in the past
  trading week.
- **Sector alpha is real**: 60d return +12.3% vs `數位雲端類指數` -8.6%
  → +20.9 pts of cross-sector alpha. Wistron is leading the AI-ODM cluster,
  not just riding it.
- **Narrative has a name**: 2026-05-09 TW investment-advisor list of "16 AI
  names to watch" included Wistron alongside Hon Hai and Quanta.

Bear / risk case (acknowledged but secondary):
- P/B at 72nd percentile of the last 90 days → paying near-recent-high
  multiples; no valuation safety net.
- RS vs broad market 60d = 0.84 (TAIEX is hot enough that even +20pt sector
  alpha leaves Wistron lagging the index).
- 52-week high at 161 is the unbroken ceiling; -9% gap from current.
- Margin balance creeping up (54.7K → 55.6K shares this week) — early
  retail crowding signal, not yet acute.

Verdict: **bullish, conviction 3/5** (naive 3 / aware 3 = agree). Initially
opened at aware_conviction 4 but `q_factor_alpha` (2026-05-10, 90d window,
n=51) decomposed the +20.9pt sector-alpha into:

  market β = 0.55 (t=3.52)
  sector β = 0.37 (t=1.58)
  flow   β = 0.03 (t=0.20)
  residual α = +11.4% annualised, t=+0.17 (NOT significant)
  R² = 44%

Translation: the +20.9pt outperformance is **factor-driven, not
idiosyncratic**. The trade is a coherent factor-rotation play (long market
β + long AI-sector β) and the fundamentals/flow narrative supports it,
but there's no statistically distinguishable special-name alpha here.
Drop conviction one notch and treat the position as a beta trade, not
an alpha trade. Position management unchanged — invalidation levels
still binding.

## Position management

| Scenario | Level | Action |
|---|---|---|
| Entry | 147 | held |
| Continuation breakout | close ≥ 149 with foreign 5d > +50M | size up; next stop 161 |
| Soft pullback (normal) | 140 (~ATR(14)=4.6 below entry) | hold |
| Momentum break | **close < 134 (SMA-50)** | structural exit |
| Flow invalidation | foreign_5d_sum < -50M for 3 days | exit on bounce |

ATR(14) is 4.57, so a 5-pt swing in either direction is normal noise; only
sustained moves outside the 134-149 channel count.

## What the data says (naive pass)

### Position in supply chain
- Pillar: infrastructure / Node: server-odm
- Cluster (ρ at lag 0): 2382 Quanta (0.71), 2317 Hon Hai (0.67),
  6669 Wiwynn (0.65), 2356 Inventec (0.53). Highly co-moving — sector
  rotation drives this trade.
- Supplied by: 3711 ASE Technology (advanced-packaging, our only confirmed
  inbound supply edge).
- US partners: Meta, Google.

### Technicals as of 2026-05-08 close
- Close 146.50, SMA-50 133.87, SMA-200 133.31. Above both by ~9-10%.
- RSI(14) 63.6 — neutral, room to overbought territory.
- MACD line +3.39, histogram +0.51 — momentum still expanding.
- BB %B 0.88 — upper third of the band, not extreme.
- ATR(14) 4.57 → typical daily swing.
- 52-week high gap: -9.0%. Two prior failed attempts at the high.

### Flow (T86, 20 trading days)
- Foreign net: **+169,484,935 shares** (massive accumulation).
- Trust net: -1,558,166 (net flat).
- Total three-party: +167,923,295.
- 5/8 most-recent days net foreign buying; +25M on May 6 was the standout.
- Foreign holdings: 28.28% → 29.36% (+1.08 pt week-on-week).
- Margin balance: +1.7K shares this week (slow drift up).
- Short balance: 539 shares (de-minimis).

### Valuation
- P/E 17.0, P/B 2.62, dividend yield 3.75%.
- P/B percentile vs last 90d: 72% → expensive relative to recent history,
  but supported by triple-digit YoY revenue growth.

### Lead-lag (120-day window)
- Tickers that lead 3231: nothing meaningful (gain ≤ +0.006).
- Tickers that 3231 leads: 2399 (Aspeed) at lag 3d ρ=0.215, gain +0.019.
  Marginal.
- Practical implication: **3231 doesn't have a reliable upstream signal
  ticker**. Watch the cluster (2382/2317/6669/2356) as a unit.

## Factor decomposition (q_factor_alpha)

Run on 2026-05-10 against the last 90 calendar days (n=51 trading days
after intersection with sector-index, flow-factor and market-factor
date sets).

| Quantity | Value | Reading |
|---|---|---|
| α (daily)              | +0.045%       | tiny |
| α annualised           | +11.4%        | apparent outperformance |
| α t-stat               | +0.17         | **noise — not significant** |
| R² (factor explained)  | 44%           | moderate |
| β market (0050)        | +0.55, t=3.52 | significant moderate exposure |
| β sector (數位雲端)     | +0.37, t=1.58 | marginal moderate exposure |
| β flow (foreign-z LS)  | +0.03, t=0.20 | ≈ zero, not a flow trade |

The flow β being ~zero is interesting given how much I leaned on
"foreign +169M shares 20d" in the bull case. It means Wistron's daily
returns are NOT correlated with the flow-factor portfolio after market
and sector are already in. The foreign-buying narrative is real in
absolute terms, but the daily price action isn't clocked off the
foreign-flow rhythm — it's clocked off TAIEX and the AI-sector index.

**This narrows the trade thesis. We're long beta. The fundamental
narrative gives conviction in the regime; the factor model says we
shouldn't expect Wistron to outperform peers within the regime.**

## What the news says (aware pass)

- **2026-05-09 DigiTimes**: "Wistron profit triples on server surge, AI
  demand seen robust." Earnings/narrative confirmation.
- **2026-05-09 sinotrade**: AI server cohort rebound, foreign accumulation
  on 鴻海/緯創 specifically called out. Direct flow validation.
- **2026-05-09 Wantrich (旺得富)**: CCL/PCB/CPU shortage narrative
  thread, big-name analyst (大咖投顧) flagged 16 AI names — Wistron in
  the list.

The aware pass strengthens conviction because it (a) pins a fundamental
catalyst (tripled earnings) to the flow we're already seeing in T86,
(b) gives us a peer-validation list (analysts naming the same cluster
we already classify as server-ODM), and (c) provides a forward narrative
hook (CCL/PCB/CPU shortage feeding through to ODMs).

## Discipline

This thesis tracks against the structured invalidation in frontmatter.
The post-close cron (`src/cron/thesis_status.py`) will surface RSI,
foreign_z, foreign_5d, and SMA-50-distance daily; if any of those trip
the levels above, escalate via Telegram.

The dashboard at `/d/{TOKEN}/t/3231` carries the live chart, foreign-flow
panel, and 30-day news feed.
