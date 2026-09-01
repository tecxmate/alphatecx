"""Position risk — what a trade costs you when you are wrong.

This module exists because of one sentence from [niko]: "one is an opportunist
who can trade to make money. i know it's more risky. bake that in and estimate
the risk well." The aggressive persona is only defensible if the risk it takes
is QUANTIFIED, so the quantification is the product and the persona is the
framing over it.

Everything here is a PURE function over plain numbers — no DB, no clock, no
network — for the same reason `mcp_server/api/rg/` is pure: a risk number you
cannot re-derive deterministically from stated inputs is a number nobody should
size a position on.

WHAT THIS DELIBERATELY IS NOT
-----------------------------
Not a recommendation, and not a probability of profit. It answers only "if this
goes against you to your stop, what does that cost, and can you actually get
out?" — never "will it go up". The system's standing non-goal (never emit a
buy/sell/hold instruction) is unaffected: sizing math is arithmetic on the
user's OWN stated risk budget, not a view on direction.

THE TAIWAN-SPECIFIC PART, which generic risk models miss
--------------------------------------------------------
TWSE has a ±10% daily price limit. In a limit-down there is no bid: your stop
does not fill, and the loss is NOT bounded by your stop distance. Any honest
estimate of downside in this market has to say so, so `limit_down_gap_risk`
exists and every full estimate carries it.
"""

from __future__ import annotations

# TWSE/TPEX daily band. Kept as a plain constant rather than imported from
# limit_board: that module owns the tick-rounded PRICE, this one only needs the
# percentage to reason about the non-fill scenario.
DAILY_LIMIT_PCT = 10.0

# ATR multiple used when a caller gives no explicit stop. Matches
# momentum_leaders.DEFAULT_ATR_STOP_MULT so the two agree about what "the stop"
# means; a second, different default would produce two answers for one trade.
DEFAULT_ATR_STOP_MULT = 2.0

# Fraction of a day's turnover you can realistically take without moving the
# price. 10% is the common desk rule of thumb and is deliberately conservative
# for a retail size; it is stated in the output so a caller can disagree.
PARTICIPATION_CAP = 0.10


def _pos(x) -> float | None:
    """Coerce to a strictly positive float, else None.

    Zero and negative are treated as missing rather than clamped: a zero ATR or
    a zero price is bad data, and silently substituting a floor would produce a
    confident, wrong position size.
    """
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def atr_stop(close, atr, mult: float = DEFAULT_ATR_STOP_MULT) -> float | None:
    """Stop price `mult` ATRs below `close`, or None if inputs are unusable.

    Returns None rather than a stop at-or-below zero: a stop that cannot be
    reached is not a stop, and for a low-priced name with a large ATR that is
    exactly what naive arithmetic produces.
    """
    c, a = _pos(close), _pos(atr)
    if c is None or a is None:
        return None
    stop = c - mult * a
    return round(stop, 4) if stop > 0 else None


def position_size(account_value, risk_pct, entry, stop) -> dict:
    """How many shares risk exactly `risk_pct` of the account to the stop.

    The one piece of arithmetic that separates a survivable trading process
    from gambling, and the reason it belongs in the tool rather than the
    model's head:

        risk_budget = account_value * risk_pct/100
        risk_per_share = entry - stop
        shares = risk_budget / risk_per_share

    Returns `shares` as a float AND `lots` (Taiwan trades in 1,000-share lots),
    plus `lots_floor` — the tradeable size once you round DOWN. Rounding up
    would silently exceed the stated risk budget, which is the one number the
    caller asked to control.
    """
    av, rp = _pos(account_value), _pos(risk_pct)
    e, s = _pos(entry), _pos(stop)
    if av is None or rp is None or e is None or s is None:
        return {"error": "need positive account_value, risk_pct, entry and stop"}
    if s >= e:
        return {"error": "stop must be BELOW entry for a long position"}

    risk_budget = av * rp / 100.0
    risk_per_share = e - s
    shares = risk_budget / risk_per_share
    lots = shares / 1000.0
    lots_floor = int(lots)

    return {
        "risk_budget_twd": round(risk_budget, 2),
        "risk_per_share_twd": round(risk_per_share, 4),
        "stop_distance_pct": round((1 - s / e) * 100, 2),
        "shares": round(shares, 1),
        "lots": round(lots, 3),
        "lots_floor": lots_floor,
        "position_value_twd": round(lots_floor * 1000 * e, 2),
        "position_pct_of_account": round(lots_floor * 1000 * e / av * 100, 2),
        "actual_risk_twd": round(lots_floor * 1000 * risk_per_share, 2),
        "note": (
            "lots_floor rounds DOWN — rounding up would exceed the risk budget "
            "you specified. actual_risk_twd is what the tradeable size really "
            "puts at stake."
        ),
    }


def limit_down_gap_risk(entry, stop, account_value=None, lots=None) -> dict:
    """What a limit-down does to a stop, in this market specifically.

    TWSE's ±10% band means a stop below the limit-down price CANNOT fill that
    day — there is no bid. The position gaps through and the realised loss is
    set by where it eventually trades, not by the stop.

    Two regimes:
      stop_inside_band  — the stop sits above the limit-down price, so it can
                          fill on a normal-to-bad day. A limit-down still skips
                          it, but only on the extreme day.
      stop_below_band   — the stop is further away than one full daily limit,
                          so a single limit-down day jumps straight past it and
                          the stop provides no protection at all on that day.
    """
    e, s = _pos(entry), _pos(stop)
    if e is None or s is None:
        return {"error": "need positive entry and stop"}

    limit_price = round(e * (1 - DAILY_LIMIT_PCT / 100.0), 4)
    stop_inside = s > limit_price
    out = {
        "daily_limit_pct": DAILY_LIMIT_PCT,
        "limit_down_price": limit_price,
        "stop_price": round(s, 4),
        "stop_inside_daily_band": stop_inside,
        "one_limit_down_loss_pct": DAILY_LIMIT_PCT,
        "explanation": (
            "In a Taiwan limit-down there is no bid — a stop does not fill. "
            + ("Your stop is inside one day's band, so it can fill on an "
               "ordinary bad day; a limit-down would still skip it."
               if stop_inside else
               "Your stop is FURTHER than one full daily limit, so a single "
               "limit-down day gaps straight past it and the stop protects "
               "nothing that day.")
        ),
    }
    av, lt = _pos(account_value), _pos(lots)
    if av is not None and lt is not None:
        loss = lt * 1000 * e * DAILY_LIMIT_PCT / 100.0
        out["one_limit_down_loss_twd"] = round(loss, 2)
        out["one_limit_down_loss_pct_of_account"] = round(loss / av * 100, 2)
    return out


def liquidity_to_exit(lots, avg_daily_volume_shares,
                      participation: float = PARTICIPATION_CAP) -> dict:
    """Sessions needed to exit, at a realistic share of daily volume.

    A stop you cannot trade out of is decoration. This is the risk that bites
    hardest in the small/illiquid names an opportunist is most drawn to, and
    the one no price-based metric shows.
    """
    lt, adv = _pos(lots), _pos(avg_daily_volume_shares)
    if lt is None or adv is None:
        return {"error": "need positive lots and avg_daily_volume_shares"}
    shares = lt * 1000
    tradeable_per_day = adv * participation
    sessions = shares / tradeable_per_day
    return {
        "position_shares": round(shares),
        "avg_daily_volume_shares": round(adv),
        "participation_assumed_pct": round(participation * 100, 1),
        "pct_of_daily_volume": round(shares / adv * 100, 2),
        "sessions_to_exit": round(sessions, 2),
        "verdict": (
            "same-day exit realistic" if sessions <= 1
            else "needs multiple sessions — a fast exit will move the price"
        ),
    }


def estimate(*, entry, atr=None, stop=None, account_value=None, risk_pct=None,
             avg_daily_volume_shares=None,
             atr_stop_mult: float = DEFAULT_ATR_STOP_MULT) -> dict:
    """The whole picture, assembled from whatever inputs are available.

    Degrades by SECTION rather than failing whole: a caller with no volume data
    still gets sizing and limit-down risk, and `missing` names what could not be
    computed and why. Silence about an uncomputed risk reads as "no risk",
    which is the failure mode this module exists to prevent.
    """
    e = _pos(entry)
    if e is None:
        return {"error": "entry price is required and must be positive"}

    resolved_stop = _pos(stop) or atr_stop(e, atr, atr_stop_mult)
    basis = ("explicit" if _pos(stop) else
             f"atr_x{atr_stop_mult}" if resolved_stop else None)

    out: dict = {
        "entry": round(e, 4),
        "stop": resolved_stop,
        "stop_basis": basis,
        "assumptions": {
            "atr_stop_mult": atr_stop_mult,
            "participation_cap_pct": PARTICIPATION_CAP * 100,
            "daily_limit_pct": DAILY_LIMIT_PCT,
        },
    }
    missing: list[str] = []

    if resolved_stop is None:
        missing.append(
            "stop — no explicit stop and no usable ATR, so nothing downstream "
            "can be sized. Supply a stop or a ticker with OHLCV history."
        )
        out["missing"] = missing
        return out

    out["limit_down_risk"] = limit_down_gap_risk(e, resolved_stop)

    if account_value is not None and risk_pct is not None:
        sizing = position_size(account_value, risk_pct, e, resolved_stop)
        out["sizing"] = sizing
        lots = sizing.get("lots_floor")
        if lots:
            out["limit_down_risk"] = limit_down_gap_risk(
                e, resolved_stop, account_value=account_value, lots=lots)
            if avg_daily_volume_shares is not None:
                out["liquidity"] = liquidity_to_exit(lots, avg_daily_volume_shares)
            else:
                missing.append(
                    "liquidity — no avg_daily_volume_shares, so 'can I get out' "
                    "is UNKNOWN, not fine."
                )
        elif "error" not in sizing:
            missing.append(
                "liquidity — the risk budget does not fund one whole 1,000-share "
                "lot at this stop distance."
            )
    else:
        missing.append(
            "sizing — no account_value / risk_pct, so position size and the "
            "TWD cost of being wrong are UNKNOWN."
        )

    if missing:
        out["missing"] = missing
    return out
