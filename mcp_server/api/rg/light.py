"""M1 — light state machine (PRD §5 M1, v1.1 "綠燈解鎖條件").

The score→light table in the PRD reads like a pure mapping, but v1.1 adds
asymmetric hysteresis, and two rows of the replay table exist specifically to
catch an implementation that forgets it:

  7/30  −0.26% after −4.65% and −3.76%  → must stay red
  7/31  +8.0%                            → must not go green

Risk moves faster than safety, so the rule is asymmetric on purpose:
an upgrade toward red is immediate, a downgrade toward green must be earned.
Red also cannot skip yellow — recovery is walked, never jumped.
"""
from __future__ import annotations

from . import config as cfg

_RANK = {"green": 0, "yellow": 1, "red": 2}


def build_index_context(closes: list[float]) -> dict:
    """Derive the hysteresis inputs from a newest-first list of index closes.

    `closes[0]` is the session being scored. Two derived facts:

    up_streak
        Consecutive higher closes ending today. 7/31's +8% gives 1, not 3 —
        which is what makes a single violent up day a "candidate first day"
        rather than an unlock.

    held_above_prior_low_days
        Consecutive sessions whose close held above the prior low, where the
        prior low is the minimum of the `PRIOR_LOW_WINDOW` closes *before* that
        session. 7/30 closed 39933.3 under 7/29's 40039.18, so the streak is 0
        and red holds.
    """
    up_streak = 0
    for i in range(len(closes) - 1):
        if closes[i] > closes[i + 1]:
            up_streak += 1
        else:
            break

    held = 0
    for i in range(len(closes)):
        window = closes[i + 1: i + 1 + cfg.PRIOR_LOW_WINDOW]
        if not window:
            break
        if closes[i] > min(window):
            held += 1
        else:
            break

    return {"up_streak": up_streak, "held_above_prior_low_days": held}


def resolve_light(
    score: int,
    prev_light: str | None,
    ctx: dict,
    raw_light: str | None = None,
) -> tuple[str, str]:
    """Apply hysteresis to today's raw band. Returns (light, reason).

    Args:
        score: today's M1 score.
        prev_light: yesterday's published light, or None on a cold start.
        ctx: keys `prev_score`, `close_above_ma20`, `up_streak`,
             `held_above_prior_low_days`. Missing keys read as "not satisfied".
        raw_light: override for the band lookup (tests); defaults to the
             band implied by `score`.
    """
    from .scoring import light_from_score

    raw = raw_light or light_from_score(score)

    # Cold start, or the score got worse: publish the raw band immediately.
    if prev_light not in _RANK:
        return raw, "初次計算,直接採用分數燈號"
    if _RANK[raw] >= _RANK[prev_light]:
        return raw, "分數燈號不低於前一日,直接採用"

    # From here the raw band wants to relax. Every downgrade is one step.
    prev_score = ctx.get("prev_score")
    no_new_penalty = prev_score is None or score <= prev_score

    if prev_light == "red":
        held = ctx.get("held_above_prior_low_days") or 0
        if no_new_penalty and held >= cfg.RED_TO_YELLOW_HOLD_DAYS:
            return "yellow", f"紅轉黃:未新增扣分,且連 {held} 日不破前低"
        blocker = ("指數仍破前低" if held < cfg.RED_TO_YELLOW_HOLD_DAYS
                   else "子項扣分仍在增加")
        return "red", f"維持紅燈:{blocker}(需連 {cfg.RED_TO_YELLOW_HOLD_DAYS} 日不破前低)"

    if prev_light == "yellow":
        up_streak = ctx.get("up_streak") or 0
        above_ma20 = bool(ctx.get("close_above_ma20"))
        if no_new_penalty and (above_ma20 or up_streak >= cfg.YELLOW_TO_GREEN_UP_STREAK):
            unlock = f"站回 MA{cfg.MA_SHORT}" if above_ma20 else f"連 {up_streak} 日收高"
            return "green", f"黃轉綠:{unlock}"
        return "yellow", (
            f"維持黃燈:未站回 MA{cfg.MA_SHORT},且收高天數 {up_streak} < "
            f"{cfg.YELLOW_TO_GREEN_UP_STREAK}"
        )

    return raw, "分數燈號直接採用"
