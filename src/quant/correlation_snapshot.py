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
    return snapshot, corr, tickers


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
    """[Deprecated] Plotly 3D viewer — kept for reference, no longer wired up."""
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


def build_matplotlib_panels(snap: dict, corr: np.ndarray, tickers: list[str]) -> bytes:
    """Render the snapshot as a 2x2 light-theme PNG (returns raw bytes).

    Panels:
        TL: cluster map (correlation MDS X vs Y) — color = pillar
        TR: cluster axis vs 30d return (X vs ret_30d)
        BL: risk/return scatter (annualised vol vs ret_30d)
        BR: correlation heatmap, sorted by pillar
    """
    import io
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    PILLAR_COLOR = {
        "semiconductor":  "#2563eb",
        "infrastructure": "#ea580c",
        "equipment":      "#7c3aed",
        "energy":         "#16a34a",
        None:             "#cbd5e0",
    }
    PILLAR_ORDER = ["semiconductor", "equipment", "infrastructure", "energy", None]

    nodes = snap["nodes"]
    by_id = {n["id"]: n for n in nodes}
    ids        = [n["id"]      for n in nodes]
    names      = [n["name"]    for n in nodes]
    pillars    = [n["pillar"]  for n in nodes]
    xs         = np.array([n["x"]       for n in nodes])
    ys         = np.array([n["y"]       for n in nodes])
    ret30      = np.array([n["ret_30d"] for n in nodes])
    vols       = np.array([n["vol"]     for n in nodes])
    colors     = [PILLAR_COLOR[p] for p in pillars]
    is_ctx     = np.array([p is None for p in pillars])
    sizes      = np.where(is_ctx, 12, np.clip(vols * 60, 18, 90))

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.facecolor": "white",
        "figure.facecolor": "white",
        "axes.edgecolor": "#94a3b8",
        "axes.labelcolor": "#475569",
        "xtick.color": "#64748b",
        "ytick.color": "#64748b",
        "axes.titlecolor": "#0f172a",
        "axes.titlesize": 12,
        "axes.titleweight": "600",
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
    })

    fig, axes = plt.subplots(2, 2, figsize=(14, 11))
    fig.suptitle(
        f"Taiwan AI universe — {snap['n_tickers']} tickers · window {snap['window_days']}d · as of {snap['asof']}",
        fontsize=14, fontweight="600", color="#0f172a", y=0.995,
    )

    # ── TL: cluster map ──
    ax = axes[0, 0]
    # Draw context first (under)
    ax.scatter(xs[is_ctx],  ys[is_ctx],  c="#cbd5e0", s=8, alpha=0.5, linewidths=0)
    # Then classified
    ax.scatter(xs[~is_ctx], ys[~is_ctx], c=[colors[i] for i in range(len(nodes)) if not is_ctx[i]],
               s=sizes[~is_ctx], alpha=0.85, linewidths=0.4, edgecolors="white")
    # Label only classified
    for i, n in enumerate(nodes):
        if pillars[i] is None: continue
        ax.annotate(ids[i], (xs[i], ys[i]), fontsize=7, color="#334155",
                    xytext=(3, 3), textcoords="offset points")
    ax.set_title("Correlation cluster (top-down)")
    ax.set_xlabel("MDS axis 1")
    ax.set_ylabel("MDS axis 2")
    ax.grid(True, linestyle="--", linewidth=0.5, color="#e2e8f0")
    ax.axhline(0, color="#cbd5e0", linewidth=0.7)
    ax.axvline(0, color="#cbd5e0", linewidth=0.7)

    # Overlay supply-chain edges as faint grey lines (cluster panel only)
    for e in snap["edges"]:
        a, b = by_id.get(e["from"]), by_id.get(e["to"])
        if not a or not b: continue
        ax.plot([a["x"], b["x"]], [a["y"], b["y"]],
                color="#fbbf24", linewidth=0.6, alpha=0.45, zorder=1)

    # ── TR: cluster axis vs 30d return ──
    ax = axes[0, 1]
    ax.axhline(0, color="#94a3b8", linewidth=0.8, zorder=1)
    ax.scatter(xs[is_ctx],  ret30[is_ctx],  c="#cbd5e0", s=8, alpha=0.5, linewidths=0)
    ax.scatter(xs[~is_ctx], ret30[~is_ctx],
               c=[colors[i] for i in range(len(nodes)) if not is_ctx[i]],
               s=sizes[~is_ctx], alpha=0.85, linewidths=0.4, edgecolors="white")
    for i, n in enumerate(nodes):
        if pillars[i] is None: continue
        if abs(ret30[i]) > 0.15:  # only label movers
            ax.annotate(ids[i], (xs[i], ret30[i]), fontsize=7, color="#334155",
                        xytext=(3, 3), textcoords="offset points")
    ax.set_title("Cluster position vs 30d return")
    ax.set_xlabel("MDS axis 1 (cluster)")
    ax.set_ylabel("30-day return")
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(True, linestyle="--", linewidth=0.5, color="#e2e8f0")

    # ── BL: risk/return scatter ──
    ax = axes[1, 0]
    ax.axhline(0, color="#94a3b8", linewidth=0.8, zorder=1)
    ax.scatter(vols[is_ctx],  ret30[is_ctx],  c="#cbd5e0", s=8, alpha=0.5, linewidths=0)
    ax.scatter(vols[~is_ctx], ret30[~is_ctx],
               c=[colors[i] for i in range(len(nodes)) if not is_ctx[i]],
               s=sizes[~is_ctx], alpha=0.85, linewidths=0.4, edgecolors="white")
    for i, n in enumerate(nodes):
        if pillars[i] is None: continue
        if vols[i] > 0.6 or abs(ret30[i]) > 0.3:  # label outliers
            ax.annotate(ids[i], (vols[i], ret30[i]), fontsize=7, color="#334155",
                        xytext=(3, 3), textcoords="offset points")
    ax.set_title("Risk vs return")
    ax.set_xlabel("Annualised volatility")
    ax.set_ylabel("30-day return")
    ax.xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(True, linestyle="--", linewidth=0.5, color="#e2e8f0")

    # ── BR: correlation heatmap, sorted by pillar then ticker (classified only) ──
    ax = axes[1, 1]
    ticker_to_idx = {t: i for i, t in enumerate(tickers)}
    classified_in_corr = [n for n in nodes if n["pillar"] and n["id"] in ticker_to_idx]
    classified_in_corr.sort(key=lambda n: (PILLAR_ORDER.index(n["pillar"]), n["id"]))
    if len(classified_in_corr) >= 4:
        order = [ticker_to_idx[n["id"]] for n in classified_in_corr]
        sub = corr[np.ix_(order, order)]
        im = ax.imshow(sub, cmap="RdYlBu_r", vmin=-1, vmax=1, aspect="auto")
        labels = [n["id"] for n in classified_in_corr]
        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=90, fontsize=6)
        ax.set_yticklabels(labels, fontsize=6)
        for tick, n in zip(ax.get_yticklabels(), classified_in_corr):
            tick.set_color(PILLAR_COLOR[n["pillar"]])
        for tick, n in zip(ax.get_xticklabels(), classified_in_corr):
            tick.set_color(PILLAR_COLOR[n["pillar"]])
        ax.set_title("Correlation heatmap (classified, sorted by pillar)")
        cbar = plt.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
        cbar.ax.tick_params(labelsize=8)
    else:
        ax.text(0.5, 0.5, "not enough classified data", ha="center", va="center",
                transform=ax.transAxes, color="#94a3b8")
        ax.set_axis_off()

    # Pillar legend (single, on the figure)
    handles = [mpatches.Patch(color=PILLAR_COLOR[p],
               label=p if p else "context (unclassified)")
               for p in PILLAR_ORDER]
    fig.legend(handles=handles, loc="lower center",
               bbox_to_anchor=(0.5, -0.005), ncol=5,
               frameon=False, fontsize=10)

    plt.tight_layout(rect=[0, 0.03, 1, 0.97])
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return buf.getvalue()


PLOTLY_PILLAR_COLOR = {
    "semiconductor":  "#2563eb",
    "infrastructure": "#ea580c",
    "equipment":      "#7c3aed",
    "energy":         "#16a34a",
}
PLOTLY_CTX_COLOR = "#cbd5e0"
PLOTLY_PILLAR_ORDER = ["semiconductor", "equipment", "infrastructure", "energy"]


def _plotly_hover(n):
    return (f"<b>{n['id']} {n['name']}</b><br>"
            f"{(n['pillar'] or 'unclassified')} / {n['node'] or '—'}<br>"
            f"vol {n['vol']*100:.1f}% · 30d {n['ret_30d']*100:+.1f}%")


def _add_cluster_traces(fig, snap, *, row=None, col=None, show_legend=True):
    """Add supply-chain edges + context + per-pillar scatter (X=x, Y=y)."""
    import plotly.graph_objects as go
    nodes = snap["nodes"]
    by_id = {n["id"]: n for n in nodes}
    target = dict(row=row, col=col) if row else {}

    # Supply-chain edges
    edge_x, edge_y = [], []
    for e in snap["edges"]:
        a, b = by_id.get(e["from"]), by_id.get(e["to"])
        if not a or not b: continue
        edge_x += [a["x"], b["x"], None]
        edge_y += [a["y"], b["y"], None]
    if edge_x:
        fig.add_trace(go.Scatter(
            x=edge_x, y=edge_y, mode="lines",
            line=dict(color="rgba(251,191,36,0.55)", width=1),
            hoverinfo="skip", showlegend=False, name="supply",
        ), **target)

    # Context underlay
    ctx = [n for n in nodes if not n["pillar"]]
    if ctx:
        fig.add_trace(go.Scatter(
            x=[n["x"] for n in ctx], y=[n["y"] for n in ctx],
            mode="markers", marker=dict(size=4, color=PLOTLY_CTX_COLOR, opacity=0.6),
            hovertemplate=[_plotly_hover(n) + "<extra></extra>" for n in ctx],
            showlegend=show_legend, name="context", legendgroup="context",
        ), **target)

    # Per-pillar
    for pillar in PLOTLY_PILLAR_ORDER:
        ns = [n for n in nodes if n["pillar"] == pillar]
        if not ns: continue
        sizes = [max(7, min(18, n["vol"] * 25)) for n in ns]
        fig.add_trace(go.Scatter(
            x=[n["x"] for n in ns], y=[n["y"] for n in ns],
            mode="markers+text",
            marker=dict(size=sizes, color=PLOTLY_PILLAR_COLOR[pillar],
                        opacity=0.9, line=dict(width=0.5, color="white")),
            text=[n["id"] for n in ns], textposition="top right",
            textfont=dict(size=8, color="#475569"),
            hovertemplate=[_plotly_hover(n) + "<extra></extra>" for n in ns],
            legendgroup=pillar, name=pillar, showlegend=show_legend,
        ), **target)


def _add_xy_panel_traces(fig, snap, *, x_field, y_field, row=None, col=None,
                         show_legend=True):
    """Generic context + per-pillar scatter for any (x_field, y_field) panel."""
    import plotly.graph_objects as go
    nodes = snap["nodes"]
    target = dict(row=row, col=col) if row else {}

    ctx = [n for n in nodes if not n["pillar"]]
    if ctx:
        fig.add_trace(go.Scatter(
            x=[n[x_field] for n in ctx], y=[n[y_field] for n in ctx],
            mode="markers", marker=dict(size=4, color=PLOTLY_CTX_COLOR, opacity=0.6),
            hovertemplate=[_plotly_hover(n) + "<extra></extra>" for n in ctx],
            showlegend=show_legend, name="context", legendgroup="context",
        ), **target)

    for pillar in PLOTLY_PILLAR_ORDER:
        ns = [n for n in nodes if n["pillar"] == pillar]
        if not ns: continue
        sizes = [max(7, min(18, n["vol"] * 25)) for n in ns]
        fig.add_trace(go.Scatter(
            x=[n[x_field] for n in ns], y=[n[y_field] for n in ns],
            mode="markers+text",
            marker=dict(size=sizes, color=PLOTLY_PILLAR_COLOR[pillar],
                        opacity=0.9, line=dict(width=0.5, color="white")),
            text=[n["id"] for n in ns], textposition="top right",
            textfont=dict(size=8, color="#475569"),
            hovertemplate=[_plotly_hover(n) + "<extra></extra>" for n in ns],
            legendgroup=pillar, name=pillar, showlegend=show_legend,
        ), **target)


def _add_heatmap_trace(fig, snap, corr, tickers, *, row=None, col=None,
                       colorbar_x=1.0, colorbar_y=0.5, colorbar_len=0.9):
    import plotly.graph_objects as go
    nodes = snap["nodes"]
    ticker_to_idx = {t: i for i, t in enumerate(tickers)}
    classified = [n for n in nodes if n["pillar"] and n["id"] in ticker_to_idx]
    classified.sort(key=lambda n: (PLOTLY_PILLAR_ORDER.index(n["pillar"]), n["id"]))
    if len(classified) < 4:
        return
    order = [ticker_to_idx[n["id"]] for n in classified]
    sub = corr[np.ix_(order, order)]
    labels = [n["id"] for n in classified]
    target = dict(row=row, col=col) if row else {}
    fig.add_trace(go.Heatmap(
        z=sub, x=labels, y=labels,
        colorscale="RdBu_r", zmid=0, zmin=-1, zmax=1,
        colorbar=dict(thickness=12, len=colorbar_len,
                      x=colorbar_x, y=colorbar_y,
                      title=dict(text="ρ", font=dict(size=10))),
        hovertemplate="%{y} ↔ %{x}<br>ρ = %{z:.2f}<extra></extra>",
        showscale=True,
    ), **target)


_AXIS_STYLE = dict(showline=True, linecolor="#94a3b8", linewidth=1,
                   gridcolor="#e2e8f0", zerolinecolor="#cbd5e0",
                   ticks="outside", tickcolor="#94a3b8")
_LIGHT_LAYOUT = dict(
    paper_bgcolor="white", plot_bgcolor="#fafbfc",
    font=dict(family="-apple-system,system-ui,sans-serif",
              size=11, color="#334155"),
    hovermode="closest",
    legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.10,
                bgcolor="rgba(248,250,252,0.85)", bordercolor="#e2e8f0",
                borderwidth=1, font=dict(size=11)),
)


def _fig_individual_cluster(snap):
    import plotly.graph_objects as go
    fig = go.Figure()
    _add_cluster_traces(fig, snap)
    fig.update_layout(
        title="Correlation cluster — top-down view",
        xaxis=dict(title="MDS axis 1", **_AXIS_STYLE),
        yaxis=dict(title="MDS axis 2", **_AXIS_STYLE),
        height=720, **_LIGHT_LAYOUT,
    )
    return fig


def _fig_individual_momentum(snap):
    import plotly.graph_objects as go
    fig = go.Figure()
    _add_xy_panel_traces(fig, snap, x_field="x", y_field="ret_30d")
    fig.update_layout(
        title="Cluster position vs 30-day return",
        xaxis=dict(title="MDS axis 1 (cluster)", **_AXIS_STYLE),
        yaxis=dict(title="30-day return", tickformat=".0%", **_AXIS_STYLE),
        height=720, **_LIGHT_LAYOUT,
    )
    return fig


def _fig_individual_risk(snap):
    import plotly.graph_objects as go
    fig = go.Figure()
    _add_xy_panel_traces(fig, snap, x_field="vol", y_field="ret_30d")
    fig.update_layout(
        title="Risk vs return",
        xaxis=dict(title="annualised volatility", tickformat=".0%", **_AXIS_STYLE),
        yaxis=dict(title="30-day return", tickformat=".0%", **_AXIS_STYLE),
        height=720, **_LIGHT_LAYOUT,
    )
    return fig


def _fig_individual_heatmap(snap, corr, tickers):
    import plotly.graph_objects as go
    fig = go.Figure()
    _add_heatmap_trace(fig, snap, corr, tickers, colorbar_x=1.02)
    fig.update_layout(
        title="Correlation heatmap (classified, sorted by pillar)",
        xaxis=dict(showgrid=False, **_AXIS_STYLE),
        yaxis=dict(showgrid=False, autorange="reversed", **_AXIS_STYLE),
        height=720,
        paper_bgcolor="white", plot_bgcolor="#fafbfc",
        font=dict(family="-apple-system,system-ui,sans-serif",
                  size=11, color="#334155"),
    )
    return fig


def _fig_combined(snap, corr, tickers):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "Correlation cluster (top-down)",
            "Cluster position vs 30d return",
            "Risk vs return",
            "Correlation heatmap (classified, sorted by pillar)",
        ),
        horizontal_spacing=0.08, vertical_spacing=0.10,
    )
    _add_cluster_traces(fig, snap, row=1, col=1, show_legend=True)
    _add_xy_panel_traces(fig, snap, x_field="x", y_field="ret_30d",
                         row=1, col=2, show_legend=False)
    _add_xy_panel_traces(fig, snap, x_field="vol", y_field="ret_30d",
                         row=2, col=1, show_legend=False)
    _add_heatmap_trace(fig, snap, corr, tickers,
                       row=2, col=2, colorbar_x=1.0, colorbar_y=0.22, colorbar_len=0.4)
    # Layout
    fig.update_layout(
        title=dict(text=f"<b>Taiwan AI universe</b> — {snap['n_tickers']} tickers · "
                        f"window {snap['window_days']}d · as of {snap['asof']}",
                   x=0.02, xanchor="left", font=dict(size=14, color="#0f172a")),
        margin=dict(l=50, r=50, t=80, b=50),
        height=820, **_LIGHT_LAYOUT,
    )
    fig.update_xaxes(title_text="MDS axis 1", row=1, col=1, **_AXIS_STYLE)
    fig.update_yaxes(title_text="MDS axis 2", row=1, col=1, **_AXIS_STYLE)
    fig.update_xaxes(title_text="MDS axis 1 (cluster)", row=1, col=2,
                     matches="x1", **_AXIS_STYLE)
    fig.update_yaxes(title_text="30d return", tickformat=".0%",
                     row=1, col=2, **_AXIS_STYLE)
    fig.update_xaxes(title_text="annualised volatility", tickformat=".0%",
                     row=2, col=1, **_AXIS_STYLE)
    fig.update_yaxes(title_text="30d return", tickformat=".0%",
                     row=2, col=1, **_AXIS_STYLE)
    fig.update_xaxes(showgrid=False, row=2, col=2)
    fig.update_yaxes(showgrid=False, autorange="reversed", row=2, col=2)
    return fig


def build_plotly_2d_html(snap: dict, corr: np.ndarray, tickers: list[str]) -> str:
    """Tabbed HTML page: combined 2x2 plus 4 individual full-size views."""
    PILLAR_COLOR = PLOTLY_PILLAR_COLOR

    PLOT_CFG = {
        "displayModeBar": True, "displaylogo": False, "responsive": True,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    }

    def fig_to_div(fig, div_id, include_js):
        return fig.to_html(
            full_html=False,
            include_plotlyjs="cdn" if include_js else False,
            div_id=div_id, config=PLOT_CFG,
        )

    div_combined = fig_to_div(_fig_combined(snap, corr, tickers),
                              "fig-all", include_js=True)
    div_cluster  = fig_to_div(_fig_individual_cluster(snap),
                              "fig-cluster", include_js=False)
    div_momentum = fig_to_div(_fig_individual_momentum(snap),
                              "fig-momentum", include_js=False)
    div_risk     = fig_to_div(_fig_individual_risk(snap),
                              "fig-risk", include_js=False)
    div_heatmap  = fig_to_div(_fig_individual_heatmap(snap, corr, tickers),
                              "fig-heatmap", include_js=False)

    disc = snap.get("discovery", [])
    rows = "".join(
        f'<li><b>{c["ticker"]}</b> {c["name"]} \u2192 '
        f'<span style="color:{PILLAR_COLOR.get(c["suggested_pillar"], "#64748b")}">'
        f'{c["suggested_pillar"]}</span> '
        f'<span style="color:#64748b">(\u03c1\u2248{c["conviction"]})</span></li>'
        for c in disc[:10]
    )
    disc_block = (f'<div class="disc"><h2>Discovery candidates</h2>'
                  f'<ol>{rows}</ol></div>' if rows else "")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>alphatecx \u00b7 TW correlation map</title>
<style>
  html,body {{ margin:0; padding:0; background:#ffffff; color:#0f172a;
    font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif; }}
  .wrap {{ max-width:1500px; margin:0 auto; padding:14px 18px 28px; }}
  .header {{ display:flex; justify-content:space-between; align-items:flex-end;
            margin-bottom:10px; gap:12px; flex-wrap:wrap; }}
  .header h1 {{ font-size:16px; font-weight:600; margin:0; color:#0f172a; }}
  .meta {{ color:#64748b; font-size:12px; }}
  .tabs {{ display:flex; gap:4px; margin:6px 0 10px; flex-wrap:wrap;
          border-bottom:1px solid #e2e8f0; }}
  .tab {{ padding:8px 14px; border:1px solid transparent; border-bottom:none;
        background:transparent; color:#64748b; font-size:13px; cursor:pointer;
        font-family:inherit; border-radius:6px 6px 0 0; margin-bottom:-1px; }}
  .tab:hover {{ color:#0f172a; background:#f8fafc; }}
  .tab.active {{ background:#ffffff; color:#0f172a; font-weight:600;
                border:1px solid #e2e8f0; border-bottom:1px solid #ffffff; }}
  .panel {{ display:none; }}
  .panel.active {{ display:block; }}
  .hint {{ color:#94a3b8; font-size:12px; margin:0 0 6px; }}
  .disc {{ margin-top:14px; padding:14px 18px; background:#f8fafc;
    border:1px solid #e2e8f0; border-radius:8px; max-width:640px; }}
  .disc h2 {{ font-size:14px; margin:0 0 8px; color:#0f172a; }}
  .disc ol {{ margin:0; padding-left:20px; font-size:13px; line-height:1.7; }}
</style></head><body>
<div class="wrap">
  <div class="header">
    <h1>Taiwan AI universe \u2014 correlation map</h1>
    <div class="meta">{snap["n_tickers"]} tickers \u00b7 window {snap["window_days"]}d \u00b7 as of {snap["asof"]}</div>
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="all">All (2\u00d72)</button>
    <button class="tab" data-tab="cluster">Cluster</button>
    <button class="tab" data-tab="momentum">Cluster vs return</button>
    <button class="tab" data-tab="risk">Risk vs return</button>
    <button class="tab" data-tab="heatmap">Correlation heatmap</button>
  </div>
  <p class="hint">Drag to pan \u00b7 scroll to zoom \u00b7 double-click to reset \u00b7 click a pillar in the legend to toggle.</p>
  <div class="panel active" data-panel="all">{div_combined}</div>
  <div class="panel" data-panel="cluster">{div_cluster}</div>
  <div class="panel" data-panel="momentum">{div_momentum}</div>
  <div class="panel" data-panel="risk">{div_risk}</div>
  <div class="panel" data-panel="heatmap">{div_heatmap}</div>
  {disc_block}
</div>
<script>
(function() {{
  const tabs   = document.querySelectorAll('.tab');
  const panels = document.querySelectorAll('.panel');
  function show(name) {{
    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    panels.forEach(p => p.classList.toggle('active', p.dataset.panel === name));
    const active = document.querySelector('.panel.active .js-plotly-plot');
    if (active && window.Plotly) window.Plotly.Plots.resize(active);
    if (history.replaceState) history.replaceState(null, '', '#' + name);
  }}
  tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.tab)));
  const hash = (location.hash || '').replace(/^#/, '');
  if (hash && document.querySelector(`.panel[data-panel="${{hash}}"]`)) show(hash);
}})();
</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=120)
    ap.add_argument("--out-json", type=str,
                    default="mcp_server/api/static/graph_snapshot.json")
    ap.add_argument("--out-html", type=str,
                    default="mcp_server/api/static/graph.html")
    args = ap.parse_args()

    snapshot, corr, tickers = build_snapshot(window_days=args.window)

    json_path = Path(args.out_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(snapshot, indent=2))

    # PNG (static, Telegram/reports)
    png = build_matplotlib_panels(snapshot, corr, tickers)
    png_path = Path(args.out_json).parent / "graph.png"
    png_path.write_bytes(png)

    # HTML (interactive, web viewer) — plotly 2D with linked axes
    html_path = Path(args.out_html)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_plotly_2d_html(snapshot, corr, tickers))

    log.info("Wrote %s + %s + %s (%d nodes, %d edges, %d corr_edges)",
             json_path, html_path, png_path,
             len(snapshot["nodes"]), len(snapshot["edges"]),
             len(snapshot["corr_edges"]))


if __name__ == "__main__":
    main()
