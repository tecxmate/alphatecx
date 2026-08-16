"""Taipei market session state (phase + trading-calendar awareness).

This exists to kill a whole error class at the source: mistaking a 試撮
(pre-open simulated auction) price for a real trade. During 08:30–09:00 the
book is uncrossed and the "price" can swing violently on a thin order book —
it is an indication, not a fill. Any quote surfaced in that window must be
stamped indicative, and any question about "is this price real?" is answered
here before a number is ever quoted.

The phase logic is pure and time-only (this module). Whether a given calendar
day trades at all — weekends, statutory holidays, and ad-hoc typhoon closures —
comes from the `market_holidays` table (see db_v2.query_market_closures), which
the tool layer feeds in as `is_trading_day`.

Regular-session hours (Asia/Taipei), TWSE/TPEX equities:
  08:30–09:00  pre_open_auction   (試撮 — indicative, price_is_indicative=true)
  09:00–13:30  regular            (continuous auction; odd-lot intraday too)
  13:30–14:30  after_hours        (after-hours fixed-price 14:00–14:30;
                                    odd-lot after-hours single call at 14:30)
  otherwise    closed
"""
from __future__ import annotations

from datetime import datetime, time

# Phase boundaries as naive Taipei clock times; the tz-aware `now` is compared
# on its local wall clock.
_PRE_OPEN_START = time(8, 30)
_OPEN = time(9, 0)
_CLOSE = time(13, 30)
_AFTER_HOURS_END = time(14, 30)

# Static reference map returned to the caller, so an agent reasoning about
# timing does not have to hard-code these itself.
PHASES_TODAY = {
    "pre_open_auction": "08:30-09:00",
    "regular": "09:00-13:30",
    "odd_lot_intraday": "09:00-13:30",
    "after_hours_fixed": "14:00-14:30",
    "after_hours_odd": "13:40-14:30 (single call auction at 14:30)",
}

_INDICATIVE_WARNING = (
    "試撮 — pre-open simulated auction. The displayed price is indicative and "
    "can swing violently on a thin book; it is not a trade. Do not treat it as "
    "a fill or a real quote."
)


def phase_for(now: datetime, is_trading_day: bool) -> tuple[str, bool, str | None]:
    """Return (phase, price_is_indicative, warning) for a Taipei-local `now`.

    On a non-trading day every clock time is `closed`; a caller must resolve
    `is_trading_day` from the calendar first — a holiday at 10:00 is still shut.
    """
    if not is_trading_day:
        return "closed", False, None

    t = now.timetz().replace(tzinfo=None) if now.tzinfo else now.time()
    if t < _PRE_OPEN_START:
        return "closed", False, None
    if t < _OPEN:
        return "pre_open_auction", True, _INDICATIVE_WARNING
    if t < _CLOSE:
        return "regular", False, None
    if t < _AFTER_HOURS_END:
        return "after_hours", False, None
    return "closed", False, None


def build_state(now: datetime, is_trading_day: bool, calendar_source: str) -> dict:
    """Assemble the full session-state payload.

    `now` must be Asia/Taipei tz-aware. `calendar_source` records how
    `is_trading_day` was decided ('calendar' when the holiday table answered,
    'weekend_only' when it was unavailable and only weekends were excluded) so
    the caller can tell a confirmed open day from a best-effort guess.
    """
    phase, indicative, warning = phase_for(now, is_trading_day)
    return {
        "taipei_time": now.isoformat(),
        "date": now.date().isoformat(),
        "weekday": now.strftime("%A"),
        "is_trading_day": is_trading_day,
        "phase": phase,
        "price_is_indicative": indicative,
        "phases_today": PHASES_TODAY,
        "calendar_source": calendar_source,
        "warning": warning,
    }
