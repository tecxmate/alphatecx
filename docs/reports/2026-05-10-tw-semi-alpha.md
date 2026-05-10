# Taiwan Semiconductor Supply-Chain Alpha Report
**As of 2026-05-10 — flow & indicator data through TWSE T+1: 2026-05-08; monthly revenue: 2026-03**
**Stack:** alphatecx v1 (TWSE/MOPS primitives) + alphatecx v2 (supply-chain classification, multi-window flow, technical indicators, screener, backtester, factor regression, cointegration, PCA, quality composite, regime).

> **All v2 quant tools are now live.** This version supersedes the earlier flow-only narrative; the factor-alpha and cointegration results materially change the trade book.

---

## 1. Market regime (`q_regime` direct read)

| Metric | Value |
|---|---|
| Window | 30 trading days, 42 classified tickers |
| 30-day annualised vol | **31.4% (high)** — trend: **falling** ✅ |
| Avg pairwise correlation | **0.347 (normal)** — trend: **falling** ✅ |
| Composite label | **high_vol_normal** |

Both vol and correlation are elevated but trending down. Falling correlation = dispersion is opening up — alpha bets *will* differentiate from here. Falling vol = the regime is improving, not breaking. Position size still constrained by the absolute vol level, but the directional read is "lean in, don't lean out."

---

## 2. Real alpha is concentrated in 4 names — and they are **not** the server-ODM cluster

The factor regression (`q_factor_screen`) decomposes each ticker's 90-day return stream into market β (0050), sector β (sector index), flow β (foreign-buy long/short portfolio), and a residual α. **Only |t-stat| > 2 counts as statistically real alpha.** Across the entire infrastructure + semiconductor + equipment universes, only four names cleared that bar:

| Code | Name | Pillar / Node | α annualised | α t-stat | R² |
|---|---|---|---:|---:|---:|
| **3583** | Sunyad (辛耘) | equipment / equipment-materials | **+431%** | **2.71** ✅ | 0.16 |
| **6147** | ChipMOS (頎邦) | equipment / testing-probing | **+461%** | **2.31** ✅ | 0.11 |
| **3665** | BizLink (貿聯-KY) | infrastructure / connectors-cables | **+320%** | **2.13** ✅ | 0.21 |
| **5274** | ASPEED (信驊) | infrastructure / bmc-management | **+266%** | **2.17** ✅ | 0.49 |

These are the genuine stock-picking opportunities — performance not explained by market, sector, or flow factor exposures. **6147 ChipMOS is the standout**: it has the second-highest alpha t-stat *and* the longest possible foreign buy streak (20 consecutive days, +64.3M shares 20d). Triple confirmation: idiosyncratic alpha + flow + persistence. **3665 BizLink** is similar (10-day buy streak + α t = 2.13). **5274 ASPEED** has lower flow z-score but the highest sector exposure (β_sector 1.23) — the AI-server-cloud beta amplifies its alpha.

**Negative-alpha standout:** **2330 TSMC**, α annualised −37.8%, **t = −1.72** (marginally significant), R² **0.94** — i.e. 94% of TSMC's daily-return variance is explained by market + sector + flow factors, and the residual is *negative*. This is rigorous confirmation of the foreign-sell signal: TSMC is structurally lagging its own factor stack.

---

## 3. The server-ODM "tier-S" basket — factor bet, not stock-picking bet

The big intuitive call from §3a in the prior version (long 2317 / 3231 / 2356 / 2382) **does not survive the factor regression**:

| Code | Name | α annualised | α t-stat | R² | Interpretation |
|---|---|---:|---:|---:|---|
| 2317 | Hon Hai | −13.8% | −0.21 | 0.63 | All factors. No edge. |
| 3231 | Wistron | +8.3% | +0.13 | 0.45 | All factors. No edge. |
| 2356 | Inventec | +21.4% | +0.38 | 0.61 | All factors. No edge. |
| 2382 | Quanta | +50.5% | +0.68 | 0.43 | All factors. No edge. |
| 2301 | LiteOn | −105% | −1.05 | 0.52 | Factors + small negative residual. |

None significant. The basket has a strong tape because of its **factor loadings** (high market β, high sector β, modest positive flow β), not because of company-specific outperformance. **PCA (`q_pca_decompose`) confirms this directly: PC1 explains 65.0% of basket variance** with all six tickers loaded between +0.36 and +0.46 — i.e. one common factor (server-ODM beta) drives most of the move.

**Trading implication:** the basket is one bet with six legs. Size as one position, not as six diversified picks. Use it for AI-server-capex β exposure; do not size it up expecting alpha decay between names.

---

## 4. Cointegration tests **reverse** both pair-trade theses

| Pair | Stationary (5%) | Half-life | Spread z | Signal | Trade |
|---|:-:|---:|---:|---|---|
| 2317 Hon Hai / 2330 TSMC | ✅ | 10.8 d | **+2.37** | short_a_long_b | **Long TSMC, short Hon Hai** |
| 2301 LiteOn / 2308 Delta | ✅ | **5.6 d** | **+3.19** | short_a_long_b | **Long Delta, short LiteOn** |
| 3231 Wistron / 3037 Unimicron | ❌ (only stationary at 10%) | 8.1 d | +1.99 | no_signal | **Not tradeable** |

**Both pair theses I wrote earlier were directionally wrong.** The flow-direction read (foreign buying ODM, foreign selling foundry) is real, but the *price* spreads have already overshot:

- **2317/2330 z = +2.37**: Hon Hai has outperformed TSMC by 2.4σ over the 120-day window. Foreigns may still be rotating in, but the price has run far enough that the spread now mean-reverts. Half-life 10.8 days. Stat-arb: **short Hon Hai / long TSMC**.
- **2301/2308 z = +3.19, half-life 5.6 days**: even more extreme — LiteOn has been bid up so hard relative to Delta that the spread is at +3.2σ with a fast revert. **Short LiteOn / long Delta**, target close in ~6 trading sessions.

The 3231/3037 spread is not cointegrated at the 5% level — Wistron and Unimicron drift independently, so this is not a stat-arb pair. Discard.

This is the most important correction in the report: **flow tells you direction; cointegration tells you when the price has paid for the flow**. They disagree right now.

---

## 5. Quality composite — the genuine value-and-flow combinations

`q_quality_score` blends growth + valuation (P/B percentile vs own 90-d history) + flow Z + trend into a 0–100 score. The leaderboard separates names that *look* cheap on absolute multiples from names that are cheap *relative to their own recent history* (the actual mean-reversion edge).

### Semiconductor pillar (best risk/reward — value + growth + flow):

| Code | Name | Score | Rev YoY | P/B percentile | Flow Z | Comment |
|---|---|---:|---:|---:|---:|---|
| **2344** | Winbond | **82** | +91.5% | **35.9** | n/a | DRAM; **cheapest in pillar vs own history**; +134M foreign 20d |
| 2408 | Nanya Tech | 76 | +560% | 48.7 | n/a | DRAM upcycle; +26M 20d but base effect inflates YoY |
| 2330 | TSMC | 62 | +45% | **98.7** | +0.15 | **At ATH P/B percentile**; α t-stat = −1.72 |
| 2337 | Macronix | 61 | +96% | 78.2 | n/a | NOR-flash |
| 8046 | Nan Ya PCB | 61 | +39% | 88.5 | −0.42 | Expensive + distribution — skip |
| 3443 | Global Unichip | 58 | +33% | **98.7** | −0.26 | Most expensive ASIC IP relative to own history |
| 3711 | ASE | 47 | +14.6% | 94.9 | **−1.93** | Distribution extreme; expensive |
| **3661** | **Alchip** | **36** | **−46.6%** | 98.7 | −0.56 | **Revenue collapsed!** Despite AI-ASIC narrative |
| **3035** | **Faraday** | **34** | **−69.4%** | 87.2 | +0.52 | **Revenue collapsed even harder** |
| 2454 | MediaTek | 31 | +12.9% | **100** | n/a | At absolute P/B all-time high |

**Two earnings shocks not visible in flow data alone:** Alchip and Faraday — the two names I previously flagged as "early-stage ASIC IP rotation" — have **revenue down 47% and 69% YoY in March**. Whatever the AI-ASIC narrative says, the actual revenue numbers say their custom-IP backlog has rolled over. **Move both out of buy candidates**. The foreign 4-day buy streaks on these names are likely shorts being squeezed or repositioning, not fundamental flow.

**2344 Winbond is the new top semiconductor pick:** quality 82, P/B percentile 35.9 (cheap vs own history), revenue +91.5% YoY. The DRAM upcycle narrative + cheap valuation + foreign accumulation (+134M 20d in the memory-DRAM node, with Winbond as the named driver) is the cleanest "cheap, growing, accumulated" combination in the pillar.

### Infrastructure pillar (the rotation's destination, ranked by quality):

| Code | Name | Score | Rev YoY | P/B pct | Flow Z | Comment |
|---|---|---:|---:|---:|---:|---|
| 3081 | LandMark (聯亞) | 100* | +89% | n/a | n/a | Optical-CPO; sparse data — verify |
| 5274 | ASPEED | 100* | +64% | n/a | n/a | **Only α-significant infra name; size up** |
| 6274 | TUC (台燿) | 100* | +72% | n/a | n/a | High-speed CCL — but flow is **negative** |
| **3324** | **Aurora (雙鴻)** | **92.7** | **+92%** | n/a | **+4.25** | Cooling; **flow Z extreme positive** — flow inflection |
| 2314 | MTI | 79 | +98% | 42 | n/a | Tiny float |
| 3653 | Auras | 64 | +19% | 41 | n/a | |
| 3017 | AVC (奇鋐) | 63 | +112% | **86** | −0.66 | Hot growth; expensive vs own history; foreign distribution |
| 3231 | Wistron | 61 | +118% | 71.8 | −0.10 | Growth confirmed; valuation moderate |
| 2382 | Quanta | 58 | +88% | **96** | −0.24 | Very expensive vs own history |
| 3037 | Unimicron | 56 | +23% | **89.7** | −0.53 | Expensive + flow distribution |
| 2317 | Hon Hai | 56 | +46% | 84.6 | +0.40 | Above-average flow but expensive |
| 2356 | Inventec | 54 | +47% | **89.7** | n/a | Higher-than-it-looks valuation |
| 4958 | Zhen Ding | 54 | +7.2% | 93.6 | +0.06 | Weak growth + expensive |
| 2383 | Elite Material | 52 | +57% | **96.2** | n/a | Expensive vs own |
| 2399 | Biostar | 46 | **−21.7%** | 91 | −0.25 | Revenue contracting |
| 3189 | Kinsus | 45 | +25% | 84.6 | n/a | |
| 6669 | Wiwynn | 42 | +14% | 79.5 | n/a | Underperforming peers |
| 3665 | BizLink | 41 | +22% | 91 | n/a | **But α t-stat = 2.13** — alpha is in the residual |
| 3533 | Speedtech | 39 | +23% | **96.2** | n/a | Cheapest streak (+13d) but most expensive PB |

**Two big upgrades:**

1. **3324 Aurora (雙鴻)** — quality 92.7, revenue +92% YoY, **flow Z = +4.25** (the most extreme positive z-score in the data, tied with 6488 GlobalWafers). I had this on the FADE list earlier because it was -12.6M shares 20d in cooling. The latest reading shows that distribution has reversed sharply. Strong inflection candidate. Verify flow continuity tomorrow.

2. **2356 Inventec at P/B percentile 89.7** — its absolute P/B (2.33) looks cheap, but it is at the 90th percentile of its own 90-day history. **The "value" angle in v2 was wrong**; it's expensive vs its own recent valuation. Drop the "cheapest server ODM" framing.

---

## 6. Updated trade book

### 6a. **Tier 1 — true-alpha longs** (factor-regression-confirmed, |t| > 2)

| Pos | Code | Name | Why | Sizing comment |
|---|---|---|---|---|
| Long | **6147** | ChipMOS | α t = 2.31, **20-day buy streak**, +64.3M shrs 20d, semi test capacity tightening | Best single-name in book |
| Long | **5274** | ASPEED | α t = 2.17, BMC monopoly, March rev +63.6% YoY | Mid weight (RSI not extreme) |
| Long | **3665** | BizLink | α t = 2.13, **10-day buy streak**, AI server cabling | Mid weight |
| Long | **3583** | Sunyad | **α t = 2.71** (highest), equipment-materials niche | Smaller — R² only 0.16 means lots of unexplained vol |

These four are the actual stock-picking opportunities in the universe. Position size: 2.5% portfolio per name, total 10%, in the "alpha sleeve."

### 6b. **Tier 2 — factor-bet basket** (size as one position with six legs)

Server-ODM basket: **2317 / 3231 / 2356 / 2382 / 2376 / 6669**, equal-weight. PC1 = 65% confirms one-factor exposure. Treat as a 5–10% portfolio bet on AI-server-capex β. Do **not** size each leg independently. Cut on regime break (vol > 35% or correlation > 0.55).

### 6c. **Tier 3 — flow inflection watch (verify tomorrow)**

- **3324 Aurora (雙鴻)** — quality 92.7, flow Z +4.25, March rev +92% YoY. If 5-day flow flips positive, add ~2%.
- **2344 Winbond (華邦電)** — quality 82, P/B percentile 35.9 (cheapest in semi pillar vs own history), DRAM upcycle, +134M shrs node-level 20d. ~3% sizing if confirmed.

### 6d. **Pair trades — stat-arb (cointegration-confirmed)**

| Long | Short | Spread z | Half-life | Sizing |
|---|---|---:|---:|---|
| **2330 TSMC** | **2317 Hon Hai** | +2.37 | 10.8 d | 1× notional pair |
| **2308 Delta** | **2301 LiteOn** | **+3.19** | **5.6 d** | 1× notional pair, larger; fast revert |

Net market-neutral. Stop: spread further widens by 0.5σ (z > 2.9 / 3.7). Target: spread back to z = 0 (mean), partial close at z = 0.5.

### 6e. **Fade / avoid**

- **2330 TSMC outright** — only as the long leg of the cointegrated pair, not as a standalone holding (α t = −1.72)
- **3711 ASE** — quality 47, flow Z = −1.93, distribution extreme
- **3661 Alchip** + **3035 Faraday** — **revenue down 47% and 69% YoY**; the AI-ASIC narrative does not match their actual numbers
- **3037 Unimicron, 4958 Zhen Ding, 6213 Iteq, 6274 TUC** — substrate/PCB cluster, all expensive vs own history with foreign distribution
- **2454 MediaTek** — at 100th P/B percentile, growth tepid
- **2399 Biostar** — revenue contracting −21.7% YoY

---

## 7. What changed vs the prior versions of this report

| Earlier call | Updated finding | Source of revision |
|---|---|---|
| Long basket 2317/3231/2356/2382 as alpha bets | **Factor exposure, not alpha**; size as one position | `q_factor_screen` (all four α t < 1) |
| Long Hon Hai vs short TSMC pair | **Reverse: long TSMC, short Hon Hai** — spread overshoot | `q_cointegration_pair` z = +2.37 |
| Long LiteOn vs short Delta pair | **Reverse: long Delta, short LiteOn** — spread overshoot | `q_cointegration_pair` z = +3.19 |
| 2356 Inventec "cheapest server ODM" | **At 90th percentile of own P/B history** | `q_quality_score` |
| 3035 Faraday + 3661 Alchip "early-stage ASIC IP rotation" | **Revenue −47% / −69% YoY** — fundamental break | `q_quality_score` |
| 3324 Aurora on fade list | **Flow Z = +4.25 (extreme positive)** — inflection | `q_quality_score` flow subscore |
| ASPEED, ChipMOS, BizLink, Sunyad noted but not promoted | **Only four names with statistically real alpha** | `q_factor_screen` |
| 2344 Winbond mentioned only at node level | **Top semi pillar quality (82/100), cheap vs own history** | `q_quality_score` |
| 3231/3037 pair mooted | **Not cointegrated at 5%** — discard | `q_cointegration_pair` |

---

## 8. Action checklist — tomorrow morning (T+1 = 2026-05-09 lands)

1. Re-run `q_cointegration_pair` for both active pairs — confirm z hasn't reverted before entry.
2. Pull `monthly_revenue` for **3661 Alchip and 3035 Faraday** to verify the −47% / −69% YoY (these are surprising enough to deserve a primary-source check before acting on them).
3. Pull `sc_ticker_momentum` on **3324 Aurora** with `min_streak ≥ 1` — look for first foreign-buy day starting the streak.
4. Pull `monthly_revenue` for **2344 Winbond** — confirm the +91.5% number and check April filing if available.
5. Run `q_factor_alpha` on the four tier-1 alphas (6147, 5274, 3665, 3583) at `days=120` to check stability of their t-stats over a longer window.
6. Pull `n_for_ticker` on Hon Hai vs TSMC — look for catalysts that explain the 2.37σ spread overshoot (corporate action, large-block trade, results expectations) before sizing the pair.
7. Pull `twse_foreign_holdings` for ChipMOS (6147) and BizLink (3665) — alpha-tier names need foreign-room verification before sizing.

---

*Compiled by Claude. Quant primitives via alphatecx v2 (`q_regime`, `q_factor_screen`, `q_factor_alpha`, `q_cointegration_pair`, `q_pca_decompose`, `q_quality_score`, `q_indicators`, `q_screener`, `q_backtest`, `q_valuation`, `sc_ticker_momentum`, `sc_sector_momentum`, `sc_compare_nodes`, `sc_supply_chain_map`). Data sources: TWSE T86 / MI_QFIIS / MI_MARGN / BWIBBU_d, TPEX dailyTrade, MOPS T187AP05, MI_INDEX. All flow numbers are net institutional shares; revenue in 千元 TWD. Factor regression is OLS over 90 trading days vs market (0050), sector index, and a long-short flow factor; α t-stat |t|>2 is the significance bar. Cointegration is Engle-Granger two-step; "tradeable" requires stationarity at 5% AND |z|≥1.5.*
