"""Honest evaluation of a signal rule's historical record.

WHY THIS MODULE EXISTS. `q_backtest` reported hit-rate and average forward
return and nothing else. Every one of the following was missing, and every one
of them biases the answer in the SAME direction — optimistic:

1. **No baseline.** A 58% hit rate is meaningless alone. If the universe rose
   over 56% of all 5-day windows in the same period, the rule's edge is two
   points, not fifty-eight. This is the single most misleading omission: it
   turns "the market went up" into "my signal works".
2. **No transaction costs.** Taiwan charges 0.1425% brokerage per side plus a
   0.3% securities transaction tax on the sell. A round trip is ~0.585% before
   slippage. A 5-day rule averaging +0.4% is a LOSING rule; the old output
   reported it as a winner.
3. **Overlapping windows inflate n.** A name satisfying RSI<30 on six
   consecutive days contributes six observations whose 5-day forward windows
   almost entirely overlap. They are not six independent facts.
4. **Cross-sectional correlation inflates n further.** Taiwan semis move
   together; 200 triggers on one date is closer to one observation than to 200.
   Clustering by DATE handles 3 and 4 at once and is the conservative choice.
5. **No interval.** A point estimate from 40 effective observations was
   presented with the same confidence as one from 4,000.

The module is PURE — lists in, dict out, no DB, no clock — for the same reason
`rg/` and `position_risk.py` are: a number nobody can re-derive from stated
inputs is one nobody should trade on.

WHAT IT STILL CANNOT FIX, and says so in `caveats` rather than hiding:
survivorship. `raw_twse_ohlcv` holds the universe as classified TODAY, applied
backwards. A name added because it became important contributes its whole prior
history, and names that were dropped contribute none. That bias is upward and
is NOT corrected here — correcting it needs point-in-time universe membership,
which this repo does not record.
"""

from __future__ import annotations

import math

# Taiwan round-trip friction, in percent of notional.
#   brokerage    0.1425% per side  x2  = 0.285%   (full rate; brokers discount,
#                                                  commonly to ~0.06-0.09%/side)
#   transaction  0.30% on the SELL only = 0.300%  (securities transaction tax)
# Slippage is NOT included — it is strategy- and size-dependent, and inventing
# a number would be worse than naming its absence.
BROKERAGE_PCT_PER_SIDE = 0.1425
SELL_TAX_PCT = 0.30
ROUND_TRIP_COST_PCT = round(BROKERAGE_PCT_PER_SIDE * 2 + SELL_TAX_PCT, 4)

# Below this many INDEPENDENT observations, a hit rate is decoration.
MIN_EFFECTIVE_N = 30


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion, in percent.

    Wilson rather than the normal approximation because the normal one is badly
    wrong exactly where this tool is most dangerous — small n and proportions
    near 0 or 1, where it can produce bounds outside [0, 100].
    """
    if n <= 0:
        return (0.0, 100.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (
        round(max(0.0, centre - margin) * 100, 2),
        round(min(1.0, centre + margin) * 100, 2),
    )


def effective_sample_size(dates: list[str]) -> int:
    """Independent observations ≈ distinct trigger DATES.

    Deliberately conservative. The alternative — treating every (ticker, date)
    as independent — is what let a rule firing across 200 correlated names on
    one afternoon report n=200. Clustering by date collapses both the
    overlapping-window problem and the cross-sectional-correlation problem into
    one number that cannot overstate the evidence.
    """
    return len(set(dates))


def summarize(
    observations: list[dict],
    baseline: dict | None = None,
    cost_pct: float = ROUND_TRIP_COST_PCT,
) -> dict:
    """Turn raw trigger observations into an honest record.

    Args:
        observations: [{"ticker_id", "date", "pct_return"}, ...] — one row per
            trigger, `pct_return` already measured over the forward window.
        baseline: {"avg_return_pct", "hit_rate_pct", "n"} for the SAME window
            and universe with no condition applied. None if unavailable, in
            which case the edge fields report None rather than a guess.
        cost_pct: round-trip friction to subtract. Override for a discounted
            brokerage rate.

    Returns a dict whose `verdict` is safe to read aloud.
    """
    if not observations:
        return {
            "n_observations": 0,
            "verdict": "No triggers in the window — nothing to evaluate.",
            "caveats": _caveats(0, 0),
        }

    returns = [float(o["pct_return"]) for o in observations]
    dates = [str(o["date"]) for o in observations]
    n = len(returns)
    n_eff = effective_sample_size(dates)
    winners = sum(1 for r in returns if r > 0)
    hit_rate = 100.0 * winners / n
    avg = sum(returns) / n

    # The interval uses the EFFECTIVE n. Using the raw n here would reintroduce
    # the whole problem in the one number people read as rigour.
    eff_winners = int(round(winners * n_eff / n))
    lo, hi = wilson_interval(eff_winners, n_eff)

    net_avg = avg - cost_pct

    out = {
        "n_observations": n,
        "n_effective": n_eff,
        "n_distinct_tickers": len({str(o["ticker_id"]) for o in observations}),
        "hit_rate_pct": round(hit_rate, 2),
        "hit_rate_ci95_pct": [lo, hi],
        "avg_return_pct": round(avg, 3),
        "median_return_pct": round(_median(returns), 3),
        "best_return_pct": round(max(returns), 3),
        "worst_return_pct": round(min(returns), 3),
        "round_trip_cost_pct": cost_pct,
        "net_avg_return_pct": round(net_avg, 3),
    }

    if baseline and baseline.get("n"):
        b_avg = float(baseline["avg_return_pct"])
        b_hit = float(baseline["hit_rate_pct"])
        out["baseline"] = {
            "avg_return_pct": round(b_avg, 3),
            "hit_rate_pct": round(b_hit, 2),
            "n": baseline["n"],
            "meaning": (
                "every bar in the same window and universe, no condition "
                "applied — what you would have got by picking at random"
            ),
        }
        out["edge_vs_baseline_pct"] = round(avg - b_avg, 3)
        out["hit_rate_edge_pp"] = round(hit_rate - b_hit, 2)
        out["net_edge_vs_baseline_pct"] = round(avg - b_avg - cost_pct, 3)
    else:
        out["baseline"] = None
        out["edge_vs_baseline_pct"] = None
        out["hit_rate_edge_pp"] = None
        out["net_edge_vs_baseline_pct"] = None

    out["caveats"] = _caveats(n, n_eff)
    out["verdict"] = _verdict(out)
    return out


def _caveats(n: int, n_eff: int) -> list[str]:
    caveats = [
        "SURVIVORSHIP: the universe is the one classified TODAY, applied "
        "backwards. Names added because they became important carry their whole "
        "prior history; names dropped carry none. This bias is UPWARD and is "
        "not corrected — point-in-time universe membership is not recorded.",
        "IN-SAMPLE: thresholds tested here were usually chosen by looking at "
        "this same data. A rule tuned and measured on one sample is a "
        "description of that sample, not a prediction.",
        "Slippage is excluded from the cost figure; only brokerage and the "
        "sell-side transaction tax are modelled.",
    ]
    if n and n_eff < n:
        caveats.append(
            f"{n} raw triggers cluster into {n_eff} distinct dates. The "
            f"interval uses {n_eff}, because triggers sharing a date share a "
            f"market and their forward windows overlap."
        )
    return caveats


def _verdict(s: dict) -> str:
    """One sentence a persona can say out loud without overclaiming.

    Order matters: sample size is checked FIRST, because an impressive edge on
    nine effective observations is not a weak result, it is an absent one.
    """
    n_eff = s["n_effective"]
    if n_eff < MIN_EFFECTIVE_N:
        return (
            f"Only {n_eff} independent observations — not enough to conclude "
            f"anything. Treat as illustrative, not as evidence."
        )

    net_edge = s.get("net_edge_vs_baseline_pct")
    if net_edge is None:
        if s["net_avg_return_pct"] <= 0:
            return (
                f"Average {s['avg_return_pct']:+.2f}% before costs is "
                f"{s['net_avg_return_pct']:+.2f}% after the {s['round_trip_cost_pct']}% "
                f"round trip — the rule does not pay for its own trading."
            )
        return (
            f"{s['net_avg_return_pct']:+.2f}% average after costs, but with no "
            f"baseline to compare against this may just be the market rising."
        )

    if net_edge <= 0:
        return (
            f"No edge: {s['edge_vs_baseline_pct']:+.2f}% versus simply holding "
            f"the universe, which is {net_edge:+.2f}% once the "
            f"{s['round_trip_cost_pct']}% round trip is paid."
        )
    lo, hi = s["hit_rate_ci95_pct"]
    return (
        f"{net_edge:+.2f}% per trade over baseline after costs, from {n_eff} "
        f"independent observations; hit rate {s['hit_rate_pct']:.0f}% "
        f"(95% CI {lo:.0f}-{hi:.0f}%). Real but small edges are the normal "
        f"case — size accordingly."
    )
