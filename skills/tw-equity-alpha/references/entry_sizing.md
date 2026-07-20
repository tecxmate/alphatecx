# Entry, sizing & macro overlay (Mode 3)

For "should I enter / add", "170 buy?", position-sizing, "is this a chase", and the macro read that
frames all of them. Plus the short-term catalyst-trade playbook.

## Contents
1. Tranche entry framework
2. Invalidation & stops
3. Position sizing
4. The macro overlay (stock-specific vs foreign-flow selloff)
5. Index vs single-stock (0050 / TSMC mechanics)
6. Short-term catalyst / momentum trades

---

## 1. Tranche entry framework
Never lump into a single-name thesis, especially pre-catalyst. Default 3-tranche structure:

| Tranche | Trigger | Zone | Size |
|---|---|---|---|
| 1 · Starter | Pullback that **holds** above the base / 200-day | at/above base support | 1/3 |
| 2 · Add | Confirmed **close above near-resistance on rising volume** | breakout level | 1/3 |
| 3 · Add | Clears the **overhead-supply** zone | supply zone | 1/3 |

Rules:
- **Don't chase a hard gap-up** — wait for a pullback-and-hold. Chasing the pop is the roller-coaster
  entry.
- A pullback *into* the starter zone that holds is a legitimate probe even on a red day; a starter is
  a *probe*, not the position — keep tranches 2–3 dry for confirmation.
- If entering at the *top* of the starter zone, stagger the limit down (e.g., ⅓ at the top, ⅓ lower)
  so a deeper dip improves your average instead of leaving you at the band's high.
- Match triggers to the specific chart's levels (base support, near-resistance, overhead supply) from
  `twse_daily_history`; don't use generic numbers.

## 2. Invalidation & stops
Define these *before* entry and don't move them on emotion:
- **Warn** — close below the base's lower edge (thesis wobbling).
- **Hard stop** — a defined level below that.
- **Thesis broken** — below the structural line (often near the dividend-yield floor).
An entry price does **not** change the invalidation. Distinguish a *macro-driven* dip (index down,
name down small — often a buy-the-base opportunity) from the name breaking on *its own* weakness (the
real invalidation). The stop is triggered by the latter, not by the index dragging it 1% on a
foreign-outflow day.

## 3. Position sizing
- **Frame it as risk, not split.** The question isn't "how do I divide NT$X" but "how much am I
  willing to lose if this single unconfirmed thesis fails?" That number, ÷ the % distance to your
  stop, is the position size.
- **Core-satellite.** A single speculative name is a *satellite* — cap it (~10–20% of the portfolio,
  less pre-catalyst). The diversified core (e.g., a broad ETF) is the default for the rest — but note
  a TWSE index ETF is *itself* concentrated (see §5), so it's "safer than one stock", not "safe".
- **Starter into a binary catalyst** (e.g., a revenue print in 2 days) is a reasonable risk posture
  *if small*; a full position into a binary is not.
- **Small accounts / odd-lot:** many quality TW names trade > NT$100k per 1,000-share lot, so a small
  account is doing **零股 (odd-lot)** — the NT$ split is then fully flexible. Watch broker minimum
  fees on tiny odd-lot orders.
- **Liquidity sizing:** check average turnover (`twse_daily_history`). Size so you can exit without
  moving the stock; a few-million-NT$/day name caps your position hard.
- **DCA the core:** lump-summing a broad ETF at all-time highs into an active correction carries
  timing risk — 定期定額 (regular investment) is the standard mitigant.

## 4. The macro overlay
Before judging any single-day move, read the tape:
- **Is the down day stock-specific or macro?** If the index is down ~2% and everything is red, it's
  macro. Check *dispersion* in the watchlist: a name down far *less* than the index is showing
  **relative strength** (constructive), not weakness.
- **Foreign-flow washouts** are the common TW pattern: foreigners dump the **index ETF (0050) and
  megacaps as ATMs** on international triggers (US semi selloff, a hawkish Fed, USD strength / TWD
  weakness) — *not* a bet against Taiwan fundamentals. 投信 often buy against it.
- **Under-owned names are shields** in exactly this kind of selloff: foreigners can't dump what they
  don't own, so a low-foreign-% name (see Sleeper Score #4) bleeds far less than 0050 or the
  foreign-heavy AI-server ODMs. This is a *feature* of the sleeper profile.
- **FX cuts both ways:** the TWD weakness driving the foreign outflow is a *fundamental tailwind* to
  a USD-exporter's earnings — the selloff and the thesis needn't conflict.
- A macro flush that drags a fundamentally-intact, still-accumulated name toward its base is an
  *entry setup* (tranche 1), not a thesis break.

## 5. Index vs single-stock (0050 / TSMC mechanics)
Useful when the user weighs an ETF vs a megacap:
- A TWSE 50 ETF (0050) is **~55–60% TSMC** — it's "shock-absorbed TSMC", not a diversified fund.
- **More volatile: the single stock (TSMC)** — over time it has bigger up *and* down days than the
  ETF. The ETF dampens moves ~40% via the other ~42% of holdings, no more.
- **Who falls more on a given day depends on what led it:** a TSMC-specific shock (ADR gap, earnings)
  → TSMC falls more; a broad/ETF-redemption day → the ETF can fall more than a flat TSMC. One day's
  reading isn't a "safer" verdict.
- **"Safer" = the ETF**, in the drawdown/single-name sense (it can't be blown up by one company) —
  but it still lives and dies with TSMC + the AI/semi theme. Neither hedges the other.

## 6. Short-term catalyst / momentum trades
For the short-horizon mode. Keep it structurally separate from the sleeper thesis.
- **Event trades:** a defined near-term catalyst — monthly revenue (~10th), earnings, a supply-chain
  data point, ex-dividend. Enter small, tight stop, short leash. If the name **already ran into** the
  event, weight **sell-the-news** risk heavily (a "buy the rumor" that's up 2 limit-ups into the
  print is a distribution risk, not a setup).
- **Cyclical bounce trades** (e.g., petrochem into a quarterly result) are *trades, not investments*
  — no earnings floor, driven by feedstock/rumor; confirm with flow (dealers distributing into the
  pop = exit it).
- **Momentum / limit-ups:** not endorsed. If asked, be honest: after 2–4 consecutive limit-ups the
  reversal probability climbs sharply; the parabola-into-reversal (§screening Avoid Catalog) is the
  common ending. Missing a runaway winner is the *cost* of a process that avoids the reversals — say
  it once, plainly, and don't moralize.
- **Ex-dividend timing:** for a high-yield name near ex-div, the price drops ~the dividend on the
  ex-date; whether it 填息 (refills the gap) is its own signal. Factor it into entry timing.
