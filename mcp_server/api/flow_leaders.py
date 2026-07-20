"""Market-wide foreign-accumulation screener (the 拓凱 signature).

`flow_leaders_scan` looks for the pattern that precedes a move rather than
confirming one after it: sustained institutional net buying into a price that
has *not yet run*, in a name that is still cheap and under-owned. This is the
"generative" half of the board tools — `scan_limit_board` triages what already
moved; this finds what is being quietly accumulated first.

This module is the pure scoring layer. The heavy per-ticker aggregation lives
in ``db_v2.query_flow_leaders`` (one market-wide SQL pass); everything here is
a deterministic function of one already-aggregated row, so it is unit-tested
directly against the two non-negotiable acceptance cases (see
tests/test_flow_leaders.py):

  * 拓凱 (4536) as of 2026-06-30 must score into the top of the board and
    triage ``sleeper`` — ~7 weeks of foreign net buying (+~1.0M shares) while
    the price sat flat ~160-167, PE ~12.4, foreign held ~12.5%, margin ~0.
  * 日馳 (1526) as of 2026-07-17 must triage ``chase`` — it ran +~18% on
    foreign *selling* with no earnings.

Two deliberate deviations from the handoff spec, both forced by 拓凱:

  1. **Flatness is median-anchored, not endpoint-to-endpoint.** A single
     corrupt TWSE print (4536 closed 87.3 on 2026-05-13, sandwiched by ~152)
     blows up any max/min- or first/last-based range. `price_move_pct` is
     measured as *latest vs the window median* and `price_range_pct` as
     *(p90-p10)/median* — a lone bad tick cannot move either.

  2. **Single-day z-score does not gate selection.** The handoff's
     `min_foreign_z=1.0` would exclude 拓凱, whose *final-day* foreign_net_z20
     is ~-0.4: a multi-week grind has no closing-day spike. The accumulation
     signal is the **buy-day ratio + cumulative net**, not one day's z. `z20`
     is kept as a minor score input and an optional (non-default) filter only.
"""
from __future__ import annotations

from typing import Any, Optional

# ── Score weights (0-100), per handoff §3a ──────────────────────────────────
# The two make-or-break signals — accumulation and not-yet-run — carry the most.
W_ACCUMULATION = 35.0   # buy-day ratio + positive cumulative net + z spike
W_FLATNESS = 25.0       # price has not run yet
W_VALUATION = 20.0      # cheap PE / PB / real yield
W_UNDER_OWNED = 10.0    # foreign under-owned, room to buy
W_NO_FROTH = 5.0        # margin ≈ 0, no retail leverage froth
W_REVENUE = 5.0         # monthly revenue YoY turning up

# Flag / triage thresholds (mirror scan_limit_board's apply_triage vocabulary
# so both board tools speak the same rubric — see references/screening.md).
CHEAP_PE_MAX = 20.0
YIELD_MIN = 3.0
UNDER_OWNED_PCT = 20.0
STORY_PREMIUM_PE = 40.0
RAN_HARD_PCT = 30.0
NO_FROTH_MARGIN_USAGE_PCT = 5.0


def clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _f(v: Any) -> Optional[float]:
    """Coerce a possibly-Decimal / possibly-None cell to float or None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def price_move_pct(row: dict) -> Optional[float]:
    """Latest close vs the window *median* — how far above the recent typical
    level the price sits. Median-anchored so one corrupt print can't distort it.
    """
    latest = _f(row.get("close_today"))
    med = _f(row.get("med_close"))
    if latest and med:
        return (latest / med - 1.0) * 100.0
    return None


def price_range_pct(row: dict) -> Optional[float]:
    """(p90 - p10) / median as a robust window range, ignoring the tails where
    a single bad tick would otherwise land."""
    p10 = _f(row.get("p10"))
    p90 = _f(row.get("p90"))
    med = _f(row.get("med_close"))
    if p10 is not None and p90 is not None and med:
        return (p90 - p10) / med * 100.0
    return None


def margin_usage_pct(row: dict) -> Optional[float]:
    """Margin balance as a % of the exchange-set margin limit — a proxy for
    retail leverage froth. None when either side is missing."""
    bal = _f(row.get("margin_balance"))
    limit = _f(row.get("margin_limit"))
    if bal is not None and limit:
        return bal / limit * 100.0
    return None


def score_row(
    row: dict,
    *,
    window_days: int = 20,
    max_price_move_pct: float = 8.0,
    max_pe: float = 20.0,
    max_foreign_held: float = 25.0,
    min_buy_day_ratio: float = 0.65,
) -> dict:
    """Score one aggregated ticker row and attach the derived signature.

    Returns a *new* dict = the input plus:
      price_move_pct, price_range_pct, margin_pct_of_limit,
      is_flat, accumulation_into_flat, sleeper_score,
      sleeper_flags, triage.

    Pure and total: every missing enrichment field simply fails its own test
    instead of raising, exactly as scan_limit_board.apply_triage does. The one
    asymmetry is `pe_ratio is None` — where a valuation row exists that means
    "no positive earnings" (an anti-flag); where it does not (TPEX gap) it must
    not be read as loss-making. `valuation_known` carries that distinction.
    """
    fnet_sum = _f(row.get("foreign_net_sum"))
    buy_ratio = _f(row.get("buy_day_ratio"))
    z20 = _f(row.get("foreign_net_z20"))
    pe = _f(row.get("pe_ratio"))
    pb = _f(row.get("pb_ratio"))
    yld = _f(row.get("dividend_yield"))
    held = _f(row.get("foreign_held_pct"))
    rev_yoy = _f(row.get("revenue_yoy_pct"))
    valuation_known = bool(row.get("valuation_known"))

    move = price_move_pct(row)
    rng = price_range_pct(row)
    usage = margin_usage_pct(row)

    is_flat = move is not None and abs(move) <= max_price_move_pct
    accumulation_into_flat = bool(
        fnet_sum is not None and fnet_sum > 0
        and buy_ratio is not None and buy_ratio >= min_buy_day_ratio
        and is_flat
    )

    # ── accumulation strength (35) ──────────────────────────────────────────
    acc = 0.0
    if fnet_sum is not None and fnet_sum > 0:
        acc += 12.0
    if buy_ratio is not None:
        acc += 15.0 * clip((buy_ratio - 0.5) / 0.4, 0, 1)   # .50→0, .90→full
    if z20 is not None:
        acc += 8.0 * clip((z20 + 0.5) / 2.0, 0, 1)          # -.5→0, 1.5→full
    acc = clip(acc, 0, W_ACCUMULATION)

    # ── flatness / not-yet-run (25) ─────────────────────────────────────────
    flat = 0.0
    if move is not None:
        if abs(move) <= max_price_move_pct:
            flat = W_FLATNESS
        else:  # graded decay: full at threshold → 0 at 3× threshold
            flat = W_FLATNESS * clip(
                1 - (abs(move) - max_price_move_pct) / (2 * max_price_move_pct), 0, 1
            )
    if rng is not None and rng > 40:   # choppy even if the endpoints look flat
        flat *= 0.6

    # ── valuation (20) ──────────────────────────────────────────────────────
    val = 0.0
    if pe is not None and pe > 0:
        val += 12.0 * clip((max_pe - pe) / max_pe, 0, 1)
    if yld is not None:
        val += 5.0 * clip(yld / 5.0, 0, 1)
    if pb is not None and pb > 0:
        val += 3.0 * clip((3.0 - pb) / 3.0, 0, 1)
    val = clip(val, 0, W_VALUATION)

    # ── under-owned (10) ────────────────────────────────────────────────────
    under = 0.0
    if held is not None:
        under = W_UNDER_OWNED * clip((max_foreign_held - held) / max_foreign_held, 0, 1)

    # ── no leverage froth (5) ───────────────────────────────────────────────
    froth = W_NO_FROTH   # unknown margin ⇒ assume no froth (do not penalise)
    if usage is not None:
        froth = W_NO_FROTH * clip(1 - usage / 20.0, 0, 1)

    # ── revenue inflection (5) ──────────────────────────────────────────────
    revsc = W_REVENUE / 2   # unknown ⇒ neutral half-credit
    if rev_yoy is not None:
        revsc = W_REVENUE * clip((rev_yoy + 10.0) / 30.0, 0, 1)   # -10%→0, +20%→full

    sleeper_score = round(acc + flat + val + under + froth + revsc, 1)

    # ── flags + triage (same vocabulary as scan_limit_board) ────────────────
    flags: list[str] = []
    if accumulation_into_flat or (buy_ratio is not None and buy_ratio >= min_buy_day_ratio
                                  and fnet_sum is not None and fnet_sum > 0):
        flags.append("accumulating")
    if is_flat:
        flags.append("flat")
    if pe is not None and 0 < pe < CHEAP_PE_MAX:
        flags.append("cheap")
    if yld is not None and yld >= YIELD_MIN:
        flags.append("yield")
    if held is not None and held < UNDER_OWNED_PCT:
        flags.append("under_owned")
    if usage is not None and usage < NO_FROTH_MARGIN_USAGE_PCT:
        flags.append("no_froth")
    if rev_yoy is not None and rev_yoy > 0:
        flags.append("rev_inflecting")

    anti: list[str] = []
    if pe is None and valuation_known:
        anti.append("no_earnings")
    if pe is not None and pe > STORY_PREMIUM_PE:
        anti.append("story_premium")
    if fnet_sum is not None and fnet_sum < 0:
        anti.append("distributing")
    if move is not None and move > RAN_HARD_PCT:
        anti.append("already_ran")
    if buy_ratio is not None and buy_ratio < 0.5:
        anti.append("net_selling_days")

    flags.extend(anti)

    if anti:
        triage = "chase"
    elif {"cheap", "accumulating", "flat"} <= set(flags):
        triage = "sleeper"
    else:
        triage = "watch"

    return {
        **row,
        "price_move_pct": round(move, 2) if move is not None else None,
        "price_range_pct": round(rng, 2) if rng is not None else None,
        "margin_pct_of_limit": round(usage, 2) if usage is not None else None,
        "is_flat": is_flat,
        "accumulation_into_flat": accumulation_into_flat,
        "sleeper_score": sleeper_score,
        "sleeper_flags": flags,
        "triage": triage,
    }
