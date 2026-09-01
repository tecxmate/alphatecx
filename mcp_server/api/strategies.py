"""Systematic strategies from quant funds — what transfers here, and what does not.

[niko] asked what could be mimicked from Renaissance, Citadel, Millennium, Two
Sigma, AQR, Man AHL and the Chinese quant houses. The useful answer requires
saying NO clearly, because most of what makes those firms famous is not a
strategy anyone can copy — it is infrastructure, capital structure, or a
regulatory position.

THE ORGANISING CLAIM: what transfers from quant investing is the RIGOR, not the
signals. The published factor premia (AQR) and trend following (AHL) work on
daily closes and are fully documented. Medallion's edge is inseparable from
tick data, co-located execution and a closed employee-only capital base;
Citadel Securities' edge is that it IS the market maker. No amount of code here
reproduces either, and a tool that implied otherwise would be selling a
fantasy.

So every entry carries a `status`:

    available    implemented and callable today
    buildable    the data exists here; it is engineering, not research
    out_of_reach the input this needs does not exist in this system, and
                 saying why is more useful than a degraded imitation

`out_of_reach` entries are kept deliberately. A user who has read about
Renaissance deserves to be told why it cannot be copied, not to be quietly
handed a moving-average crossover with a famous name attached.

Pure data — no DB, no network. The point is to be inspectable and honest, not
clever.
"""

from __future__ import annotations

AVAILABLE = "available"
BUILDABLE = "buildable"
OUT_OF_REACH = "out_of_reach"

# The system's actual data position, restated here because every honest
# judgement below follows from it: daily TWSE/TPEX bars, institutional flow
# published once a day near 15:00, monthly revenue, and a supply-chain
# classification. No intraday book, no tick data, no execution, no shorting or
# leverage modelled, no point-in-time universe membership.
DATA_REALITY = (
    "Daily TWSE/TPEX closes, T86 institutional flow (published once daily near "
    "15:00), monthly revenue, and a hand-classified supply-chain universe. No "
    "tick data, no order book history, no execution path, and no point-in-time "
    "record of universe membership."
)

STRATEGIES: dict[str, dict] = {
    "trend_following": {
        "name": "Trend following / time-series momentum",
        "practitioners": ["Man AHL", "Winton", "Aspect"],
        "mechanism": (
            "Own what has gone up over the past 3-12 months, exit when it stops. "
            "Judged per instrument against its OWN past, not ranked against "
            "peers — that is what makes it time-series rather than "
            "cross-sectional."
        ),
        "needs": "Daily closes and a volatility estimate. Nothing else.",
        "status": BUILDABLE,
        "tools": ["q_indicators", "price_history", "sc_ticker_momentum"],
        "honest_limit": (
            "The most robust published anomaly and the most crowded. Its real "
            "cost is behavioural: long flat stretches and frequent small losses "
            "between rare large gains. Most people abandon it in the flat "
            "stretch, which is where its returns are actually earned."
        ),
    },
    "cross_sectional_momentum": {
        "name": "Cross-sectional momentum (relative strength)",
        "practitioners": ["AQR", "most quant equity books"],
        "mechanism": "Own the strongest names relative to the universe; avoid the weakest.",
        "needs": "Daily closes across a universe.",
        "status": AVAILABLE,
        "tools": ["momentum_leaders_scan", "sc_sector_momentum", "q_factor_alpha"],
        "honest_limit": (
            "Suffers violent reversals at market turning points — momentum "
            "crashes are its signature failure and they arrive precisely when "
            "the strategy looks best."
        ),
    },
    "factor_premia": {
        "name": "Factor investing — value, quality, size, low-volatility",
        "practitioners": ["AQR", "Dimensional", "Robeco"],
        "mechanism": (
            "Tilt toward characteristics with documented long-run premia rather "
            "than forecasting individual companies."
        ),
        "needs": "Valuation ratios and fundamentals across a universe.",
        "status": AVAILABLE,
        "tools": ["q_factor_screen", "q_factor_alpha", "q_quality_score", "q_valuation"],
        "honest_limit": (
            "Premia are measured in decades and have gone missing for ten years "
            "at a time — value from 2010 to 2020 is the standard example. A "
            "factor tilt is a bet you must be able to hold through being wrong "
            "for longer than you expect."
        ),
    },
    "volatility_targeting": {
        "name": "Volatility targeting / risk parity sizing",
        "practitioners": ["Bridgewater", "Man AHL", "most CTAs"],
        "mechanism": (
            "Size positions by volatility rather than conviction, so each "
            "position contributes similar risk. Halve the position when "
            "volatility doubles."
        ),
        "needs": "Daily returns. It is a SIZING rule, not a signal.",
        "status": AVAILABLE,
        "tools": ["risk_estimate", "q_indicators"],
        "honest_limit": (
            "Improves risk-adjusted return, not raw return, and it de-risks "
            "into a crash by construction — which is the point, and also why it "
            "underperforms in a V-shaped recovery."
        ),
    },
    "pod_risk_discipline": {
        "name": "Pod risk discipline — mechanical loss limits",
        "practitioners": ["Millennium", "Citadel", "Balyasny"],
        "mechanism": (
            "Hard, pre-committed drawdown limits per book. A pod that loses a "
            "set percentage is cut, regardless of the thesis. Capital flows to "
            "what is working."
        ),
        "needs": "Position tracking and a stop rule decided BEFORE entry.",
        "status": AVAILABLE,
        "tools": ["rg_status", "rg_positions", "rg_alerts", "rg_checklist", "risk_estimate"],
        "honest_limit": (
            "THE most transferable idea on this list and the least glamorous. "
            "Millennium's edge is not better forecasts — it is that losers are "
            "cut mechanically before they become fatal, by a rule nobody is "
            "allowed to argue with in the moment. This system's Risk Guard is "
            "the same idea; the hard part is obeying it, not building it."
        ),
    },
    "statistical_arbitrage": {
        "name": "Statistical arbitrage / pairs trading",
        "practitioners": ["Renaissance", "D.E. Shaw", "Two Sigma"],
        "mechanism": (
            "Trade the spread between historically-related instruments when it "
            "diverges, betting on convergence."
        ),
        "needs": (
            "At the daily horizon: cointegration testing. At the horizon that "
            "actually pays: tick data, low-latency execution, and shorting."
        ),
        "status": BUILDABLE,
        "tools": ["q_cointegration_pair", "q_pca_decompose"],
        "honest_limit": (
            "The daily-bar version is a distant cousin of what Renaissance "
            "does, not a small version of it. Real stat arb earns thousands of "
            "tiny edges through fast execution; at daily frequency the Taiwan "
            "round trip (~0.585%) eats a spread trade before it converges. "
            "Shorting is also not modelled anywhere in this system, and half of "
            "a pair trade is a short."
        ),
    },
    "index_enhancement": {
        "name": "Index enhancement (指數增強)",
        "practitioners": ["the dominant Chinese quant product; AQR-style tilts"],
        "mechanism": (
            "Track a benchmark closely and add modest factor alpha on top, "
            "measured as excess return against the index rather than absolute."
        ),
        "needs": "A benchmark series and factor scores. 0050 is already harvested.",
        "status": BUILDABLE,
        "tools": ["q_index_history", "q_factor_alpha", "q_backtest"],
        "honest_limit": (
            "The honest framing for most retail 'strategies': the question is "
            "not whether you made money, it is whether you beat 0050 after "
            "costs and tax. Most active approaches do not, and this framing "
            "makes that visible instead of hiding it in absolute returns."
        ),
    },
    "ml_alpha_ensemble": {
        "name": "Machine-learning alpha ensembles",
        "practitioners": ["Two Sigma", "Voleon", "High-Flyer (幻方)"],
        "mechanism": (
            "Combine many weak, individually-useless predictors into an "
            "ensemble, retrained continuously."
        ),
        "needs": (
            "Breadth — thousands of instruments or years of intraday data — so "
            "that out-of-sample validation is even possible."
        ),
        "status": OUT_OF_REACH,
        "tools": [],
        "honest_limit": (
            "Not a compute problem, a sample-size one. A few hundred Taiwan "
            "names of daily bars cannot support a model with many parameters: "
            "there is not enough independent data to distinguish a real pattern "
            "from a fitted one, and the validation would be the first thing to "
            "lie to you. High-Flyer's own history is the cautionary note — its "
            "returns compressed sharply when high-turnover quant crowded and "
            "regulators tightened, which is a capacity and crowding lesson, not "
            "a modelling one."
        ),
    },
    "high_frequency_market_making": {
        "name": "High-frequency market making",
        "practitioners": ["Citadel Securities", "Jane Street", "Renaissance (Medallion)"],
        "mechanism": "Quote both sides continuously; earn the spread; manage inventory.",
        "needs": "Exchange membership, co-location, sub-millisecond execution.",
        "status": OUT_OF_REACH,
        "tools": [],
        "honest_limit": (
            "You cannot approximate this by trading faster. The edge IS the "
            "position — being the counterparty everyone trades against, with "
            "fee structures and latency retail cannot buy. Medallion's ~66% "
            "annualised is inseparable from that position and from being closed "
            "to outside capital; it is not a strategy that was published and "
            "can be re-run."
        ),
    },
}

# Cross-school agreements among quantitative practitioners specifically. The
# `investing_principles` tool carries the universals every SCHOOL agrees on
# (margin of safety, know what you own, survival first); these are narrower —
# things systematic investors converge on that a discretionary reader may not
# have met. Kept separate rather than merged so the existing principle set stays
# what it claims to be: school-neutral.
QUANT_PRINCIPLES: list[dict] = [
    {
        "principle": "An edge is measured against a baseline, never against zero",
        "detail": (
            "A 58% win rate means nothing until you know that 56% of all bars "
            "rose over the same horizon. Most reported 'strategies' are the "
            "market with extra steps."
        ),
        "attributed_to": "universal in quant research; the first thing AQR-style work establishes",
        "enforced_by": "q_backtest returns `baseline` and `net_edge_vs_baseline_pct`",
    },
    {
        "principle": "Costs decide short-horizon strategies",
        "detail": (
            "Taiwan round trip is ~0.585% (0.1425% brokerage each way + 0.30% "
            "sell-side transaction tax). A 5-day rule averaging +0.4% gross is "
            "a losing strategy. Turnover is a cost, not a sign of effort."
        ),
        "attributed_to": "Bogle on costs; every systematic desk on turnover budgets",
        "enforced_by": "q_backtest subtracts costs and reports the net figure",
    },
    {
        "principle": "Diversification across UNCORRELATED bets is the only free lunch",
        "detail": (
            "Fifteen genuinely independent bets beat one good one. Fifteen "
            "Taiwan semiconductor names are approximately ONE bet — the "
            "correlation is what counts, not the ticker count."
        ),
        "attributed_to": "Dalio's 'Holy Grail'; Markowitz",
        "enforced_by": "q_pca_decompose and q_lead_lag expose shared factors",
    },
    {
        "principle": "Size by volatility, not by conviction",
        "detail": (
            "Conviction is unmeasurable and reliably miscalibrated. Volatility "
            "is measurable. Equal-risk sizing beats equal-dollar sizing."
        ),
        "attributed_to": "Bridgewater risk parity; CTA practice",
        "enforced_by": "risk_estimate sizes to a stated risk budget via ATR",
    },
    {
        "principle": "Cut losers by rule, not by judgement",
        "detail": (
            "The stop must be decided before entry, when you have nothing at "
            "stake. Millennium's structural advantage is that the rule is not "
            "negotiable in the moment."
        ),
        "attributed_to": "Millennium / Citadel pod risk management",
        "enforced_by": "Risk Guard (rg_*), and it never emits a buy signal",
    },
    {
        "principle": "Capacity decays edge",
        "detail": (
            "A strategy's returns shrink as money crowds in. Medallion closed "
            "to outside capital for exactly this reason. Any public strategy "
            "you can read about has already been partly arbitraged away."
        ),
        "attributed_to": "Renaissance's closure of Medallion; the quant crowding literature",
        "enforced_by": "nothing — it is a reason for humility about any result",
    },
    {
        "principle": "Out-of-sample, or it is not a result",
        "detail": (
            "A threshold chosen by looking at the data and then measured on the "
            "same data describes that sample. Adding conditions until the "
            "numbers improve is fitting noise, and the tell is the effective "
            "sample size falling as you add them."
        ),
        "attributed_to": "universal; the reason most published backtests do not replicate",
        "enforced_by": "q_backtest reports n_effective and names in-sample tuning in `caveats`",
    },
]


def describe(key: str) -> dict | None:
    """One strategy, or None if the key is unknown."""
    entry = STRATEGIES.get((key or "").strip().lower())
    return {"key": key, **entry} if entry else None


def by_status(status: str) -> list[str]:
    want = (status or "").strip().lower()
    return [k for k, v in STRATEGIES.items() if v["status"] == want]
