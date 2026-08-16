"""Pure scoring for `momentum_leaders_scan` — the momentum sibling of flow_leaders.

Where `flow_leaders` hunts cheap + accumulated + not-yet-run, this hunts strong
trends EARLY, and says when one has broken. Same shape as its sibling: this
module is pure functions over plain dicts, `db_v2.query_momentum_leaders` does
the SQL, `index.py` wires the tool. Keeping the judgment out of SQL is what
makes the acceptance cases in the spec testable without a database.

THE TWO ENGINES MUST NOT CONTAMINATE EACH OTHER. Their logic is inverted on
purpose and sharing helpers between them would quietly break both:

    high P/E        sleeper: anti-flag        momentum: irrelevant, you are
                                              paying for the trend
    price not run   sleeper: a requirement    momentum: disqualifying — it wants
                                              an established trend
    exit            sleeper: thesis-driven    momentum: mechanical stop, no
                                              discretion

The doctrine that makes this tool safe rather than a blow-off chaser:

  1. Enter trends early. The parabolic guard is the single most important line
     of code here — it is what makes the same stock an `entry` in June and a
     `chase` in August.
  2. Require institutions to be buying WITH the move. That is the whole
     retail-pump filter; without it this becomes a meme scanner.
  3. Never emit an entry without a stop. Momentum's math is small losses and
     big wins, so the stop IS the strategy: `score_row` downgrades any candidate
     whose stop cannot be computed, rather than emitting a naked entry.
"""
from __future__ import annotations

from typing import Any

# ── Score weights (sum to 100) ──────────────────────────────────────────────
W_RELATIVE_STRENGTH = 30.0   # the core momentum factor — outperformance persists
W_TREND_STRUCTURE = 25.0     # established uptrend, not a bounce
W_BREAKOUT_QUALITY = 20.0    # real breakouts carry volume; dry ones fail
W_INST_CONFIRMATION = 15.0   # separates a trend from a retail pump
W_EARNINGS_MOMENTUM = 10.0   # fundamental fuel behind the price

# ── Thresholds ──────────────────────────────────────────────────────────────
BREAKOUT_VOLUME_MULT = 1.5   # volume vs 20-day average for a *valid* breakout
CLIMAX_VOLUME_MULT = 3.0     # ... and beyond which it reads as exhaustion
# "closed well off its high": at or below this point in the day's range. A
# climax bar is defined by the close giving back the move, not by volume alone —
# huge volume with a close AT the high is accumulation, not distribution.
CLIMAX_CLOSE_POSITION = 0.35
DEFAULT_ATR_STOP_MULT = 2.5
MA50_STOP_FLOOR_MULT = 0.97  # trend-based floor sits just under the 50-day
ENTRY_SCORE_MIN = 70.0       # below this a clean setup is still only a `watch`
R_MULTIPLE_TARGET = 2.5      # first target at 2-3x the stop distance

TRIAGE_ENTRY = "momentum-entry"
TRIAGE_WATCH = "watch"
TRIAGE_CHASE = "chase"


def _f(v: Any) -> float | None:
    """Coerce to float, or None. Mirrors flow_leaders._f deliberately: both
    scorers read the same LEFT-JOINed rows where any column may be absent."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # NaN is not a number we can score


def clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ── Components ──────────────────────────────────────────────────────────────

def extension_above_ma50_pct(row: dict) -> float | None:
    """How far price has run above its 50-day mean, in percent.

    The parabola metric. A name 75% above its 50-day average is not early in a
    trend however good the trend is — it is late, and the risk/reward has
    already inverted.
    """
    close, ma50 = _f(row.get("close")), _f(row.get("ma_50"))
    if close is None or not ma50:
        return None
    return (close / ma50 - 1.0) * 100.0


def trend_structure(row: dict) -> tuple[float, str]:
    """0-1 on stacked, rising moving averages, plus a human description.

    Full marks need price > MA50 > MA200 *and* both rising. Stacked-but-flat is
    a partial score: the structure is there but the trend has stopped paying.
    """
    close = _f(row.get("close"))
    ma50, ma200 = _f(row.get("ma_50")), _f(row.get("ma_200"))
    ma50_prev, ma200_prev = _f(row.get("ma_50_prev")), _f(row.get("ma_200_prev"))
    if close is None or ma50 is None or ma200 is None:
        return 0.0, "insufficient history for 50/200-day structure"

    stacked = close > ma50 > ma200
    rising50 = ma50_prev is not None and ma50 > ma50_prev
    rising200 = ma200_prev is not None and ma200 > ma200_prev

    if stacked and rising50 and rising200:
        return 1.0, "50>200, both rising"
    if stacked and rising50:
        return 0.75, "50>200, 50-day rising"
    if stacked:
        return 0.5, "50>200, flat"
    if close > ma50:
        return 0.25, "above 50-day but 50<200"
    return 0.0, "below the 50-day"


def breakout_quality(row: dict) -> tuple[float, str]:
    """0-1 on "new multi-month high, carried by volume".

    Volume is the discriminator. A breakout to a new high on *below*-average
    volume is the classic failure pattern: nobody is actually buying it.
    """
    close = _f(row.get("close"))
    high_3m = _f(row.get("high_3m"))
    vol_ratio = _f(row.get("volume_ratio_20"))
    if close is None or high_3m is None:
        return 0.0, "no breakout reference"

    at_high = close >= high_3m * 0.995   # within a rounding tick of the high
    if not at_high:
        pct = (close / high_3m - 1.0) * 100.0 if high_3m else 0.0
        return 0.15, f"{pct:.1f}% from the 3M high"
    if vol_ratio is None:
        return 0.5, "new 3M high, volume unknown"
    if vol_ratio >= BREAKOUT_VOLUME_MULT:
        return 1.0, f"new 3M high on {vol_ratio:.1f}x volume"
    return 0.35, f"new 3M high but only {vol_ratio:.1f}x volume"


def inst_confirmation(row: dict) -> tuple[bool, float]:
    """(confirmed, 0-1). Are foreign and/or trust buying WITH the trend?

    This is the retail-pump filter and the reason this tool will not become a
    meme chaser. Either institution buying counts — 投信 alone often leads a
    domestic theme — but foreign *selling* into strength is distribution and
    scores zero however hard the price is ripping.
    """
    foreign = _f(row.get("foreign_trend_net"))
    trust = _f(row.get("trust_trend_net"))
    if foreign is None and trust is None:
        return False, 0.0

    f_buy = (foreign or 0.0) > 0
    t_buy = (trust or 0.0) > 0
    f_sell = (foreign or 0.0) < 0

    if f_buy and t_buy:
        return True, 1.0
    if f_buy or t_buy:
        # Trust buying while foreign sells is contested, not confirmed — the
        # 晟田 pattern is exactly 投信 buying into foreign distribution.
        return (not f_sell), (0.4 if f_sell else 0.7)
    return False, 0.0


def earnings_momentum(row: dict) -> tuple[float, str]:
    """0-1 on revenue growth, accelerating if we can see the prior month.

    Reported but never gating: price can lead the fundamentals by a quarter, and
    demanding confirmed acceleration would filter out the early entries this
    tool exists to find.
    """
    yoy = _f(row.get("rev_yoy_pct"))
    yoy_prev = _f(row.get("rev_yoy_pct_prev"))
    if yoy is None:
        return 0.0, "no revenue read"
    if yoy <= 0:
        return 0.0, f"revenue YoY {yoy:+.0f}%"
    accelerating = yoy_prev is not None and yoy > yoy_prev
    base = clip(yoy / 40.0, 0.0, 1.0)        # +40% YoY saturates the component
    if accelerating:
        return clip(base + 0.2, 0.0, 1.0), f"revenue YoY {yoy:+.0f}%, accelerating"
    return base * 0.8, f"revenue YoY {yoy:+.0f}%"


# ── The anti-flags (any one forces `chase`) ─────────────────────────────────

def anti_flags(row: dict, *, max_extension_pct: float,
               min_base_days: int) -> list[str]:
    """Reasons this is a chase, not an entry — regardless of how good it scores.

    These are hard gates, deliberately evaluated independently of the score. A
    parabolic name scores WELL on relative strength and breakout quality; that
    is precisely why the score alone cannot be trusted to reject it.
    """
    flags: list[str] = []

    ext = extension_above_ma50_pct(row)
    parabolic = ext is not None and ext > max_extension_pct
    if parabolic:
        flags.append("parabolic")

    base_days = row.get("base_days_before_leg")
    if base_days is not None and int(base_days) < min_base_days:
        flags.append("no_base")

    # Distribution into strength: price ripping while foreign sells. Trust
    # buying alongside does NOT redeem it — that is the pattern, not a defence.
    foreign = _f(row.get("foreign_trend_net"))
    ret = _f(row.get("trend_return_pct"))
    if foreign is not None and foreign < 0 and ret is not None and ret > 0:
        flags.append("retail_pump")

    vol_ratio = _f(row.get("volume_ratio_20"))
    close, high, low = _f(row.get("close")), _f(row.get("high")), _f(row.get("low"))
    if vol_ratio is not None and vol_ratio > CLIMAX_VOLUME_MULT:
        if close is not None and high is not None and low is not None and high > low:
            position = (close - low) / (high - low)
            if position <= CLIMAX_CLOSE_POSITION:
                flags.append("climax_volume")

    # A limit-up lock is only a warning when the name is ALREADY extended: an
    # early-trend limit-up is one of the better entries there is.
    if row.get("limit_up") and parabolic:
        flags.append("limit_locked_extended")

    return flags


# ── The stop (non-negotiable) ──────────────────────────────────────────────

def trailing_stop(row: dict, *, atr_stop_mult: float = DEFAULT_ATR_STOP_MULT,
                  for_entry: bool = True
                  ) -> tuple[float | None, str | None, float | None]:
    """(stop, basis, distance_pct) — the tightest of three candidate stops.

    max() of the three because each is a floor the trend should not breach, so
    the binding one is the highest. Whichever binds is reported, because "why is
    my stop here" must be answerable before the trade, not after.

    `for_entry` matters more than it looks. Sizing a NEW position, a stop above
    the current price is nonsensical, so those candidates are discarded and
    (None, None, None) means "no entry stop can be placed" — price is already
    under its own trend floor, and `score_row` refuses to call that an entry.

    MONITORING a held position it is the exact opposite: price having fallen
    through the swing low IS the stop being hit, and discarding that candidate
    would silently slide the stop down and report "hold" forever. The exit
    signal this mode exists to produce could never fire. So monitor mode keeps
    every candidate and lets the caller compare it against the close.
    """
    close = _f(row.get("close"))
    if close is None or close <= 0:
        return None, None, None

    candidates: list[tuple[float, str]] = []
    atr = _f(row.get("atr_14"))
    if atr is not None and atr > 0:
        candidates.append((close - atr_stop_mult * atr, "atr"))
    swing = _f(row.get("recent_swing_low"))
    if swing is not None and swing > 0:
        candidates.append((swing, "swing_low"))
    ma50 = _f(row.get("ma_50"))
    if ma50 is not None and ma50 > 0:
        candidates.append((ma50 * MA50_STOP_FLOOR_MULT, "ma50"))

    usable = [(s, b) for s, b in candidates
              if s > 0 and (s < close or not for_entry)]
    if not usable:
        return None, None, None

    stop, basis = max(usable, key=lambda sb: sb[0])
    return round(stop, 2), basis, round((close - stop) / close * 100.0, 2)


# ── Scoring + triage ────────────────────────────────────────────────────────

def score_row(
    row: dict,
    *,
    min_rs_percentile: float = 80.0,
    require_inst_confirm: bool = True,
    max_extension_pct: float = 40.0,
    min_base_days: int = 5,
    atr_stop_mult: float = DEFAULT_ATR_STOP_MULT,
) -> dict:
    """Score one enriched row into a candidate with a triage verdict.

    Order matters: anti-flags are checked against the raw row and win outright.
    A blow-off top scores high on the momentum components by construction, so
    letting the score arbitrate would produce exactly the behaviour this tool
    exists to prevent.
    """
    rs_pct = _f(row.get("rs_percentile"))
    trend_score, trend_desc = trend_structure(row)
    brk_score, brk_desc = breakout_quality(row)
    confirmed, inst_score = inst_confirmation(row)
    earn_score, earn_desc = earnings_momentum(row)

    score = (
        W_RELATIVE_STRENGTH * clip((rs_pct or 0.0) / 100.0, 0.0, 1.0)
        + W_TREND_STRUCTURE * trend_score
        + W_BREAKOUT_QUALITY * brk_score
        + W_INST_CONFIRMATION * inst_score
        + W_EARNINGS_MOMENTUM * earn_score
    )

    flags = anti_flags(row, max_extension_pct=max_extension_pct,
                       min_base_days=min_base_days)
    stop, basis, dist = trailing_stop(row, atr_stop_mult=atr_stop_mult)

    if flags:
        triage = TRIAGE_CHASE
    elif (
        score >= ENTRY_SCORE_MIN
        and rs_pct is not None and rs_pct >= min_rs_percentile
        and (confirmed or not require_inst_confirm)
        # §8: never an entry without a stop. A momentum book without stops is
        # just a bag of losers, so an unplaceable stop downgrades to watch.
        and stop is not None
    ):
        triage = TRIAGE_ENTRY
    else:
        triage = TRIAGE_WATCH

    out = {
        "ticker_id": row.get("ticker_id"),
        "name": row.get("name"),
        "market": row.get("market"),
        "momentum_score": round(score, 1),
        "triage": triage,
        "rs_percentile": round(rs_pct, 1) if rs_pct is not None else None,
        "trend": trend_desc,
        "breakout": brk_desc,
        "extension_above_ma50_pct": _round(extension_above_ma50_pct(row)),
        "base_days_before_leg": row.get("base_days_before_leg"),
        "foreign_trend_net": row.get("foreign_trend_net"),
        "trust_trend_net": row.get("trust_trend_net"),
        "inst_confirmed": confirmed,
        "rev_yoy_pct": _round(_f(row.get("rev_yoy_pct"))),
        "earnings": earn_desc,
        # Reported, never gating — momentum names are expensive by nature and
        # that is what you are paying for. (In flow_leaders a high P/E is an
        # anti-flag; keeping the inversion explicit stops the two engines
        # bleeding into one another.)
        "pe_ratio": _round(_f(row.get("pe_ratio"))),
        "trailing_stop": stop,
        "stop_basis": basis,
        "stop_distance_pct": dist,
        "flags": flags,
    }
    if stop is not None and dist is not None:
        close = _f(row.get("close")) or 0.0
        out["r_multiple_target"] = round(close + R_MULTIPLE_TARGET * (close - stop), 2)
    return out


def _round(v: float | None, places: int = 2) -> float | None:
    return None if v is None else round(v, places)


def monitor_row(row: dict, *, atr_stop_mult: float = DEFAULT_ATR_STOP_MULT) -> dict:
    """`mode="monitor"`: re-compute the stop for a held name and say whether it
    has broken.

    Deliberately NOT a re-score. A held momentum position has exactly one
    question — is the trend still intact — and answering it with a fresh score
    invites re-justifying a loser as a "watch". `stop_hit` is the exit signal
    and carries no discretion.
    """
    stop, basis, dist = trailing_stop(row, atr_stop_mult=atr_stop_mult,
                                      for_entry=False)
    close = _f(row.get("close"))
    hit = stop is not None and close is not None and close <= stop
    return {
        "ticker_id": row.get("ticker_id"),
        "name": row.get("name"),
        "close": close,
        "trailing_stop": stop,
        "stop_basis": basis,
        "stop_distance_pct": dist,
        "stop_hit": hit,
        "action": "exit — trend broke" if hit else "hold — trend intact",
    }
