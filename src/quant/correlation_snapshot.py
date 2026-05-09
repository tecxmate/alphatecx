#!/usr/bin/env python3
"""Build a 3D correlation-network snapshot of the TW universe.

Reads daily closes from raw_twse_ohlcv, computes log-return correlations
over a rolling window, projects to 3D via PCA-on-correlation-distance, and
writes a single JSON snapshot consumed by the /graph viewer.

The "distance" choice:
    d_ij = sqrt(2 * (1 - rho_ij))
This is the standard Mantegna distance — turns a correlation matrix into a
proper Euclidean distance matrix. Then we PCA the distance matrix to embed
in 3D. Tickers that move together → small distance → close in 3D.

Run:
    python -m src.quant.correlation_snapshot
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
from dotenv import load_dotenv
import psycopg

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("snapshot")

# --- pillar palette (kept in sync with viewer) ----------------------------
PILLAR_COLOR = {
    "semiconductor":  "#4f9cff",  # blue
    "infrastructure": "#ff7a59",  # orange
    "equipment":      "#9b6dff",  # purple
    "energy":         "#22c55e",  # green
    None:             "#3a3a3a",  # grey context
}


def fetch_returns(window_days: int = 120) -> pl.DataFrame:
    """Wide DataFrame: rows = trading dates, cols = tickers, values = close."""
    log.info("Fetching OHLCV closes (window=%d days)", window_days)
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    sql = """
        SELECT date, ticker_id, close
          FROM raw_twse_ohlcv
         WHERE date >= %s
           AND close IS NOT NULL
           AND close > 0
         ORDER BY date
    """
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, (cutoff,))
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError("no OHLCV rows in window")
    df = pl.DataFrame(rows, schema=["date", "ticker_id", "close"], orient="row")
    df = df.with_columns(pl.col("close").cast(pl.Float64))
    wide = df.pivot(values="close", index="date", on="ticker_id", aggregate_function="last")
    wide = wide.sort("date")
    log.info("Wide frame: %d dates x %d tickers", wide.height, wide.width - 1)
    return wide


def fetch_meta() -> dict[str, dict]:
    """ticker_id -> {company_name, ai_pillar, node, us_partners}."""
    sql = """
        SELECT ticker_id, company_name, ai_pillar, node, us_partners
          FROM dim_ticker
    """
    out = {}
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql)
        for tid, name, pillar, node, partners in cur.fetchall():
            out[tid] = {
                "name": name or tid,
                "pillar": pillar,
                "node": node,
                "partners": list(partners) if partners else [],
            }
    return out


def fetch_edges() -> list[dict]:
    sql = """
        SELECT upstream_id, downstream_id, relationship, confidence
          FROM sc_edges
    """
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [
            {"from": u, "to": d, "rel": r, "conf": c}
            for u, d, r, c in cur.fetchall()
        ]


def compute_returns(wide: pl.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Return (T x N) log-return matrix and list of N tickers (data-rich only)."""
    tickers = [c for c in wide.columns if c != "date"]
    closes = wide.select(tickers).to_numpy()
    # Drop tickers with too many NaNs (require >= 80% of days populated)
    valid_frac = (~np.isnan(closes)).sum(axis=0) / closes.shape[0]
    keep_mask = valid_frac >= 0.8
    tickers = [t for t, k in zip(tickers, keep_mask) if k]
    closes = closes[:, keep_mask]
    log.info("After NaN filter: %d tickers", len(tickers))

    # Log returns; first row drops to NaN; replace with 0 then mask
    rets = np.diff(np.log(closes), axis=0)
    # Replace remaining NaNs with column mean (small influence in correlation)
    col_mean = np.nanmean(rets, axis=0)
    inds = np.where(np.isnan(rets))
    rets[inds] = np.take(col_mean, inds[1])
    return rets, tickers


def correlation_to_2d_floor(rets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Returns (corr_matrix, 2D floor coords).

    X,Y = classical MDS of Mantegna correlation distance (preserves cluster
    geometry on the horizontal plane). The vertical Z axis is added later
    from a meaningful quantity (e.g. 30-day return) so 'up' literally means
    'going up'.
    """
    # Standardize columns
    rets_std = (rets - rets.mean(axis=0)) / (rets.std(axis=0) + 1e-12)
    corr = (rets_std.T @ rets_std) / rets.shape[0]
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)

    # Mantegna distance: d_ij = sqrt(2*(1 - rho))
    dist = np.sqrt(np.clip(2.0 * (1.0 - corr), 0, None))

    # Classical MDS: double-center then take top 2 eigenvectors for the floor
    n = dist.shape[0]
    sq = dist ** 2
    J = np.eye(n) - np.ones((n, n)) / n
    B = -0.5 * J @ sq @ J
    eigvals, eigvecs = np.linalg.eigh(B)
    idx = np.argsort(eigvals)[::-1][:2]
    floor = eigvecs[:, idx] * np.sqrt(np.maximum(eigvals[idx], 0))
    floor -= floor.mean(axis=0)
    span = np.abs(floor).max() + 1e-9
    floor = floor / span
    return corr, floor


def compute_node_attrs(rets: np.ndarray, tickers: list[str]) -> dict[str, dict]:
    """Per-ticker volatility and trailing return."""
    vol = rets.std(axis=0) * np.sqrt(252)  # annualized
    ret_30 = np.exp(rets[-30:].sum(axis=0)) - 1 if rets.shape[0] >= 30 else np.zeros(len(tickers))
    ret_full = np.exp(rets.sum(axis=0)) - 1
    return {
        t: {"vol": float(vol[i]), "ret_30d": float(ret_30[i]), "ret_window": float(ret_full[i])}
        for i, t in enumerate(tickers)
    }


def build_snapshot(window_days: int = 120) -> dict:
    wide = fetch_returns(window_days)
    rets, tickers = compute_returns(wide)
    corr, floor = correlation_to_2d_floor(rets)
    attrs = compute_node_attrs(rets, tickers)
    meta = fetch_meta()
    edges = fetch_edges()

    # Z axis is 30-day return — directly readable: up = rising, down = falling.
    # Scale so a +/- 30% move spans roughly the same visual range as the floor.
    Z_SCALE = 3.0
    z_clip = 0.95  # cap visually so extreme outliers don't break framing

    nodes = []
    for i, tid in enumerate(tickers):
        m = meta.get(tid, {"name": tid, "pillar": None, "node": None, "partners": []})
        a = attrs[tid]
        z_visual = float(np.clip(a["ret_30d"] * Z_SCALE, -z_clip, z_clip))
        nodes.append({
            "id":      tid,
            "name":    m["name"],
            "pillar":  m["pillar"],
            "node":    m["node"],
            "x":       float(floor[i, 0]),
            "y":       float(floor[i, 1]),
            "z":       z_visual,
            "vol":     round(a["vol"], 4),
            "ret_30d": round(a["ret_30d"], 4),
            "color":   PILLAR_COLOR.get(m["pillar"], PILLAR_COLOR[None]),
            "partners": m["partners"],
        })

    # Top correlations (>= 0.7) as faint extra edges, only between classified
    classified = {n["id"] for n in nodes if n["pillar"]}
    corr_edges = []
    idx = {t: i for i, t in enumerate(tickers)}
    for a in classified:
        if a not in idx: continue
        for b in classified:
            if b <= a or b not in idx: continue
            c = corr[idx[a], idx[b]]
            if c >= 0.7:
                corr_edges.append({"from": a, "to": b, "rho": round(float(c), 3)})

    # Discovery: for each unclassified ticker, find its 5 nearest classified
    # neighbours by correlation. If at least 3 of the 5 share the same pillar
    # AND the median correlation to that pillar is high, flag as a candidate.
    discovery = _discovery_candidates(corr, tickers, nodes, idx)

    snapshot = {
        "asof":       date.today().isoformat(),
        "window_days": window_days,
        "n_tickers":   len(nodes),
        "axes": {
            "x": "correlation cluster (MDS-1)",
            "y": "correlation cluster (MDS-2)",
            "z": "30-day return (up = rising)",
            "z_scale": Z_SCALE,    # multiply visual z by 1/Z_SCALE to recover ret_30d
        },
        "nodes":      nodes,
        "edges":      edges,        # supply-chain edges (sc_edges)
        "corr_edges": corr_edges,   # high-correlation pairs (>= 0.7)
        "discovery":  discovery,    # unclassified tickers that cluster with a pillar
    }
    return snapshot


def _discovery_candidates(corr, tickers, nodes, idx):
    """Return [{ticker, name, suggested_pillar, suggested_node, conviction, neighbours}, ...].

    For each context (unclassified) ticker, look at its 5 strongest correlations
    among classified tickers. If at least 3 share the same pillar AND median
    correlation to that pillar >= 0.55, flag as a supply-chain peer candidate.
    Sort by descending conviction (max correlation to dominant pillar).
    """
    by_id = {n["id"]: n for n in nodes}
    classified_ids = [n["id"] for n in nodes if n["pillar"]]

    out = []
    for n in nodes:
        if n["pillar"] is not None:
            continue
        if n["id"] not in idx:
            continue
        i = idx[n["id"]]
        # Correlation to every classified ticker
        sims = []
        for cid in classified_ids:
            if cid not in idx: continue
            sims.append((cid, float(corr[i, idx[cid]])))
        sims.sort(key=lambda x: x[1], reverse=True)
        top5 = sims[:5]
        if len(top5) < 5:
            continue

        # Dominant pillar / node among top-5
        from collections import Counter
        pillars = Counter(by_id[t]["pillar"] for t, _ in top5)
        nodes_ct = Counter(by_id[t]["node"]   for t, _ in top5)
        top_pillar, p_count = pillars.most_common(1)[0]
        top_node,   n_count = nodes_ct.most_common(1)[0]

        if p_count < 3:
            continue

        # Median correlation to that pillar
        pillar_corrs = [c for t, c in top5 if by_id[t]["pillar"] == top_pillar]
        median_corr = float(np.median(pillar_corrs))
        if median_corr < 0.55:
            continue

        out.append({
            "ticker":            n["id"],
            "name":              n["name"],
            "suggested_pillar":  top_pillar,
            "suggested_node":    top_node if n_count >= 3 else None,
            "conviction":        round(median_corr, 3),
            "neighbours": [
                {"id": t, "name": by_id[t]["name"], "pillar": by_id[t]["pillar"],
                 "node": by_id[t]["node"], "rho": round(c, 3)}
                for t, c in top5
            ],
        })
    out.sort(key=lambda x: x["conviction"], reverse=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=120, help="Days of history to use")
    ap.add_argument("--out", type=str,
                    default="mcp_server/api/static/graph_snapshot.json",
                    help="Output JSON path")
    args = ap.parse_args()

    snapshot = build_snapshot(window_days=args.window)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2))
    log.info("Wrote %s (%d nodes, %d edges, %d corr_edges)",
             out_path, len(snapshot["nodes"]),
             len(snapshot["edges"]), len(snapshot["corr_edges"]))


if __name__ == "__main__":
    main()
