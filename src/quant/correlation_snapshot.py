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


def fetch_all_tickers() -> list[dict]:
    """Every dim_ticker row — used to power the in-page search/classify UI."""
    sql = """
        SELECT ticker_id, company_name, ai_pillar, node
          FROM dim_ticker
         ORDER BY ticker_id
    """
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [
            {"id": tid, "name": name or tid, "pillar": pillar, "node": node}
            for tid, name, pillar, node in cur.fetchall()
        ]


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


def build_plotly_2d_html(snap: dict, corr: np.ndarray, tickers: list[str],
                         directory: list[dict] | None = None) -> str:
    """Tabbed HTML page: combined 2x2 plus 4 individual full-size views.

    `directory` is the full dim_ticker list (id/name/pillar/node) embedded
    into the page for client-side ticker search + classify.
    """
    PILLAR_COLOR = PLOTLY_PILLAR_COLOR
    directory_json = json.dumps(directory or [], separators=(",", ":"))

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

    def _neighbour_text(candidate: dict) -> str:
        return "; ".join(
            f"{n['id']} {n['rho']}"
            for n in (candidate.get("neighbours") or [])[:4]
        )

    disc_rows = "".join(
        f'<tr data-q="{c["ticker"]} {c["name"]} {c["suggested_pillar"]} {c.get("suggested_node") or ""}">'
        f'<td><b>{c["ticker"]}</b></td>'
        f'<td>{c["name"]}</td>'
        f'<td><span class="pill" style="--pill:{PILLAR_COLOR.get(c["suggested_pillar"], "#64748b")}">{c["suggested_pillar"]}</span></td>'
        f'<td>{c.get("suggested_node") or ""}</td>'
        f'<td>{c["conviction"]}</td>'
        f'<td>{_neighbour_text(c)}</td>'
        f'</tr>'
        for c in disc
    )
    disc_table = (
        '<div class="table-tools"><input class="table-filter" data-target="discovery-table" '
        'type="search" placeholder="Filter discovery candidates"></div>'
        '<div class="table-scroll"><table id="discovery-table" class="terminal-table">'
        '<thead><tr><th>Ticker</th><th>Name</th><th>Suggested pillar</th>'
        '<th>Suggested node</th><th>Conviction</th><th>Top neighbours</th></tr></thead>'
        f'<tbody>{disc_rows}</tbody></table></div>'
        if disc_rows else '<div class="empty">No discovery candidates above threshold.</div>'
    )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>alphatecx \u00b7 TW correlation map</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f4f6f8; --surface:#ffffff;
    --surface-2:#eef2f6; --line:#cbd5e1; --line-soft:#e2e8f0;
    --text:#0f172a; --muted:#64748b; --link:#0f66d0; --accent:#f59e0b; }}
  :root[data-theme="dark"] {{ color-scheme: dark; --bg:#080b10; --surface:#0f141b;
    --surface-2:#151c25; --line:#2b3746; --line-soft:#1d2733;
    --text:#d8dee9; --muted:#8b98a8; --link:#61a5ff; --accent:#f6b73c; }}
  html,body {{ margin:0; padding:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;
    font-size:13px; line-height:1.42; }}
  .wrap {{ max-width:1560px; margin:0 auto; padding:10px 14px 22px; }}
  .header {{ display:flex; justify-content:space-between; align-items:flex-end;
    margin-bottom:8px; gap:12px; flex-wrap:wrap; border-bottom:1px solid var(--line);
    padding-bottom:8px; }}
  .header h1 {{ font-size:17px; font-weight:650; margin:0; color:var(--text); }}
  .meta {{ color:var(--muted); font-size:11px; }}
  .header-actions {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .terminal-btn {{ border:1px solid var(--line); background:var(--surface);
    color:var(--text); border-radius:4px; padding:4px 8px; font:inherit;
    font-size:11px; cursor:pointer; }}
  .tabs {{ display:flex; gap:0; margin:8px 0; flex-wrap:wrap;
    border:1px solid var(--line); background:var(--surface); }}
  .tab {{ padding:7px 11px; border:0; border-right:1px solid var(--line);
    background:transparent; color:var(--muted); font-size:12px; cursor:pointer;
    font-family:inherit; white-space:nowrap; }}
  .tab:hover {{ color:var(--text); background:var(--surface-2); }}
  .tab.active {{ background:var(--text); color:var(--surface); font-weight:650; }}
  :root[data-theme="dark"] .tab.active {{ background:#d8dee9; color:#080b10; }}
  .panel {{ display:none; }}
  .panel.active {{ display:block; }}
  .panel .js-plotly-plot {{ background:var(--surface); border:1px solid var(--line); }}
  .hint {{ color:var(--muted); font-size:11px; margin:0 0 6px; }}
  .hint.hidden {{ display:none; }}
  .disc {{ margin-top:12px; padding:10px 12px; background:var(--surface);
    border:1px solid var(--line); max-width:640px; }}
  .disc h2 {{ font-size:12px; margin:0 0 7px; color:var(--muted); text-transform:uppercase; }}
  .disc ol {{ margin:0; padding-left:18px; font-size:12px; line-height:1.6; }}
  .classify {{ margin:6px 0 10px; padding:8px 10px; background:var(--surface);
    border:1px solid var(--line); display:flex; gap:7px;
    align-items:center; flex-wrap:wrap; font-size:12px; position:relative; }}
  .classify input[type=text], .classify select {{ font:inherit; padding:5px 8px;
    border:1px solid var(--line); border-radius:4px; background:var(--surface); color:var(--text); }}
  .classify input#cls-search {{ width:280px; }}
  .classify input#cls-node {{ width:180px; }}
  .classify button {{ font:inherit; padding:5px 12px; background:var(--text);
    color:var(--surface); border:none; border-radius:4px; cursor:pointer; }}
  .classify button:disabled {{ background:var(--muted); cursor:not-allowed; }}
  .classify .meta {{ color:var(--muted); font-size:11px; }}
  .classify .msg.ok {{ color:#16a34a; }}
  .classify .msg.err {{ color:#dc2626; }}
  .cls-suggest {{ position:absolute; top:42px; left:42px; width:280px;
    background:var(--surface); border:1px solid var(--line); border-radius:4px;
    max-height:240px;
    overflow-y:auto; z-index:50; display:none; }}
  .cls-suggest div {{ padding:6px 10px; cursor:pointer; font-size:13px;
    border-bottom:1px solid var(--line-soft); }}
  .cls-suggest div:hover, .cls-suggest div.active {{ background:var(--surface-2); }}
  .cls-suggest .pill {{ float:right; font-size:11px; color:var(--muted); }}
  .table-tools {{ margin:6px 0 8px; }}
  .table-filter {{ width:min(420px, 100%); box-sizing:border-box; padding:6px 9px;
    border:1px solid var(--line); background:var(--surface); color:var(--text);
    font:inherit; font-size:12px; }}
  .table-scroll {{ overflow:auto; border:1px solid var(--line); background:var(--surface);
    -webkit-overflow-scrolling:touch; }}
  .terminal-table {{ width:100%; min-width:860px; border-collapse:collapse;
    font-size:12px; font-variant-numeric:tabular-nums; }}
  .terminal-table th {{ text-align:left; color:var(--muted); background:var(--surface-2);
    border-bottom:1px solid var(--line); border-right:1px solid var(--line-soft);
    padding:6px 8px; text-transform:uppercase; font-size:11px; }}
  .terminal-table td {{ border-bottom:1px solid var(--line-soft);
    border-right:1px solid var(--line-soft); padding:5px 8px; vertical-align:middle; }}
  .terminal-table tr:hover {{ background:var(--surface-2); }}
  .terminal-table select,.terminal-table input {{ width:100%; box-sizing:border-box;
    border:1px solid var(--line); background:var(--surface); color:var(--text);
    padding:4px 6px; font:inherit; font-size:12px; }}
  .terminal-table button {{ border:1px solid var(--line); background:var(--text);
    color:var(--surface); padding:4px 8px; font:inherit; font-size:11px; cursor:pointer; }}
  .row-msg {{ margin-left:7px; color:var(--muted); font-size:11px; }}
  .row-msg.ok {{ color:#16a34a; }}
  .row-msg.err {{ color:#dc2626; }}
  .pill {{ display:inline-block; padding:2px 7px; color:white; background:var(--pill);
    font-weight:650; border-radius:999px; white-space:nowrap; }}
  .empty {{ padding:18px; border:1px dashed var(--line); color:var(--muted);
    background:var(--surface); }}
  .pager {{ display:flex; align-items:center; gap:8px; margin-top:8px; color:var(--muted);
    font-size:11px; }}
  .pager button {{ border:1px solid var(--line); background:var(--surface);
    color:var(--text); padding:4px 8px; font:inherit; font-size:11px; cursor:pointer; }}
  .pager button:disabled {{ opacity:0.4; cursor:not-allowed; }}
  @media (max-width: 820px) {{
    .wrap {{ padding:8px; }}
    .header-actions {{ width:100%; justify-content:space-between; }}
    .tabs {{ flex-wrap:nowrap; overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    .tab {{ flex:0 0 auto; padding:7px 10px; font-size:11px; }}
    .classify {{ display:grid; grid-template-columns:1fr; }}
    .classify input#cls-search,.classify input#cls-node,.classify select,.classify button {{ width:100%; box-sizing:border-box; }}
    .cls-suggest {{ left:10px; right:10px; width:auto; top:76px; }}
    .panel {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
    .panel .js-plotly-plot {{ min-width:720px; }}
    .terminal-table {{ min-width:760px; }}
  }}
</style></head><body>
<div class="wrap">
  <div class="header">
    <h1>Taiwan AI universe \u2014 correlation map</h1>
    <div class="header-actions">
      <button id="theme-toggle" class="terminal-btn" type="button">Dark</button>
      <div class="meta">{snap["n_tickers"]} tickers \u00b7 window {snap["window_days"]}d \u00b7 as of {snap["asof"]}</div>
    </div>
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="all">All (2\u00d72)</button>
    <button class="tab" data-tab="cluster">Cluster</button>
    <button class="tab" data-tab="momentum">Cluster vs return</button>
    <button class="tab" data-tab="risk">Risk vs return</button>
    <button class="tab" data-tab="heatmap">Correlation heatmap</button>
    <button class="tab" data-tab="discovery">Discovery candidates</button>
  </div>
  <p id="graph-hint" class="hint">Drag to pan \u00b7 scroll to zoom \u00b7 double-click to reset \u00b7 click a pillar in the legend to toggle.</p>
  <div class="classify">
    <span>\U0001f50d</span>
    <input id="cls-search" type="text" placeholder="Search ticker (e.g. 3583, ChipMOS)\u2026" autocomplete="off">
    <div id="cls-suggest" class="cls-suggest"></div>
    <select id="cls-pillar">
      <option value="">\u2014 pillar \u2014</option>
      <option value="semiconductor">semiconductor</option>
      <option value="equipment">equipment</option>
      <option value="infrastructure">infrastructure</option>
      <option value="energy">energy</option>
    </select>
    <input id="cls-node" type="text" placeholder="node (e.g. testing-probing)" autocomplete="off">
    <button id="cls-save" disabled>Save</button>
    <span id="cls-meta" class="meta"></span>
    <span id="cls-msg"  class="msg"></span>
  </div>
  <div class="panel active" data-panel="all">{div_combined}</div>
  <div class="panel" data-panel="cluster">{div_cluster}</div>
  <div class="panel" data-panel="momentum">{div_momentum}</div>
  <div class="panel" data-panel="risk">{div_risk}</div>
  <div class="panel" data-panel="heatmap">{div_heatmap}</div>
  <div class="panel" data-panel="discovery">{disc_table}</div>
</div>
<script>
(function() {{
  const root = document.documentElement;
  const savedTheme = localStorage.getItem('alphatecx-theme');
  if (savedTheme === 'dark' || savedTheme === 'light') root.dataset.theme = savedTheme;
  const btn = document.getElementById('theme-toggle');
  function sync() {{ if (btn) btn.textContent = (root.dataset.theme || 'light') === 'dark' ? 'Light' : 'Dark'; }}
  if (btn) {{
    btn.addEventListener('click', () => {{
      const next = (root.dataset.theme || 'light') === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next;
      localStorage.setItem('alphatecx-theme', next);
      sync();
    }});
    sync();
  }}
}})();
(function() {{
  const tabs   = document.querySelectorAll('.tab');
  const panels = document.querySelectorAll('.panel');
  const graphTabs = new Set(['all', 'cluster', 'momentum', 'risk', 'heatmap']);
  const graphHint = document.getElementById('graph-hint');
  function show(name) {{
    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    panels.forEach(p => p.classList.toggle('active', p.dataset.panel === name));
    if (graphHint) graphHint.classList.toggle('hidden', !graphTabs.has(name));
    const active = document.querySelector('.panel.active .js-plotly-plot');
    if (active && window.Plotly) window.Plotly.Plots.resize(active);
    if (history.replaceState) history.replaceState(null, '', '#' + name);
  }}
  tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.tab)));
  const hash = (location.hash || '').replace(/^#/, '');
  if (hash && document.querySelector(`.panel[data-panel="${{hash}}"]`)) show(hash);
}})();
(function() {{
  document.querySelectorAll('.table-filter').forEach(input => {{
    input.addEventListener('input', () => {{
      const table = document.getElementById(input.dataset.target);
      const q = input.value.trim().toLowerCase();
      table.querySelectorAll('tbody tr').forEach(row => {{
        row.style.display = q && !(row.dataset.q || row.textContent).toLowerCase().includes(q) ? 'none' : '';
      }});
    }});
  }});
}})();
(function() {{
  const DIRECTORY = {directory_json};
  const TOKEN     = location.pathname.split('/')[2] || '';
  const $search   = document.getElementById('cls-search');
  const $sugg     = document.getElementById('cls-suggest');
  const $pillar   = document.getElementById('cls-pillar');
  const $node     = document.getElementById('cls-node');
  const $save     = document.getElementById('cls-save');
  const $meta     = document.getElementById('cls-meta');
  const $msg      = document.getElementById('cls-msg');
  let selected = null;
  let active   = -1;

  function match(q) {{
    q = q.trim().toLowerCase();
    if (!q) return [];
    const out = [];
    for (const t of DIRECTORY) {{
      if (t.id.toLowerCase().includes(q) || t.name.toLowerCase().includes(q)) {{
        out.push(t);
        if (out.length >= 25) break;
      }}
    }}
    return out;
  }}
  function render(list) {{
    if (!list.length) {{ $sugg.style.display = 'none'; $sugg.innerHTML = ''; return; }}
    $sugg.innerHTML = list.map((t, i) =>
      `<div data-idx="${{i}}"><b>${{t.id}}</b> ${{t.name}}` +
      (t.pillar ? `<span class="pill">${{t.pillar}}${{t.node ? ' / ' + t.node : ''}}</span>` : `<span class="pill">unclassified</span>`) +
      `</div>`
    ).join('');
    $sugg.style.display = 'block';
    active = -1;
    $sugg.querySelectorAll('div').forEach(d => {{
      d.addEventListener('mousedown', e => {{ e.preventDefault(); choose(list[+d.dataset.idx]); }});
    }});
    window._suggList = list;
  }}
  function choose(t) {{
    selected = t;
    $search.value = t.id + ' ' + t.name;
    $pillar.value = t.pillar || '';
    $node.value   = t.node   || '';
    $meta.textContent = t.pillar ? `currently: ${{t.pillar}}${{t.node ? ' / ' + t.node : ''}}` : 'currently: unclassified';
    $msg.textContent = '';
    $sugg.style.display = 'none';
    $save.disabled = false;
  }}
  $search.addEventListener('input', () => {{
    selected = null; $save.disabled = true; $meta.textContent = '';
    render(match($search.value));
  }});
  $search.addEventListener('keydown', e => {{
    const list = window._suggList || [];
    if (e.key === 'ArrowDown') {{ active = Math.min(active + 1, list.length - 1); paintActive(); e.preventDefault(); }}
    else if (e.key === 'ArrowUp') {{ active = Math.max(active - 1, 0); paintActive(); e.preventDefault(); }}
    else if (e.key === 'Enter' && active >= 0) {{ choose(list[active]); e.preventDefault(); }}
    else if (e.key === 'Escape') {{ $sugg.style.display = 'none'; }}
  }});
  function paintActive() {{
    $sugg.querySelectorAll('div').forEach((d, i) => d.classList.toggle('active', i === active));
  }}
  document.addEventListener('click', e => {{
    if (!e.target.closest('.classify')) $sugg.style.display = 'none';
  }});

  $save.addEventListener('click', async () => {{
    if (!selected) return;
    const pillar = $pillar.value || null;
    const node   = $node.value.trim() || null;
    if (!pillar) {{ $msg.textContent = 'pick a pillar'; $msg.className = 'msg err'; return; }}
    $save.disabled = true; $msg.textContent = 'saving…'; $msg.className = 'msg';
    try {{
      const r = await fetch(`/g/${{TOKEN}}/classify`, {{
        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ ticker_id: selected.id, pillar, node }}),
      }});
      const j = await r.json();
      if (!r.ok || !j.ok) throw new Error(j.error || 'save failed');
      $msg.textContent = 'saved · reload the page to see it on the graph';
      $msg.className = 'msg ok';
      const idx = DIRECTORY.findIndex(t => t.id === selected.id);
      if (idx >= 0) {{ DIRECTORY[idx].pillar = pillar; DIRECTORY[idx].node = node; }}
      $meta.textContent = `currently: ${{pillar}}${{node ? ' / ' + node : ''}}`;
    }} catch (err) {{
      $msg.textContent = 'error: ' + err.message;
      $msg.className = 'msg err';
    }} finally {{
      $save.disabled = false;
    }}
  }});

}})();
</script>
</body></html>"""


def build_combined_png(snap: dict, corr: np.ndarray, tickers: list[str]) -> bytes:
    """Render the same 2x2 layout the web viewer uses, as a static PNG.

    One rendering codepath shared with the HTML viewer (`_fig_combined`).
    Uses Plotly's Kaleido image engine; no matplotlib dependency.
    """
    fig = _fig_combined(snap, corr, tickers)
    return fig.to_image(format="png", width=1400, height=1100, scale=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=120)
    ap.add_argument("--out-json", type=str,
                    default="mcp_server/api/static/graph_snapshot.json")
    ap.add_argument("--out-html", type=str,
                    default="mcp_server/api/static/graph-view.html")
    args = ap.parse_args()

    snapshot, corr, tickers = build_snapshot(window_days=args.window)

    json_path = Path(args.out_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(snapshot, indent=2))

    # PNG (static, Telegram/reports) — same Plotly figure as the web viewer.
    png_path = Path(args.out_json).parent / "graph-image.png"
    png_path.write_bytes(build_combined_png(snapshot, corr, tickers))

    # HTML (interactive, web viewer) — plotly 2D with linked axes
    html_path = Path(args.out_html)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    directory = fetch_all_tickers()
    html_path.write_text(build_plotly_2d_html(snapshot, corr, tickers, directory))

    log.info("Wrote %s + %s + %s (%d nodes, %d edges, %d corr_edges)",
             json_path, html_path, png_path,
             len(snapshot["nodes"]), len(snapshot["edges"]),
             len(snapshot["corr_edges"]))


if __name__ == "__main__":
    main()
