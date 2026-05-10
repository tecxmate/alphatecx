#!/usr/bin/env python3
"""PCA risk decomposition for a basket of tickers.

Given N tickers and T days of daily log-returns, computes:
  - Top-k principal components (PC_1, PC_2, ...) — orthogonal latent
    factors that explain the most variance in the basket
  - Each ticker's loading on each PC
  - % variance explained by each PC
  - Plain interpretation: PC_1 is almost always "market β"; PC_2 and PC_3
    often have meaningful structure (e.g. "AI vs traditional", "cyclical
    vs defensive", "memory vs logic")

Use case: "I have 5 names in my portfolio — am I diversified, or am I
just betting on one factor 5 different ways?" If 80% of the variance is
in PC_1, you have effectively one position. If it's 40/30/20, you have
real diversification.

Run as CLI:
    python -m src.quant.pca_decompose 2330,3231,3711,2382,6669
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, timedelta
from typing import Optional

import numpy as np
import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("pca")


def _fetch_aligned_returns(tickers: list[str], days: int):
    """Returns (np.ndarray of shape (T, N), list[date], list[str])."""
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    placeholders = ",".join(["%s"] * len(tickers))
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT date, ticker_id, close FROM raw_twse_ohlcv
             WHERE ticker_id IN ({placeholders}) AND date >= %s
               AND close IS NOT NULL
             ORDER BY date
        """, (*tickers, cutoff))
        rows = cur.fetchall()

    # Build wide pivot { date -> { ticker -> close } }
    by_date: dict = {}
    for d, t, c in rows:
        by_date.setdefault(d, {})[t] = float(c)
    # Keep dates where ALL tickers reported
    full_dates = sorted([d for d, m in by_date.items() if len(m) == len(tickers)])
    if len(full_dates) > days:
        full_dates = full_dates[-days:]
    if len(full_dates) < 30:
        raise ValueError(f"insufficient overlap: only {len(full_dates)} aligned days")
    closes = np.array([[by_date[d][t] for t in tickers] for d in full_dates],
                      dtype=float)
    rets = np.diff(np.log(closes), axis=0)
    return rets, full_dates[1:], tickers


def compute_pca(tickers: list[str], days: int = 120, k: int = 3) -> dict:
    """PCA on standardised returns. Returns top-k components, loadings,
    and explained-variance ratios."""
    if len(tickers) < 2:
        return {"error": "need at least 2 tickers"}
    if k > len(tickers):
        k = len(tickers)

    try:
        rets, dates, ts = _fetch_aligned_returns(tickers, days)
    except ValueError as e:
        return {"error": str(e), "tickers": tickers}

    # Z-score each column (so variance contribution is unit-comparable)
    mu = rets.mean(axis=0)
    sd = rets.std(axis=0)
    sd[sd < 1e-12] = 1.0
    Z = (rets - mu) / sd

    # SVD-based PCA
    n_obs, n_tickers = Z.shape
    U, sigma, Vt = np.linalg.svd(Z, full_matrices=False)
    # eigenvalues of covariance matrix = sigma^2 / (n - 1)
    eigvals = (sigma ** 2) / max(1, n_obs - 1)
    explained = eigvals / eigvals.sum()
    loadings = Vt[:k]  # shape (k, n_tickers)

    # Per-ticker contribution to each PC: |loading|
    components = []
    for i in range(k):
        # Sort tickers by absolute loading magnitude (which dominates this PC)
        ranked = sorted(
            [(ts[j], float(loadings[i, j])) for j in range(n_tickers)],
            key=lambda x: abs(x[1]), reverse=True,
        )
        components.append({
            "pc": i + 1,
            "explained_variance": round(float(explained[i]), 4),
            "explained_variance_pct": round(float(explained[i]) * 100, 2),
            "loadings": {t: round(l, 3) for t, l in ranked},
            "interpretation_hint": _hint_for_pc(i, loadings[i], ts, explained[i]),
        })

    return {
        "tickers": ts,
        "n_obs": int(n_obs),
        "window_days": days,
        "components": components,
        "cumulative_variance_pct": round(float(explained[:k].sum()) * 100, 2),
        "interpretation": _summarise(components, ts),
    }


def _hint_for_pc(idx, loading, tickers, ev):
    """Tiny heuristic: PC_1 is almost always the market factor (all loadings
    same sign). PC_2+ usually splits the universe — show the split."""
    pos = [t for t, l in zip(tickers, loading) if l > 0]
    neg = [t for t, l in zip(tickers, loading) if l < 0]
    if idx == 0 and len(pos) >= 0.8 * len(tickers):
        return "common-factor / market β"
    if idx == 0 and len(neg) >= 0.8 * len(tickers):
        return "common-factor / market β (sign-flipped, equivalent)"
    return f"split: {len(pos)} positive vs {len(neg)} negative"


def _summarise(components, tickers):
    parts = [f"Decomposed {len(tickers)} tickers into {len(components)} principal components."]
    cum = 0
    for c in components:
        cum += c["explained_variance_pct"]
        parts.append(f"PC{c['pc']} explains {c['explained_variance_pct']:.1f}% "
                     f"({c['interpretation_hint']}).")
    parts.append(f"Top {len(components)} PCs cover {cum:.1f}% of variance.")
    if components and components[0]["explained_variance_pct"] > 70:
        parts.append("⚠ Concentration warning: a single common factor "
                     "dominates. The basket is effectively one position — "
                     "diversification across tickers is illusory.")
    elif components and components[0]["explained_variance_pct"] < 50:
        parts.append("✓ Genuine diversification — no single factor "
                     "dominates the basket.")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", help="comma-separated ticker list, e.g. '2330,3711,3231'")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    import json
    print(json.dumps(compute_pca(tickers, days=args.days, k=args.k),
                     indent=2, default=str))


if __name__ == "__main__":
    main()
