"""Correlation-network graph viewer.

`GET /g/{TOKEN}/` regenerates the graph on demand from current DB state,
with a short in-memory TTL cache so back-to-back loads (pan, zoom, tab
swaps) don't pay the recompute cost. The committed `graph.png` /
`graph_snapshot.json` artifacts are still produced by the nightly CI job
and used by Telegram / programmatic clients.

Endpoints (mounted under /g/{TOKEN}/):
  GET  /g/{TOKEN}/             → live-rendered HTML (TTL-cached)
  GET  /g/{TOKEN}/graph.png    → committed PNG (Telegram-friendly)
  GET  /g/{TOKEN}/data.json    → committed snapshot JSON
  POST /g/{TOKEN}/classify     → upsert (pillar, node) into dim_ticker
"""
from __future__ import annotations

import json
import re
import time
import traceback
from html import escape
from pathlib import Path

import db_v2
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

_VALID_PILLARS = {"semiconductor", "equipment", "infrastructure", "energy"}
_TICKER_ID_RE  = re.compile(r"^[0-9A-Za-z]{1,8}$")
_NODE_RE       = re.compile(r"^[0-9A-Za-z][0-9A-Za-z\- _/]{0,63}$")

_STATIC = Path(__file__).parent / "static"
_HTML_PATH        = _STATIC / "graph.html"
_PNG_PATH         = _STATIC / "graph.png"
_JSON_PATH        = _STATIC / "graph_snapshot.json"
_DASHBOARD_PATH   = _STATIC / "dashboard.html"
_DASHBOARD_CSS    = _STATIC / "dashboard.css"
_DASHBOARD_JS     = _STATIC / "dashboard.js"
_TICKER_DIR       = _STATIC / "ticker"


_CACHE: dict = {"html": None, "expires_at": 0.0}
_CACHE_TTL_SECONDS = 60
_WINDOW_DAYS = 120


def _render_html() -> str:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.quant.correlation_snapshot import (
        build_plotly_2d_html,
        build_snapshot,
        fetch_all_tickers,
    )
    snapshot, corr, tickers = build_snapshot(window_days=_WINDOW_DAYS)
    return build_plotly_2d_html(snapshot, corr, tickers, fetch_all_tickers())


def _invalidate_cache() -> None:
    _CACHE["html"] = None
    _CACHE["expires_at"] = 0.0


def get_viewer_html() -> HTMLResponse:
    now = time.time()
    if _CACHE["html"] and now < _CACHE["expires_at"]:
        return HTMLResponse(content=_CACHE["html"])
    try:
        html = _render_html()
    except Exception as e:
        if _HTML_PATH.exists():
            return HTMLResponse(
                content=_HTML_PATH.read_text(),
                headers={"x-graph-fallback": f"{type(e).__name__}: {e}"[:200]},
            )
        raise HTTPException(503, f"graph render failed: {type(e).__name__}: {e}") from e
    _CACHE["html"] = html
    _CACHE["expires_at"] = now + _CACHE_TTL_SECONDS
    return HTMLResponse(content=html)


def get_graph_png() -> Response:
    if not _PNG_PATH.exists():
        raise HTTPException(503, "graph.png not yet generated")
    return Response(content=_PNG_PATH.read_bytes(), media_type="image/png")


def get_snapshot_json() -> JSONResponse:
    if not _JSON_PATH.exists():
        raise HTTPException(503, "snapshot not yet generated")
    return JSONResponse(content=json.loads(_JSON_PATH.read_text()))


def get_home_html(token: str) -> HTMLResponse:
    ticker_pages = sorted(p.stem for p in _TICKER_DIR.glob("*.html")) if _TICKER_DIR.exists() else []
    ticker_links = "".join(
        f'<a class="ticker" href="/d/{escape(token)}/t/{escape(ticker)}">{escape(ticker)}</a>'
        for ticker in ticker_pages
    )
    if not ticker_links:
        ticker_links = '<span class="muted">Run ticker page generation to populate ticker links.</span>'

    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>alphatecx · home</title>
<style>
html,body {{ margin:0; padding:0; background:#fff; color:#0f172a;
  font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;
  font-size:14px; line-height:1.5; }}
.wrap {{ max-width:1120px; margin:0 auto; padding:18px 20px 34px; }}
header {{ display:flex; align-items:flex-end; justify-content:space-between;
  gap:14px; flex-wrap:wrap; border-bottom:1px solid #e2e8f0; padding-bottom:12px; }}
h1 {{ font-size:22px; line-height:1.2; margin:0; font-weight:650; }}
.meta,.muted {{ color:#64748b; font-size:12px; }}
.grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:16px; }}
.link {{ display:block; border:1px solid #dbe3ee; border-radius:8px; padding:14px 16px;
  text-decoration:none; color:#0f172a; background:#fff; min-height:86px; }}
.link:hover {{ border-color:#2563eb; background:#f8fbff; }}
.link strong {{ display:block; font-size:15px; margin-bottom:5px; }}
.link span {{ display:block; color:#64748b; font-size:12px; }}
.section {{ margin-top:22px; }}
.section h2 {{ font-size:14px; margin:0 0 8px; font-weight:650; }}
.ticker-list {{ display:flex; flex-wrap:wrap; gap:6px; }}
.ticker {{ display:inline-block; padding:4px 8px; border:1px solid #dbe3ee; border-radius:6px;
  color:#2563eb; text-decoration:none; font-size:12px; background:#fff; }}
.ticker:hover {{ border-color:#2563eb; background:#f8fbff; }}
@media (max-width: 820px) {{
  .wrap {{ padding:14px 12px 28px; }}
  .grid {{ grid-template-columns:1fr; }}
  h1 {{ font-size:19px; }}
}}
</style></head><body>
<div class="wrap">
  <header>
    <div>
      <h1>alphatecx</h1>
      <div class="meta">Taiwan AI supply-chain intelligence</div>
    </div>
    <div class="meta">{len(ticker_pages)} ticker pages available</div>
  </header>

  <div class="grid">
    <a class="link" href="/d/{escape(token)}/">
      <strong>Data Dashboard</strong>
      <span>Watchlist, theses, discovery candidates, and lead-lag tables.</span>
    </a>
    <a class="link" href="/g/{escape(token)}/">
      <strong>Correlation Graph</strong>
      <span>Live-rendered supply-chain correlation map with classification controls.</span>
    </a>
    <a class="link" href="/g/{escape(token)}/graph.png">
      <strong>Graph PNG</strong>
      <span>Static image snapshot used by reports and Telegram summaries.</span>
    </a>
    <a class="link" href="/g/{escape(token)}/data.json">
      <strong>Graph Data</strong>
      <span>Raw graph snapshot JSON for debugging or external analysis.</span>
    </a>
    <a class="link" href="/health">
      <strong>Health Check</strong>
      <span>Public FastAPI health endpoint.</span>
    </a>
    <a class="link" href="/mcp/{escape(token)}/">
      <strong>MCP Endpoint</strong>
      <span>Streamable HTTP MCP mount for client configuration.</span>
    </a>
  </div>

  <div class="section">
    <h2>Ticker Pages</h2>
    <div class="ticker-list">{ticker_links}</div>
  </div>
</div>
</body></html>"""
    return HTMLResponse(content=html)


def get_dashboard_html() -> HTMLResponse:
    if not _DASHBOARD_PATH.exists():
        raise HTTPException(503, "dashboard.html not yet generated; "
                                 "run `python -m src.dashboard.build`")
    return HTMLResponse(content=_DASHBOARD_PATH.read_text())


def get_dashboard_css() -> Response:
    if not _DASHBOARD_CSS.exists():
        raise HTTPException(404, "dashboard.css missing")
    return Response(content=_DASHBOARD_CSS.read_text(), media_type="text/css")


def get_dashboard_js() -> Response:
    if not _DASHBOARD_JS.exists():
        raise HTTPException(404, "dashboard.js missing")
    return Response(content=_DASHBOARD_JS.read_text(),
                    media_type="application/javascript")


def get_ticker_page(ticker: str) -> HTMLResponse:
    if not _TICKER_ID_RE.match(ticker):
        raise HTTPException(404, "invalid ticker")
    path = _TICKER_DIR / f"{ticker}.html"
    if not path.exists():
        raise HTTPException(404, f"no page for {ticker}")
    return HTMLResponse(content=path.read_text())


def classify_ticker(payload: dict) -> JSONResponse:
    """Persist (pillar, node) for a ticker. Insert if missing, else update.

    Visible in the rendered graph only after correlation_snapshot is re-run —
    the Plotly HTML bakes data in at build time.
    """
    ticker_id = (payload.get("ticker_id") or "").strip()
    pillar    = payload.get("pillar")
    node      = payload.get("node")
    if not _TICKER_ID_RE.match(ticker_id):
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid ticker_id"})
    if pillar not in _VALID_PILLARS:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid pillar"})
    if node is not None:
        node = node.strip() or None
    if node is not None and not _NODE_RE.match(node):
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid node"})

    sql = """
        INSERT INTO dim_ticker (ticker_id, ai_pillar, node, updated_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (ticker_id) DO UPDATE
          SET ai_pillar  = EXCLUDED.ai_pillar,
              node       = EXCLUDED.node,
              updated_at = now()
    """
    try:
        with db_v2.pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (ticker_id, pillar, node))
            conn.commit()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"{type(e).__name__}: {e}",
                     "trace": traceback.format_exc().splitlines()[-3:]},
        )
    _invalidate_cache()
    return JSONResponse(content={"ok": True, "ticker_id": ticker_id,
                                 "pillar": pillar, "node": node})
