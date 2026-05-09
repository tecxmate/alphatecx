#!/usr/bin/env python3
"""Compute pairwise lead-lag correlations across the classified universe.

For each (upstream, downstream) pair where both are classified, we compute:

    rho_k = corr( r_upstream[:-k], r_downstream[k:] )   for k in {1..max_lag}
    rho_0 = corr( r_upstream,      r_downstream )       (coincident baseline)

A pair has a "real lead" if argmax_k rho_k > 0 AND rho_k > rho_0 + epsilon —
i.e. the upstream's move predicts the downstream's move better than the
coincident move. We store every (lag, rho) row so callers can decide their
own thresholds.

Window: 60 trading days by default. Short enough to reflect current regime;
long enough that lag-7 still has 53 observations.

Run:
    python -m src.quant.leadlag                       # all classified pairs
    python -m src.quant.leadlag --upstream 2330      # only TSMC as upstream
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, timedelta
from typing import Optional

import numpy as np
import polars as pl
import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("leadlag")


def _fetch_returns(window_days: int) -> tuple[np.ndarray, list[str]]:
    """Returns (T x N) log-return matrix and list of N classified tickers
    that have enough OHLCV history."""
    cutoff = (date.today() - timedelta(days=window_days * 2)).isoformat()  # buffer for weekends
    sql = """
        SELECT o.date, o.ticker_id, o.close
          FROM raw_twse_ohlcv o
          JOIN dim_supply_chain dt USING (ticker_id)
         WHERE o.date >= %s
           AND o.close IS NOT NULL AND o.close > 0
         ORDER BY o.date
    """
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, (cutoff,))
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError("no OHLCV rows for classified universe in window")

    df = pl.DataFrame(rows, schema=["date", "ticker_id", "close"], orient="row")
    df = df.with_columns(pl.col("close").cast(pl.Float64))
    wide = df.pivot(values="close", index="date", on="ticker_id",
                    aggregate_function="last").sort("date")

    # Truncate to the most recent `window_days` rows.
    if wide.height > window_days:
        wide = wide.tail(window_days)

    tickers = [c for c in wide.columns if c != "date"]
    closes = wide.select(tickers).to_numpy()
    valid_frac = (~np.isnan(closes)).sum(axis=0) / max(1, closes.shape[0])
    keep = valid_frac >= 0.8
    tickers = [t for t, k in zip(tickers, keep) if k]
    closes = closes[:, keep]
    rets = np.diff(np.log(closes), axis=0)
    col_mean = np.nanmean(rets, axis=0)
    inds = np.where(np.isnan(rets))
    rets[inds] = np.take(col_mean, inds[1])
    log.info("returns matrix: %d days x %d tickers", rets.shape[0], rets.shape[1])
    return rets, tickers


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Stable Pearson correlation between two 1-D arrays of equal length."""
    a = a - a.mean()
    b = b - b.mean()
    den = (a.std() * b.std())
    if den < 1e-12:
        return 0.0
    return float((a * b).mean() / den)


def compute_leadlag_pairs(
    rets: np.ndarray, tickers: list[str], max_lag: int = 7,
    upstream_filter: Optional[set[str]] = None,
) -> list[tuple[str, str, int, float, int]]:
    """Yields (upstream_id, downstream_id, lag, correlation, n_obs) tuples.

    Lag 0 is the coincident baseline. Lags 1..max_lag mean upstream leads
    downstream by that many days.
    """
    n_tickers = len(tickers)
    n_days = rets.shape[0]
    out = []
    for i in range(n_tickers):
        if upstream_filter is not None and tickers[i] not in upstream_filter:
            continue
        a = rets[:, i]
        for j in range(n_tickers):
            if i == j:
                continue
            b = rets[:, j]
            for lag in range(0, max_lag + 1):
                if lag == 0:
                    aa, bb = a, b
                else:
                    aa, bb = a[:-lag], b[lag:]
                if aa.size < 20:  # too few obs for stability
                    continue
                rho = _pearson(aa, bb)
                out.append((tickers[i], tickers[j], lag, rho, int(aa.size)))
    return out


def write_to_db(rows: list[tuple], window_days: int, asof: date) -> int:
    """Batch upsert via executemany — ~100x faster than per-row over network."""
    sql = """
        INSERT INTO lead_lag (asof, upstream_id, downstream_id, lag_days,
                              correlation, n_obs, window_days)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (asof, upstream_id, downstream_id, lag_days)
        DO UPDATE SET correlation = EXCLUDED.correlation,
                      n_obs = EXCLUDED.n_obs,
                      window_days = EXCLUDED.window_days
    """
    payload = [(asof, u, d, lag, rho, nobs, window_days)
               for u, d, lag, rho, nobs in rows]
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # Replace this asof's rows up-front so a partial run never leaves
            # mixed lags from two universes. Then bulk insert fresh.
            cur.execute("DELETE FROM lead_lag WHERE asof = %s", (asof,))
            cur.executemany(sql, payload)
        conn.commit()
    return len(payload)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=60,
                    help="trailing trading days (default 60)")
    ap.add_argument("--max-lag", type=int, default=7,
                    help="max lag in days (default 7)")
    ap.add_argument("--upstream", type=str, default=None,
                    help="comma-separated upstream tickers; default = all classified")
    args = ap.parse_args()

    rets, tickers = _fetch_returns(args.window)
    upstream_filter = set(args.upstream.split(",")) if args.upstream else None
    pairs = compute_leadlag_pairs(rets, tickers, args.max_lag, upstream_filter)
    log.info("computed %d (upstream, downstream, lag) rows", len(pairs))

    asof = date.today()
    n = write_to_db(pairs, args.window, asof)
    log.info("wrote %d rows to lead_lag asof=%s", n, asof)


if __name__ == "__main__":
    main()
