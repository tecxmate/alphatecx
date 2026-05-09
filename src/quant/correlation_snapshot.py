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


def build_plotly_html(snap: dict) -> str:
    """Render the snapshot as a self-contained interactive HTML via plotly."""
    import plotly.graph_objects as go

    nodes = snap["nodes"]
    PILLAR_COLOR = {
        "semiconductor":  "#4f9cff",
        "infrastructure": "#ff7a59",
        "equipment":      "#9b6dff",
        "energy":         "#22c55e",
    }

    # Group nodes by pillar so each pillar gets its own legend entry.
    pillars = {}
    for n in nodes:
        key = n["pillar"] or "context"
        pillars.setdefault(key, []).append(n)

    fig = go.Figure()

    # Supply-chain edges (yellow) — drawn first so they sit behind nodes.
    sc_x, sc_y, sc_z = [], [], []
    by_id = {n["id"]: n for n in nodes}
    for e in snap["edges"]:
        a, b = by_id.get(e["from"]), by_id.get(e["to"])
        if not a or not b: continue
        sc_x += [a["x"], b["x"], None]
        sc_y += [a["y"], b["y"], None]
        sc_z += [a["z"], b["z"], None]
    if sc_x:
        fig.add_trace(go.Scatter3d(
            x=sc_x, y=sc_y, z=sc_z, mode="lines",
            line=dict(color="rgba(255,209,102,0.45)", width=2),
            name="supply chain", hoverinfo="skip"
        ))

    # Correlation edges (faint blue)
    cc_x, cc_y, cc_z = [], [], []
    for e in snap["corr_edges"]:
        a, b = by_id.get(e["from"]), by_id.get(e["to"])
        if not a or not b: continue
        cc_x += [a["x"], b["x"], None]
        cc_y += [a["y"], b["y"], None]
        cc_z += [a["z"], b["z"], None]
    if cc_x:
        fig.add_trace(go.Scatter3d(
            x=cc_x, y=cc_y, z=cc_z, mode="lines",
            line=dict(color="rgba(79,156,255,0.18)", width=1),
            name="correlation ≥ 0.7", hoverinfo="skip"
        ))

    # Node traces — one per pillar
    for pillar_name, ns in pillars.items():
        is_ctx = pillar_name == "context"
        color = PILLAR_COLOR.get(pillar_name, "#3a3a3a")
        sizes = [max(6, min(22, n["vol"] * 30)) for n in ns]
        if is_ctx:
            sizes = [4] * len(ns)
        text = [
            f"<b>{n['id']} {n['name']}</b><br>"
            f"{(n['pillar'] or 'unclassified')} / {n['node'] or '—'}<br>"
            f"vol {n['vol']*100:.1f}% · 30d ret {n['ret_30d']*100:+.1f}%"
            for n in ns
        ]
        fig.add_trace(go.Scatter3d(
            x=[n["x"] for n in ns], y=[n["y"] for n in ns], z=[n["z"] for n in ns],
            mode="markers",
            marker=dict(size=sizes, color=color,
                        opacity=0.35 if is_ctx else 0.95,
                        line=dict(width=0)),
            text=text, hovertemplate="%{text}<extra></extra>",
            name=pillar_name,
        ))

    # Layout — dark theme, axis titles, camera presets via updatemenus.
    fig.update_layout(
        paper_bgcolor="#0a0d12", plot_bgcolor="#0a0d12",
        font=dict(color="#cdd5df", family="-apple-system,system-ui,sans-serif"),
        margin=dict(l=0, r=0, t=40, b=0),
        title=dict(text=f"Taiwan AI universe — {snap['n_tickers']} tickers, "
                        f"window {snap['window_days']}d, as of {snap['asof']}",
                   x=0.02, xanchor="left", font=dict(size=14)),
        scene=dict(
            xaxis=dict(title="correlation cluster", showbackground=False,
                       zerolinecolor="#2a3440", gridcolor="#1a2230",
                       color="#8a96a3"),
            yaxis=dict(title="correlation cluster", showbackground=False,
                       zerolinecolor="#2a3440", gridcolor="#1a2230",
                       color="#8a96a3"),
            zaxis=dict(title="30-day return (×3 visual scale)",
                       showbackground=False, zerolinecolor="#4a5568",
                       gridcolor="#1a2230", color="#cdd5df"),
            aspectmode="cube",
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.0)),
        ),
        legend=dict(bgcolor="rgba(18,22,28,0.85)", bordercolor="#1f2630",
                    borderwidth=1, font=dict(size=11)),
        updatemenus=[dict(
            type="buttons", direction="right", x=0.5, xanchor="center",
            y=1.08, yanchor="top", showactive=False,
            bgcolor="#1a2230", bordercolor="#2a323d",
            buttons=[
                dict(label="Isometric", method="relayout",
                     args=[{"scene.camera.eye": {"x": 1.5, "y": 1.5, "z": 1.0}}]),
                dict(label="Cluster (top)", method="relayout",
                     args=[{"scene.camera.eye": {"x": 0.001, "y": 0.001, "z": 2.5}}]),
                dict(label="Momentum (side)", method="relayout",
                     args=[{"scene.camera.eye": {"x": 2.5, "y": 0.001, "z": 0.4}}]),
            ],
        )],
    )

    plotly_html = fig.to_html(full_html=False, include_plotlyjs="cdn",
                              config={"displayModeBar": True, "displaylogo": False})

    disc = snap.get("discovery", [])
    disc_rows = "".join(
        f'<li><b>{c["ticker"]}</b> {c["name"]} → '
        f'<span style="color:{PILLAR_COLOR.get(c["suggested_pillar"], "#888")}">{c["suggested_pillar"]}</span> '
        f'(ρ≈{c["conviction"]})</li>'
        for c in disc[:10]
    )
    disc_html = (f'<div class="disc"><h2>Discovery candidates</h2><ol>{disc_rows}</ol></div>'
                 if disc_rows else "")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>alphatecx · TW correlation map</title>
<style>
  html,body {{ margin:0; padding:0; height:100%; background:#0a0d12; color:#cdd5df;
    font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif; }}
  #plot {{ width:100vw; height:100vh; }}
  .disc {{ position:fixed; bottom:12px; right:12px; max-width:340px; max-height:55vh;
    padding:10px 14px; background:rgba(18,22,28,0.92); border:1px solid #1f2630;
    border-radius:10px; font-size:12px; line-height:1.6; overflow-y:auto; z-index:1000; }}
  .disc h2 {{ font-size:12px; margin:0 0 6px; color:#e6ecf2; }}
  .disc ol {{ margin:0; padding-left:18px; }}
  .disc li {{ margin:3px 0; }}
</style></head><body>
<div id="plot">{plotly_html}</div>
{disc_html}
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=120)
    ap.add_argument("--out-json", type=str,
                    default="mcp_server/api/static/graph_snapshot.json")
    ap.add_argument("--out-html", type=str,
                    default="mcp_server/api/static/graph.html")
    args = ap.parse_args()

    snapshot = build_snapshot(window_days=args.window)

    json_path = Path(args.out_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(snapshot, indent=2))

    html_path = Path(args.out_html)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_plotly_html(snapshot))

    log.info("Wrote %s + %s (%d nodes, %d edges, %d corr_edges)",
             json_path, html_path,
             len(snapshot["nodes"]), len(snapshot["edges"]),
             len(snapshot["corr_edges"]))


if __name__ == "__main__":
    main()
