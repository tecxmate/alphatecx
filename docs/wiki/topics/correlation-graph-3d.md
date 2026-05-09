---
title: 3D Correlation Network Graph
type: topic
slug: correlation-graph-3d
date: 2026-05-10
updated: 2026-05-10b
attributed_to: [claude-code]
belongs_to: [alphatecx, taiwan-ai-supply-chain]
source: chat
status: active
tags: [visualization, quant, correlation, three-js, supply-chain]
related: [supply-chain-audit-2026-05-10, taiwan-ai-supply-chain, alphatecx]
---

# 3D Correlation Network Graph

A web viewer that shows the entire TW universe as a 3D point cloud where two stocks are spatially close iff their daily returns are correlated. Edges overlay explicit supply-chain relationships and high correlation pairs. Builds on top of `raw_twse_ohlcv`, `dim_ticker`, and the new `sc_edges` table.

Origin: user request 2026-05-10 — *"company relational cluster graph 3D, how close they are vs how much they move … get as close as possible to the top hedge fund investment banks way of analysis."* The intent is a visualization that no TW retail/commercial app currently offers — temporal correlation network animation for the AI supply chain.

---

## Architecture

```
raw_twse_ohlcv (Neon)
        ↓
src/quant/correlation_snapshot.py     (one-shot, suitable for cron)
        ↓
mcp_server/api/static/graph_snapshot.json     (committed to repo)
        ↓
mcp_server/api/graph_view.py    (HTML + JSON endpoints)
        ↓
@ /g/{MCP_BEARER_TOKEN}/         (URL-as-secret, same auth model as MCP)
```

The snapshot is a pre-computed artifact, not live. Cron regenerates it; users hit a static JSON endpoint. No on-demand compute. This is intentional — the correlation matrix is O(N²) and not cheap to recompute per request.

---

## The math (why this works)

Daily log returns `r_{t,i}` for each ticker `i` over a configurable window (default 120 days). Pairwise Pearson correlation `ρ_{ij}`, then **Mantegna distance**:

```
d_{ij} = sqrt(2 · (1 − ρ_{ij}))
```

This is the standard transform that turns a correlation matrix into a proper Euclidean distance matrix (positive-definite when `ρ ∈ [−1, 1]`). Then **classical MDS** (eigendecomposition of the double-centered squared-distance matrix) produces a 3D embedding that preserves pairwise distances as faithfully as a 3D space allows.

Why MDS rather than UMAP / t-SNE: MDS is deterministic, has no hyperparameters, and preserves global geometry (UMAP/t-SNE preserve local neighbourhoods at the cost of distorting distances). For the question *"how close are these stocks"* we want global geometry. UMAP can be a v2 if local cluster shape becomes more important than absolute distance.

Coordinates are normalised so the largest absolute coordinate equals 1, regardless of universe size — keeps the camera framing stable across snapshots.

---

## What the viewer shows

| Visual property | Mapped to |
|---|---|
| Node position (x,y,z) | Correlation distance from every other node |
| Node colour | `ai_pillar` (blue = semi, orange = infra, purple = equipment, green = energy, grey = unclassified) |
| Node size | Annualised volatility (capped) |
| Solid yellow lines | Explicit supply-chain edges (`sc_edges`) — opacity by `confidence` |
| Faint blue lines | Correlation pairs ρ ≥ 0.7 between two classified nodes — opacity scales with ρ |
| Hover tooltip | ticker · name · pillar/node · vol · 30d return · US partners |
| Toggles | context tickers · correlation edges · supply edges · labels |

Frontend: **plotly** (pure Python). The snapshot generator emits a self-contained HTML file via `plotly.graph_objects.Figure.to_html()` with `include_plotlyjs="cdn"`. Plotly's WebGL backend gives drag-to-rotate, scroll-zoom, and hover tooltips out of the box. The FastAPI route just reads and returns the file (~33 LOC of Python; no JS, no importmap, no manual scaffolding).

Earlier iteration used hand-rolled three.js (~400 LOC of JS with custom drop-lines, compass, camera presets). Replaced 2026-05-10 in favour of plotly because: (a) the custom features were nice-to-have, not essential; (b) maintaining JS in a Python project costs more than the visual polish was worth; (c) plotly's modebar gives camera reset / zoom / pan for free; (d) we still get camera presets via plotly's `updatemenus` buttons.

---

## Auth model

Same URL-as-secret as MCP: `/g/{MCP_BEARER_TOKEN}/` and `/g/{MCP_BEARER_TOKEN}/data.json`. The auth gate in `index.py` accepts both `/mcp/{token}/*` and `/g/{token}/*`. Wrong token → 404.

Trade-off considered: a separate `GRAPH_TOKEN` would let the user share the viewer URL without exposing MCP. For v1 we reuse the same token (YAGNI). If sharing without exposing MCP becomes important, add a second env var and a separate prefix.

---

## How to regenerate

```bash
# After OHLCV is up to date:
python -m src.quant.correlation_snapshot --window 120
# Writes mcp_server/api/static/graph_snapshot.json
# Commit + deploy to push the new snapshot to production
```

Suggested cron cadence: nightly after `daily_harvest` finishes (post-close in Taipei). The `--window` parameter trades stability (longer window = smoother) against responsiveness to regime changes. 90-120 trading days is the sweet spot for cluster stability.

Failure mode: if the snapshot file is missing in production, the data endpoint returns 503 and the viewer shows "Error loading snapshot." Cron should always overwrite, never delete.

---

## Universe selection

Targets for the OHLCV backfill come from `src/backfill/run.py:_ohlcv_targets()` which now returns:

1. All classified tickers (`dim_supply_chain`).
2. The 0050 ETF benchmark.
3. Top N (default 150) unclassified tickers ranked by `SUM(ABS(total_net))` from `raw_twse_t86`, excluding ETFs and warrants. These appear in the graph as 35%-opacity grey "context" nodes.

Net result: ~50 classified + 150 context + benchmark ≈ **200 tickers** in the graph, with the AI cluster in colour against the broader market in grey.

---

## Open follow-ups

- **Time animation.** Currently a single static snapshot. With multiple historical snapshots stored, the viewer could scrub through time and show how clusters tighten / fragment in different regimes. Requires a `graph_snapshots` table and a snapshot-archive cron step.
- **Lead-lag / Granger overlay.** Edges representing "stock A's flow predicts stock B's price N days later." Particularly valuable for the supply chain (TSMC → ASE → ODMs).
- **Discovery integration.** Highlight unclassified context tickers that cluster strongly with classified ones — they are likely supply-chain peers we haven't mapped yet. See task #17.
- **PCA risk decomposition.** Show which latent factor (PC1, PC2, PC3) each node loads on. PC1 is usually market β; PC2/PC3 often have an interpretable "AI vs traditional" or "memory vs logic" axis.

---

## Files

- `src/quant/correlation_snapshot.py` — pipeline; `build_plotly_html()` renders the figure
- `mcp_server/api/graph_view.py` — 33-line FastAPI view, just serves the prebuilt file
- `mcp_server/api/static/graph.html` — generated plotly viewer (committed)
- `mcp_server/api/static/graph_snapshot.json` — same data in JSON for programmatic access
- `mcp_server/api/index.py` — auth gate & route registration
- `sql/009_sc_revamp.sql` — `sc_edges` table referenced by the snapshot
