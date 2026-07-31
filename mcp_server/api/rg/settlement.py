"""M2b — settlement cash check (PRD §5 M2b, added in v1.1).

Motivated by a real near-miss: on 7/24 the account was NT$26,211 short and the
broker's SMS landed at 14:02, after the market had closed and after any chance
to raise cash cheaply. The whole point of this module is to be earlier than
that SMS, so the check runs on the post-close pipeline and looks two trading
days ahead rather than reporting a shortfall on the morning it lands.

T+2 is counted in *trading* days: a Thursday buy settles Monday, and a holiday
inside the window pushes it further. The trading calendar is passed in rather
than derived here, so this module stays pure and the calendar stays one
authority (market_holidays, via session_state).
"""
from __future__ import annotations

import math

from . import config as cfg


def settle_date(trade_date: str, trading_days: list[str]) -> str | None:
    """The T+2 settlement date for a fill, or None if the calendar runs out.

    `trading_days` is an ascending list of ISO trading dates that must include
    `trade_date` and at least SETTLEMENT_LAG_DAYS sessions after it. Returning
    None rather than guessing is deliberate — a fabricated settlement date is
    worse than an admitted gap in the calendar.
    """
    try:
        i = trading_days.index(trade_date)
    except ValueError:
        return None
    j = i + cfg.SETTLEMENT_LAG_DAYS
    return trading_days[j] if j < len(trading_days) else None


def _fee(gross: float) -> float:
    """Brokerage, floored at the per-side minimum, truncated to whole TWD."""
    raw = gross * cfg.BROKER_FEE_RATE * cfg.BROKER_FEE_DISCOUNT
    return float(max(cfg.BROKER_FEE_MIN, math.floor(raw)))


def fill_amount(side: str, price: float, lots: float) -> float:
    """Signed settlement amount for one fill, in TWD.

    Negative = cash leaves the account. A buy pays gross + brokerage; a sell
    receives gross − brokerage − 0.3% transaction tax.
    """
    gross = float(price) * float(lots) * cfg.SHARES_PER_LOT
    fee = _fee(gross)
    if side == "buy":
        return -(gross + fee)
    tax = math.floor(gross * cfg.SECURITIES_TAX_RATE)
    return gross - fee - tax


def check_gap(
    schedule: list[dict],
    balance: float | None,
    today: str,
    trading_days: list[str],
) -> list[dict]:
    """Find settlement dates the reported balance cannot cover.

    Args:
        schedule: rows of {date, net_amount} — signed, negative = owed.
        balance: last reported settlement-account cash, or None if never given.
        today: ISO date the check runs on.
        trading_days: ascending ISO trading dates, used to count lead time.

    The running balance carries forward: an incoming sale on Monday funds a
    Tuesday purchase, which is how the account actually behaves. Only the next
    SETTLEMENT_LOOKAHEAD_DAYS settlement dates are examined.
    """
    if balance is None:
        return [{
            "kind": "settlement_gap",
            "severity": "warn",
            "date": today,
            "shortfall": None,
            "days_ahead": None,
            "action": "尚未回報交割戶餘額,無法檢查交割款。請用 /balance <金額> 更新。",
        }]

    upcoming = sorted(
        (r for r in schedule if str(r.get("date")) >= today),
        key=lambda r: str(r["date"]),
    )[: cfg.SETTLEMENT_LOOKAHEAD_DAYS]

    alerts: list[dict] = []
    running = float(balance)
    for row in upcoming:
        date = str(row["date"])
        running += float(row.get("net_amount") or 0)
        if running >= 0:
            continue

        shortfall = round(-running, 0)
        days_ahead = _sessions_between(today, date, trading_days)
        alerts.append({
            "kind": "settlement_gap",
            "severity": "critical",
            "date": date,
            "shortfall": shortfall,
            "days_ahead": days_ahead,
            "balance": float(balance),
            "action": (
                f"{date} 交割款不足 NT${shortfall:,.0f}。"
                f"請在該日 10:00 前補足,或今天先減碼。"
            ),
        })
    return alerts


def _sessions_between(start: str, end: str, trading_days: list[str]) -> int | None:
    """Trading sessions from `start` to `end`, or None if either is off-calendar."""
    try:
        return trading_days.index(end) - trading_days.index(start)
    except ValueError:
        return None
