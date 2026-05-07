"""Backtest harness — given a signal threshold, return forward-return stats.

This is the discipline tool: every quant signal must produce a hit-rate /
drawdown report from this harness before it gets wired into a digest.

Honest about thin data — if n_observations < 30, the report carries a
`sample_warning` and callers should treat hit-rate as illustrative, not
predictive. As more T86/OHLCV history accumulates, the same harness
produces stronger validation.

The first iteration covers single-threshold rules:
    "signal_name <op> threshold" → forward N-day return on close basis.

Compound rules (e.g. RSI < 30 AND price > SMA-200) come later when we
need them.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
from typing import Literal

from src.harvester.loader import cur

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("backtest")

Direction = Literal["below", "above"]


def backtest_threshold(
    signal_name: str,
    threshold: float,
    direction: Direction = "below",
    forward_days: int = 5,
    lookback_days: int = 365,
) -> dict:
    """Run a single-threshold backtest.

    Triggers when (value < threshold) or (value > threshold) depending on
    `direction`. Outcome = (forward_close / entry_close - 1) over the next
    `forward_days` trading days. Forward bar found via LEAD() so weekends
    and holidays don't break the lookup.
    """
    op = "<" if direction == "below" else ">"
    rule = f"{signal_name} {op} {threshold}"

    sql = f"""
        WITH triggers AS (
            SELECT s.ticker_id, s.date AS trigger_date, s.value AS signal_value
            FROM signal_value s
            WHERE s.signal_name = %s
              AND s.value {op} %s
              AND s.date >= current_date - (%s || ' days')::interval
        ),
        bars AS (
            SELECT
                ticker_id, date, close,
                LEAD(close, %s) OVER (PARTITION BY ticker_id ORDER BY date) AS forward_close
            FROM raw_twse_ohlcv
        )
        SELECT
            t.ticker_id, t.trigger_date, t.signal_value,
            b.close AS entry_close,
            b.forward_close,
            (b.forward_close / b.close - 1.0) * 100.0 AS pct_return
        FROM triggers t
        JOIN bars b ON b.ticker_id = t.ticker_id AND b.date = t.trigger_date
        WHERE b.forward_close IS NOT NULL
        ORDER BY t.trigger_date, t.ticker_id
    """

    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        c.execute(sql, (signal_name, threshold, str(lookback_days), forward_days))
        rows = c.fetchall()

    if not rows:
        return {
            "signal": signal_name,
            "rule": rule,
            "forward_days": forward_days,
            "lookback_days": lookback_days,
            "n_observations": 0,
            "sample_warning": "No triggers in lookback window",
        }

    returns = [float(r[5]) for r in rows]
    n = len(returns)
    n_winners = sum(1 for r in returns if r > 0)

    by_ticker: dict[str, int] = {}
    for r in rows:
        by_ticker[r[0]] = by_ticker.get(r[0], 0) + 1

    sample_warning = None
    if n < 30:
        sample_warning = (
            f"Only {n} observations — treat hit-rate as illustrative. "
            f"Need ~6+ months more T86/OHLCV data for robust validation."
        )

    return {
        "signal": signal_name,
        "rule": rule,
        "forward_days": forward_days,
        "lookback_days": lookback_days,
        "n_observations": n,
        "hit_rate_pct": round(100.0 * n_winners / n, 2),
        "avg_return_pct": round(statistics.mean(returns), 3),
        "median_return_pct": round(statistics.median(returns), 3),
        "best_return_pct": round(max(returns), 3),
        "worst_return_pct": round(min(returns), 3),
        "stdev_return_pct": round(statistics.stdev(returns), 3) if n > 1 else None,
        "sample_warning": sample_warning,
        "samples_by_ticker": dict(sorted(by_ticker.items())),
    }


def backtest_compound(
    conditions: list[dict],
    forward_days: int = 5,
    lookback_days: int = 365,
) -> dict:
    """Backtest a compound rule (multiple AND-combined thresholds).

    Each condition is {'signal': str, 'op': '<' | '>', 'threshold': float}.
    All conditions must be satisfied on the same (ticker, date) for the
    bar to count as a trigger. Implementation: self-join signal_value
    once per condition.

    Bounded by signal name + op allowlists — no f-string identifier ever
    reaches the database without validation.
    """
    if not conditions:
        return {"error": "compound rule needs at least one condition"}
    if len(conditions) > 4:
        return {"error": "max 4 conditions (each adds a self-join)"}

    allowed_signals = {
        "rsi_14", "macd_line", "macd_signal_line", "macd_histogram",
        "bb_pct_b", "atr_14", "sma_50", "sma_200", "rs_vs_market_60",
        "pct_below_52w_high",
        "foreign_net_z20", "foreign_net_5d_sum", "total_net_z20",
    }
    for i, cond in enumerate(conditions):
        if cond.get("signal") not in allowed_signals:
            return {"error": f"condition {i}: unknown signal '{cond.get('signal')}'"}
        if cond.get("op") not in ("<", ">"):
            return {"error": f"condition {i}: op must be '<' or '>'"}

    # Build the self-join chain. s0 is the anchor (provides trigger_date).
    joins = []
    where_clauses = []
    params: list = []
    for i, cond in enumerate(conditions):
        alias = f"s{i}"
        if i == 0:
            joins.append(f"FROM signal_value {alias}")
        else:
            joins.append(
                f"JOIN signal_value {alias} "
                f"ON {alias}.ticker_id = s0.ticker_id "
                f"AND {alias}.date = s0.date"
            )
        where_clauses.append(f"{alias}.signal_name = %s AND {alias}.value {cond['op']} %s")
        params.extend([cond["signal"], cond["threshold"]])

    # Lookback applied to anchor date.
    where_clauses.append("s0.date >= current_date - (%s || ' days')::interval")
    params.append(str(lookback_days))

    rule = " AND ".join(f"{c['signal']} {c['op']} {c['threshold']}" for c in conditions)

    sql = f"""
        WITH triggers AS (
            SELECT s0.ticker_id, s0.date AS trigger_date
            {' '.join(joins)}
            WHERE {' AND '.join(where_clauses)}
        ),
        bars AS (
            SELECT ticker_id, date, close,
                   LEAD(close, %s) OVER (PARTITION BY ticker_id ORDER BY date) AS forward_close
            FROM raw_twse_ohlcv
        )
        SELECT t.ticker_id, t.trigger_date,
               (b.forward_close / b.close - 1.0) * 100.0 AS pct_return
        FROM triggers t
        JOIN bars b ON b.ticker_id = t.ticker_id AND b.date = t.trigger_date
        WHERE b.forward_close IS NOT NULL
    """
    params.append(forward_days)

    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        c.execute(sql, tuple(params))
        rows = c.fetchall()

    if not rows:
        return {
            "rule": rule, "forward_days": forward_days,
            "lookback_days": lookback_days,
            "n_observations": 0,
            "sample_warning": "No triggers met all conditions in lookback window",
        }

    returns = [float(r[2]) for r in rows]
    n = len(returns)
    n_winners = sum(1 for r in returns if r > 0)
    by_ticker: dict[str, int] = {}
    for r in rows:
        by_ticker[r[0]] = by_ticker.get(r[0], 0) + 1

    sample_warning = None
    if n < 30:
        sample_warning = f"Only {n} obs — illustrative, not predictive."

    return {
        "rule": rule,
        "forward_days": forward_days,
        "lookback_days": lookback_days,
        "n_observations": n,
        "hit_rate_pct": round(100.0 * n_winners / n, 2),
        "avg_return_pct": round(statistics.mean(returns), 3),
        "median_return_pct": round(statistics.median(returns), 3),
        "best_return_pct": round(max(returns), 3),
        "worst_return_pct": round(min(returns), 3),
        "stdev_return_pct": round(statistics.stdev(returns), 3) if n > 1 else None,
        "sample_warning": sample_warning,
        "samples_by_ticker": dict(sorted(by_ticker.items())),
    }


def backtest_horizons(
    signal_name: str,
    threshold: float,
    direction: Direction = "below",
    horizons: tuple[int, ...] = (1, 5, 10, 20),
    lookback_days: int = 365,
) -> dict:
    """Run the same threshold rule at multiple forward horizons.

    Useful for spotting edge decay — a signal might predict 1-day moves
    but be noise at 20 days, or vice versa.
    """
    return {
        "signal": signal_name,
        "threshold": threshold,
        "direction": direction,
        "lookback_days": lookback_days,
        "by_horizon": {
            f"{d}d": backtest_threshold(
                signal_name, threshold, direction, d, lookback_days
            )
            for d in horizons
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest a quant signal threshold")
    parser.add_argument("signal_name", help="e.g. rsi_14, macd_histogram")
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--direction", choices=["below", "above"], default="below")
    parser.add_argument("--forward-days", type=int, default=5)
    parser.add_argument("--lookback-days", type=int, default=365)
    args = parser.parse_args()

    result = backtest_threshold(
        args.signal_name, args.threshold, args.direction,
        args.forward_days, args.lookback_days,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
