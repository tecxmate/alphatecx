#!/usr/bin/env python3
"""Cointegration / pairs-trading primitive.

Tests whether the spread between two tickers' log-prices is mean-reverting
(stationary). If yes, the spread is tradeable: short the rich leg, long
the cheap leg, exit when the spread crosses zero.

Method:
  1. Engle-Granger two-step: regress log(P_a) on log(P_b) + intercept,
     extract residual ε_t. The residual is the spread.
  2. Augmented Dickey-Fuller (ADF) test on ε_t — reject the null of a unit
     root → spread is stationary → pair is cointegrated.
  3. Half-life estimate: fit ε_t = α + β·ε_{t-1} + η; half-life = -ln(2)/ln(β).
     A 5-day half-life means a 2σ deviation typically reverts in 5 trading days.
  4. Current z-score of the spread: (ε_today - mean(ε)) / std(ε).
     |z| > 2 = tradeable mean-reversion entry.

We implement ADF without statsmodels (numpy only) — it's a 20-line OLS.

Run:
    python -m src.quant.cointegration 2382 3231 --days 120
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, timedelta

import numpy as np
import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("MCP_DATABASE_URL") or os.environ["DATABASE_URL"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("coint")


# Approximate ADF critical values (1%, 5%, 10%) for the no-intercept,
# no-trend model — appropriate for residual ADF in Engle-Granger step 2.
# These are MacKinnon 2010 asymptotic values; close enough for n>50.
_ADF_CRIT = {1: -2.566, 5: -1.941, 10: -1.617}


def _adf_test(series: np.ndarray, max_lag: int = 0) -> dict:
    """Augmented Dickey-Fuller test, no-constant no-trend variant.

    Regress Δy_t = ρ·y_{t-1} + Σ φ_i·Δy_{t-i} + ε_t. The t-stat on ρ is the
    ADF statistic. ρ < 0 with significant t-stat → reject unit root →
    series is stationary → pair is cointegrated.
    """
    series = np.asarray(series, dtype=float)
    n = len(series)
    if n < 30:
        return {"error": f"too short for ADF (n={n})"}

    dy = np.diff(series)
    y_lag = series[:-1]
    # Build regressor matrix: [y_{t-1}, Δy_{t-1}, ..., Δy_{t-max_lag}]
    cols = [y_lag[max_lag:]]
    for k in range(1, max_lag + 1):
        cols.append(dy[max_lag - k:-k])
    target = dy[max_lag:]
    X = np.column_stack(cols) if cols else y_lag.reshape(-1, 1)
    try:
        beta, *_ = np.linalg.lstsq(X, target, rcond=None)
        resid = target - X @ beta
        nx, kx = X.shape
        sigma2 = float(np.sum(resid ** 2) / max(1, nx - kx))
        var_beta = sigma2 * np.linalg.inv(X.T @ X)
        se_rho = float(np.sqrt(var_beta[0, 0]))
    except np.linalg.LinAlgError:
        return {"error": "ADF regression singular"}

    rho = float(beta[0])
    tstat = rho / se_rho if se_rho > 1e-12 else float("inf")
    # Reject unit-root if t-stat below 5% critical value
    return {
        "adf_stat": round(tstat, 3),
        "adf_rho": round(rho, 4),
        "stationary_5pct": bool(tstat < _ADF_CRIT[5]),
        "stationary_10pct": bool(tstat < _ADF_CRIT[10]),
        "crit_1pct": _ADF_CRIT[1],
        "crit_5pct": _ADF_CRIT[5],
        "crit_10pct": _ADF_CRIT[10],
    }


def _fetch_aligned(ticker_a: str, ticker_b: str, days: int):
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT date, ticker_id, close FROM raw_twse_ohlcv
             WHERE ticker_id IN (%s, %s) AND date >= %s AND close IS NOT NULL
             ORDER BY date
        """, (ticker_a, ticker_b, cutoff))
        rows = cur.fetchall()
        cur.execute("""SELECT ticker_id, company_name, ai_pillar, node
                       FROM dim_ticker WHERE ticker_id IN (%s, %s)""",
                    (ticker_a, ticker_b))
        meta = {r[0]: {"company_name": r[1], "ai_pillar": r[2], "node": r[3]}
                for r in cur.fetchall()}

    by_date: dict = {}
    for d, t, c in rows:
        by_date.setdefault(d, {})[t] = float(c)
    common = sorted([d for d, m in by_date.items()
                     if ticker_a in m and ticker_b in m])
    if len(common) > days:
        common = common[-days:]
    if len(common) < 30:
        raise ValueError(f"insufficient overlap (n={len(common)})")
    pa = np.array([by_date[d][ticker_a] for d in common], dtype=float)
    pb = np.array([by_date[d][ticker_b] for d in common], dtype=float)
    return common, pa, pb, meta


def compute_cointegration(ticker_a: str, ticker_b: str, days: int = 120) -> dict:
    """Engle-Granger cointegration test + spread diagnostics.

    Step 1: regress log(P_a) on [1, log(P_b)] → residual ε_t = spread.
    Step 2: ADF on ε_t → is the spread stationary?
    Step 3: half-life from AR(1) on residual.
    Step 4: current z-score of ε vs trailing distribution.

    Pair is "tradeable" when stationary at 5% and current |z| > 1.5.
    """
    try:
        dates, pa, pb, meta = _fetch_aligned(ticker_a, ticker_b, days)
    except ValueError as e:
        return {"error": str(e), "ticker_a": ticker_a, "ticker_b": ticker_b}

    log_a = np.log(pa)
    log_b = np.log(pb)

    # Step 1: regress log_a on [1, log_b]
    X = np.column_stack([np.ones_like(log_b), log_b])
    beta, *_ = np.linalg.lstsq(X, log_a, rcond=None)
    intercept, hedge_ratio = float(beta[0]), float(beta[1])
    residual = log_a - X @ beta  # ε_t (spread)

    # Step 2: ADF test on ε_t
    adf = _adf_test(residual, max_lag=1)

    # Step 3: half-life from AR(1) on residual
    eps_lag = residual[:-1]
    eps_now = residual[1:]
    Xh = np.column_stack([np.ones_like(eps_lag), eps_lag])
    bh, *_ = np.linalg.lstsq(Xh, eps_now, rcond=None)
    rho_ar1 = float(bh[1])
    if 0 < rho_ar1 < 1:
        half_life_days = float(-np.log(2) / np.log(rho_ar1))
    else:
        half_life_days = float("inf")  # no mean-reversion if rho >= 1 or <= 0

    # Step 4: current z-score
    eps_mean = float(residual.mean())
    eps_std  = float(residual.std())
    eps_now_val = float(residual[-1])
    z_score = (eps_now_val - eps_mean) / eps_std if eps_std > 1e-12 else 0.0

    # Tradeable signal
    stationary = adf.get("stationary_5pct", False)
    tradeable = stationary and abs(z_score) >= 1.5
    direction = ("long_a_short_b" if z_score < -1.5
                 else "short_a_long_b" if z_score > 1.5 else "wait")

    return {
        "ticker_a": ticker_a,
        "ticker_b": ticker_b,
        "name_a": meta.get(ticker_a, {}).get("company_name"),
        "name_b": meta.get(ticker_b, {}).get("company_name"),
        "pillar_a": meta.get(ticker_a, {}).get("ai_pillar"),
        "pillar_b": meta.get(ticker_b, {}).get("ai_pillar"),
        "node_a": meta.get(ticker_a, {}).get("node"),
        "node_b": meta.get(ticker_b, {}).get("node"),
        "n_obs": len(dates),
        "window_days": days,
        "hedge_ratio": round(hedge_ratio, 4),
        "intercept": round(intercept, 4),
        "adf_stat": adf.get("adf_stat"),
        "adf_crit_5pct": adf.get("crit_5pct"),
        "stationary_5pct": adf.get("stationary_5pct", False),
        "stationary_10pct": adf.get("stationary_10pct", False),
        "rho_ar1": round(rho_ar1, 4),
        "half_life_days": (round(half_life_days, 1)
                           if half_life_days != float("inf") else None),
        "spread_mean": round(eps_mean, 4),
        "spread_std": round(eps_std, 4),
        "spread_now": round(eps_now_val, 4),
        "z_score": round(z_score, 2),
        "tradeable": tradeable,
        "signal": direction if tradeable else "no_signal",
        "interpretation": _interpret_pair(
            ticker_a, ticker_b, stationary, z_score, half_life_days,
            tradeable, direction),
    }


def _interpret_pair(a, b, stationary, z, hl, tradeable, direction):
    parts = []
    if not stationary:
        parts.append(f"{a}/{b} spread is NOT stationary at 5% — pair is "
                     "not cointegrated; mean-reversion strategy invalid here.")
    else:
        parts.append(f"{a}/{b} spread IS stationary at 5% — cointegrated.")
        if hl == float("inf") or hl is None:
            parts.append("AR(1) gives no positive mean-reversion coefficient.")
        else:
            parts.append(f"Half-life {hl:.1f} days "
                         "(2σ deviation typically reverts in this many days).")
    parts.append(f"Current spread z-score: {z:+.2f}.")
    if tradeable:
        if direction == "long_a_short_b":
            parts.append(f"Tradeable: long {a}, short {b} — spread is below "
                         "mean, expects revert up.")
        else:
            parts.append(f"Tradeable: short {a}, long {b} — spread is above "
                         "mean, expects revert down.")
    else:
        parts.append("No tradeable signal currently (|z|<1.5 or non-stationary).")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker_a")
    ap.add_argument("ticker_b")
    ap.add_argument("--days", type=int, default=120)
    args = ap.parse_args()
    import json
    print(json.dumps(compute_cointegration(args.ticker_a, args.ticker_b,
                                           days=args.days),
                     indent=2, default=str))


if __name__ == "__main__":
    main()
