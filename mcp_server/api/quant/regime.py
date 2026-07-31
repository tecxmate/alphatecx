#!/usr/bin/env python3
"""Regime detection for the classified universe.

Two complementary axes, both computed from rolling windows:

  vol regime    realized 30-day annualised vol of the broad market (TAIEX
                via 0050 ETF)
                  < 12%  → 'low'   (calm trend, alpha-friendly)
                  12-25% → 'normal'
                  > 25%  → 'high'  (stress, cut size)

  corr regime   average pairwise correlation of classified universe
                returns over a rolling window
                  < 0.30 → 'dispersed'   (idiosyncratic — alpha-friendly)
                  0.30-0.55 → 'normal'
                  > 0.55 → 'crowded'     (factor-dominated, beta-only)

Combine into one of four regime labels. The high_vol_crowded label is
the classic "stress + factor crowding" — worst time for fundamental
single-name bets. low_vol_dispersed is the opposite — calm market with
real differentiation between names.

Run:
    python -m src.quant.regime --window 30
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
log = logging.getLogger("regime")


def fetch_market_returns(conn, days: int):
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    with conn.cursor() as c:
        c.execute("""SELECT date, close FROM raw_twse_ohlcv
                     WHERE ticker_id = '0050' AND date >= %s AND close IS NOT NULL
                     ORDER BY date""", (cutoff,))
        rows = c.fetchall()
    if len(rows) < 5:
        return [], np.array([])
    dates = [r[0] for r in rows]
    closes = np.array([float(r[1]) for r in rows], dtype=float)
    return dates[1:], np.diff(np.log(closes))


def fetch_classified_returns(conn, days: int):
    """Aligned daily log-return matrix (T × N) for classified tickers."""
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    with conn.cursor() as c:
        c.execute("""SELECT o.date, o.ticker_id, o.close
                     FROM raw_twse_ohlcv o
                     JOIN dim_supply_chain dt USING (ticker_id)
                     WHERE o.date >= %s AND o.close IS NOT NULL
                     ORDER BY o.date""", (cutoff,))
        rows = c.fetchall()
    by_date: dict = {}
    for d, t, c_ in rows:
        by_date.setdefault(d, {})[t] = float(c_)
    # Universe size on a date varies; pick the largest fully-aligned subset
    target_set = set()
    for m in by_date.values():
        s = frozenset(m.keys())
        if len(s) > len(target_set):
            target_set = s
    # Take dates that have AT LEAST 80% of target_set
    keep_min = int(len(target_set) * 0.8)
    full_dates = sorted([d for d, m in by_date.items() if len(m) >= keep_min])
    if len(full_dates) < 30:
        return [], [], np.array([])
    # Use the most-common ticker subset (those present on all kept dates)
    common_tickers = set(target_set)
    for d in full_dates:
        common_tickers &= set(by_date[d].keys())
    common_tickers = sorted(common_tickers)
    if len(common_tickers) < 5:
        return [], [], np.array([])

    closes = np.array([[by_date[d][t] for t in common_tickers]
                        for d in full_dates], dtype=float)
    rets = np.diff(np.log(closes), axis=0)
    return full_dates[1:], common_tickers, rets


def compute_regime(window: int = 30, days: int = 120) -> dict:
    with psycopg.connect(DATABASE_URL) as conn:
        m_dates, m_ret = fetch_market_returns(conn, days)
        c_dates, c_tickers, c_rets = fetch_classified_returns(conn, days)

    if len(m_ret) < window + 5 or len(c_dates) < window + 5:
        return {"error": f"insufficient history (mkt={len(m_ret)}, cls={len(c_dates)})"}

    # Vol regime
    last_vol_window = m_ret[-window:]
    vol_30d = float(last_vol_window.std() * np.sqrt(252))
    vol_label = ("low" if vol_30d < 0.12
                 else "high" if vol_30d > 0.25 else "normal")

    # Correlation regime
    last_corr_window = c_rets[-window:]
    # Standardise then correlation = Z.T @ Z / (T-1)
    Z = (last_corr_window - last_corr_window.mean(axis=0)) / (
        last_corr_window.std(axis=0) + 1e-12)
    corr_mat = Z.T @ Z / (window - 1)
    np.fill_diagonal(corr_mat, np.nan)
    avg_corr = float(np.nanmean(corr_mat))
    corr_label = ("dispersed" if avg_corr < 0.30
                  else "crowded" if avg_corr > 0.55 else "normal")

    regime = f"{vol_label}_vol_{corr_label}"
    interpretation = _interpret(vol_30d, vol_label, avg_corr, corr_label,
                                len(c_tickers), window)

    # Trend in both metrics over the prior 60 days for context
    vol_series = []
    corr_series = []
    if len(m_ret) >= window * 2 and c_rets.shape[0] >= window * 2:
        for end in range(window, min(len(m_ret), c_rets.shape[0]) + 1, 5):
            wm = m_ret[end - window: end]
            wc = c_rets[end - window: end]
            vol_series.append(float(wm.std() * np.sqrt(252)))
            Zw = (wc - wc.mean(axis=0)) / (wc.std(axis=0) + 1e-12)
            cm = Zw.T @ Zw / (window - 1)
            np.fill_diagonal(cm, np.nan)
            corr_series.append(float(np.nanmean(cm)))
    vol_trend = ("rising" if len(vol_series) > 2 and vol_series[-1] > vol_series[-3]
                 else "falling" if len(vol_series) > 2 and vol_series[-1] < vol_series[-3]
                 else "flat")
    corr_trend = ("rising" if len(corr_series) > 2 and corr_series[-1] > corr_series[-3]
                  else "falling" if len(corr_series) > 2 and corr_series[-1] < corr_series[-3]
                  else "flat")

    return {
        "asof":             date.today().isoformat(),
        "window_days":      window,
        "vol_30d_annualized": round(vol_30d, 4),
        "vol_regime":       vol_label,
        "vol_trend":        vol_trend,
        "avg_pairwise_correlation": round(avg_corr, 3),
        "corr_regime":      corr_label,
        "corr_trend":       corr_trend,
        "regime_label":     regime,
        "n_tickers":        len(c_tickers),
        "interpretation":   interpretation,
    }


def _interpret(vol, vol_lbl, corr, corr_lbl, n_tickers, window):
    parts = [
        f"Regime over last {window} trading days:",
        f"market vol {vol*100:.1f}% annualised ({vol_lbl}),",
        f"average pairwise correlation across {n_tickers} classified "
        f"tickers = {corr:.2f} ({corr_lbl}).",
    ]
    if vol_lbl == "low" and corr_lbl == "dispersed":
        parts.append("Best regime for stockpicking — low macro stress, "
                     "high idiosyncratic differentiation. Single-name "
                     "alpha is most likely to pay off here.")
    elif vol_lbl == "high" and corr_lbl == "crowded":
        parts.append("Worst regime for fundamental bets — risk-off + "
                     "factor crowding. Cut single-name size; the cluster "
                     "moves as one.")
    elif corr_lbl == "crowded":
        parts.append("Factor-crowded regime: even differentiated "
                     "fundamentals don't separate names. Treat positions "
                     "as beta exposure, not alpha.")
    elif corr_lbl == "dispersed":
        parts.append("Names are differentiating — fundamental analysis "
                     "is paying off. Good environment for the q_factor_screen "
                     "tool's significant-α names.")
    if vol_lbl == "high":
        parts.append("Elevated market vol — position-size discipline "
                     "matters more than ticker selection.")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--days", type=int, default=120)
    args = ap.parse_args()
    import json
    print(json.dumps(compute_regime(window=args.window, days=args.days),
                     indent=2, default=str))


if __name__ == "__main__":
    main()
