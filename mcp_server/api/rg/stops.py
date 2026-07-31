"""M2 — stop-loss evaluation (PRD §5 M2).

Pure: takes monitored rows plus a close price per ticker, returns the alerts
that should fire. Deciding *what* fired is separate from *whether it was
already sent* — the caller owns de-duplication (the unique index on
rg_alerts (date, kind, ticker_id) is the backstop).

Only `kind='position'` rows are evaluated. A watch-list name has no cost basis
and no exit line to breach; alerting on it would train the operator to ignore
the channel, which is the one failure this module cannot afford.
"""
from __future__ import annotations

from . import config as cfg


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def effective_lines(position: dict) -> tuple[float | None, float | None, bool]:
    """Resolve (warn_price, exit_price, is_fallback) for one position.

    When no exit line was set, fall back to cost × (1 − hard_stop_pct/100) so a
    position is never silently unguarded — a forgotten line is the common case,
    not the exception. `is_fallback` is surfaced in the alert so the operator
    can tell a line they chose from one the system invented.
    """
    warn = _num(position.get("warn_price"))
    exit_price = _num(position.get("exit_price"))
    if exit_price is not None:
        return warn, exit_price, False

    cost = _num(position.get("cost"))
    if cost is None:
        return warn, None, False

    pct = _num(position.get("hard_stop_pct"))
    if pct is None:
        pct = cfg.DEFAULT_HARD_STOP_PCT
    return warn, round(cost * (1 - pct / 100.0), 2), True


def evaluate(positions: list[dict], closes: dict[str, float]) -> list[dict]:
    """Return stop alerts for today's official closes.

    Args:
        positions: rows from rg_positions.
        closes: ticker_id → official closing price. A ticker absent from this
                map is skipped rather than treated as a breach; a missing price
                is not evidence of anything.

    Each alert: kind (stop_warn | stop_exit), ticker_id, name, severity, close,
    line, line_is_fallback, action, distance_pct.
    """
    alerts: list[dict] = []
    for pos in positions:
        if pos.get("kind") != "position" or not pos.get("active", True):
            continue
        ticker = pos.get("ticker_id")
        close = _num(closes.get(ticker))
        if close is None:
            continue

        warn, exit_price, fallback = effective_lines(pos)

        # Exit dominates warn: below the exit line, halving is the wrong advice.
        if exit_price is not None and close <= exit_price:
            alerts.append({
                "kind": "stop_exit",
                "ticker_id": ticker,
                "name": pos.get("name"),
                "severity": "critical",
                "close": close,
                "line": exit_price,
                "line_is_fallback": fallback,
                "distance_pct": round((close / exit_price - 1) * 100, 2),
                "action": f"明天開盤全數出場。{cfg.CONDITIONAL_ORDER_ADVICE}",
            })
            continue

        if warn is not None and close <= warn:
            alerts.append({
                "kind": "stop_warn",
                "ticker_id": ticker,
                "name": pos.get("name"),
                "severity": "warn",
                "close": close,
                "line": warn,
                "line_is_fallback": False,
                "distance_pct": round((close / warn - 1) * 100, 2),
                "action": "明天開盤減半,並把出場線上移。",
            })

    return alerts


def unpriced(positions: list[dict], closes: dict[str, float]) -> list[dict]:
    """Active positions `evaluate` had to skip because no close was available.

    `evaluate` is right to stay silent on a missing price, but silence is the
    wrong *report*: "0 stop alerts" and "your stop was never checked" look
    identical from the outside, and a position believed guarded but unguarded is
    the worst state this system can be in.

    The common cause is coverage, not outage — `raw_twse_ohlcv` is harvested for
    the classified supply-chain universe plus the benchmark, so promoting an
    unclassified watch name to a position leaves it without prices.
    """
    return [
        p for p in positions
        if p.get("kind") == "position" and p.get("active", True)
        and _num(closes.get(p.get("ticker_id"))) is None
    ]


def distances(positions: list[dict], closes: dict[str, float]) -> list[dict]:
    """Per-position distance to its lines, for /pos and rg_positions().

    Read-only view of the same lines `evaluate` uses, so the dashboard can
    never disagree with the alert about where a stop sits.
    """
    out = []
    for pos in positions:
        ticker = pos.get("ticker_id")
        close = _num(closes.get(ticker))
        warn, exit_price, fallback = effective_lines(pos)
        row = {
            "ticker_id": ticker,
            "name": pos.get("name"),
            "kind": pos.get("kind"),
            "active": pos.get("active", True),
            "cost": _num(pos.get("cost")),
            "qty_lots": _num(pos.get("qty_lots")),
            "warn_price": warn,
            "exit_price": exit_price,
            "exit_is_fallback": fallback,
            "close": close,
            "note": pos.get("note"),
            "triggered": None,
            "pct_to_exit": None,
            "pct_from_cost": None,
        }
        if close is not None and exit_price:
            row["pct_to_exit"] = round((close / exit_price - 1) * 100, 2)
            row["triggered"] = (
                "exit" if close <= exit_price
                else "warn" if warn and close <= warn
                else None
            )
        if close is not None and row["cost"]:
            row["pct_from_cost"] = round((close / row["cost"] - 1) * 100, 2)
        out.append(row)
    return out
