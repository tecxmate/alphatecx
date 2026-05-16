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
_FOLDER_RE     = re.compile(r"^[0-9A-Za-z][0-9A-Za-z\- _/]{0,47}$")

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
<link rel="stylesheet" href="/d/{escape(token)}/dashboard.css">
<style>
.grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:10px; }}
.link {{ display:block; border:1px solid var(--line); padding:12px 13px;
  text-decoration:none; color:var(--text); background:var(--surface); min-height:76px;
  box-shadow:var(--shadow); }}
.link:hover {{ border-color:var(--link); background:var(--surface-2); text-decoration:none; }}
.link strong {{ display:block; font-size:13px; margin-bottom:5px; }}
.link span {{ display:block; color:var(--muted); font-size:11px; }}
.section {{ margin-top:18px; }}
.section h2 {{ font-size:12px; margin:0 0 7px; font-weight:650; text-transform:uppercase; color:var(--muted); }}
.ticker-list {{ display:flex; flex-wrap:wrap; gap:5px; }}
.ticker {{ display:inline-block; padding:3px 7px; border:1px solid var(--line);
  color:var(--link); text-decoration:none; font-size:11px; background:var(--surface); }}
.ticker:hover {{ border-color:var(--link); background:var(--surface-2); }}
@media (max-width: 820px) {{
  .grid {{ grid-template-columns:1fr; }}
}}
</style></head><body>
<div class="wrap">
  <header class="header">
    <div>
      <h1>alphatecx</h1>
      <div class="meta">Taiwan AI supply-chain intelligence</div>
    </div>
    <div class="header-actions">
      <button id="theme-toggle" class="terminal-btn" type="button">Dark</button>
      <div class="meta">{len(ticker_pages)} ticker pages available</div>
    </div>
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
    <a class="link" href="/t/{escape(token)}/">
      <strong>Tickers</strong>
      <span>Search the full ticker directory, edit pillar/node, and organize folders.</span>
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
<script src="/d/{escape(token)}/dashboard.js"></script>
</body></html>"""
    return HTMLResponse(content=html)


def _ticker_directory() -> list[dict]:
    sql = """
        SELECT ticker_id, company_name, ai_pillar, node, COALESCE(tags, ARRAY[]::text[]) AS tags
        FROM dim_ticker
        ORDER BY
          CASE WHEN ai_pillar IS NULL THEN 1 ELSE 0 END,
          ticker_id
    """
    with db_v2.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [
                {
                    "id": r[0],
                    "name": r[1] or "",
                    "pillar": r[2] or "",
                    "node": r[3] or "",
                    "folders": list(r[4] or []),
                }
                for r in cur.fetchall()
            ]


def get_tickers_html(token: str) -> HTMLResponse:
    try:
        directory = _ticker_directory()
    except Exception as e:
        raise HTTPException(503, f"ticker directory failed: {type(e).__name__}: {e}") from e
    directory_json = json.dumps(directory, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    folder_count = len({f for row in directory for f in row.get("folders", [])})
    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>alphatecx · tickers</title>
<link rel="stylesheet" href="/d/{escape(token)}/dashboard.css">
</head><body>
<div class="wrap">
  <header class="header">
    <div>
      <div class="nav-back"><a href="/h/{escape(token)}/">Home</a><span>/</span><span>Tickers</span></div>
      <h1>Ticker Directory</h1>
      <div class="meta">{len(directory)} tickers · {folder_count} folders · 20 per page</div>
    </div>
    <div class="header-actions">
      <button id="theme-toggle" class="terminal-btn" type="button">Dark</button>
    </div>
  </header>

  <div class="ticker-tools">
    <input id="ticker-search" class="table-filter" type="search" placeholder="Search ticker, company, pillar, node, or folder" autocomplete="off">
    <select id="folder-filter" class="table-filter" aria-label="Folder filter"></select>
    <span id="ticker-state" class="meta"></span>
  </div>
  <div id="folder-bar" class="folder-bar"></div>
  <div class="table-scroll">
    <table id="ticker-table" class="terminal-table">
      <thead><tr>
        <th>Ticker</th><th>Name</th><th>Pillar</th><th>Node</th><th>Folders / lists</th><th>Detail</th><th>Action</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
  <div id="ticker-pager" class="pager"></div>
</div>
<script src="/d/{escape(token)}/dashboard.js"></script>
<script>
(function() {{
  const DIRECTORY = {directory_json};
  const TOKEN = location.pathname.split('/')[2] || '';
  const PAGE_SIZE = 20;
  const PILLARS = ['', 'semiconductor', 'equipment', 'infrastructure', 'energy'];
  let matches = DIRECTORY.slice();
  let page = 0;

  const search = document.getElementById('ticker-search');
  const folderFilter = document.getElementById('folder-filter');
  const folderBar = document.getElementById('folder-bar');
  const state = document.getElementById('ticker-state');
  const body = document.querySelector('#ticker-table tbody');
  const pager = document.getElementById('ticker-pager');

  function esc(s) {{
    return String(s || '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
  }}
  function foldersText(t) {{
    return (t.folders || []).join(', ');
  }}
  function queryText(t) {{
    return `${{t.id}} ${{t.name}} ${{t.pillar || ''}} ${{t.node || ''}} ${{foldersText(t)}}`.toLowerCase();
  }}
  function pillarOptions(current) {{
    return PILLARS.map(p => `<option value="${{p}}" ${{p === (current || '') ? 'selected' : ''}}>${{p || 'unclassified'}}</option>`).join('');
  }}
  function allFolders() {{
    return Array.from(new Set(DIRECTORY.flatMap(t => t.folders || []))).sort((a, b) => a.localeCompare(b));
  }}
  function syncFolders() {{
    const folders = allFolders();
    const current = folderFilter.value || '';
    folderFilter.innerHTML = '<option value="">All folders</option>' + folders.map(f => `<option value="${{esc(f)}}">${{esc(f)}}</option>`).join('');
    folderFilter.value = folders.includes(current) ? current : '';
    folderBar.innerHTML = folders.length
      ? folders.map(f => `<button type="button" data-folder="${{esc(f)}}">${{esc(f)}}</button>`).join('')
      : '<span class="meta">Add comma-separated folders in a row, for example Watch, Cooling, Earnings.</span>';
    folderBar.querySelectorAll('button').forEach(btn => {{
      btn.addEventListener('click', () => {{
        folderFilter.value = btn.dataset.folder;
        applyFilters();
      }});
    }});
  }}
  function applyFilters() {{
    const q = search.value.trim().toLowerCase();
    const folder = folderFilter.value;
    page = 0;
    matches = DIRECTORY.filter(t => {{
      const folderOk = !folder || (t.folders || []).includes(folder);
      const queryOk = !q || queryText(t).includes(q);
      return folderOk && queryOk;
    }});
    render();
  }}
  function render() {{
    const start = page * PAGE_SIZE;
    const rows = matches.slice(start, start + PAGE_SIZE);
    body.innerHTML = rows.map(t => `
      <tr data-ticker="${{esc(t.id)}}">
        <td><b>${{esc(t.id)}}</b></td>
        <td>${{esc(t.name)}}</td>
        <td><select class="row-pillar">${{pillarOptions(t.pillar)}}</select></td>
        <td><input class="row-node" type="text" value="${{esc(t.node || '')}}" placeholder="node"></td>
        <td><input class="row-folders" type="text" value="${{esc(foldersText(t))}}" placeholder="folder, list"></td>
        <td><a href="/d/${{TOKEN}}/t/${{encodeURIComponent(t.id)}}">Open</a></td>
        <td><button class="row-save">Save</button><span class="row-msg"></span></td>
      </tr>
    `).join('');
    body.querySelectorAll('.row-save').forEach(bindSave);
    state.textContent = matches.length
      ? `${{start + 1}}-${{Math.min(start + PAGE_SIZE, matches.length)}} of ${{matches.length}}`
      : 'No tickers matched.';
    const totalPages = Math.max(1, Math.ceil(matches.length / PAGE_SIZE));
    pager.innerHTML = `
      <button id="ticker-prev" ${{page <= 0 ? 'disabled' : ''}}>Prev</button>
      <span>Page ${{page + 1}} of ${{totalPages}}</span>
      <button id="ticker-next" ${{page >= totalPages - 1 ? 'disabled' : ''}}>Next</button>
    `;
    document.getElementById('ticker-prev')?.addEventListener('click', () => {{
      page = Math.max(0, page - 1);
      render();
    }});
    document.getElementById('ticker-next')?.addEventListener('click', () => {{
      page = Math.min(totalPages - 1, page + 1);
      render();
    }});
  }}
  function parseFolders(raw) {{
    return Array.from(new Set(String(raw || '').split(',').map(s => s.trim()).filter(Boolean))).slice(0, 12);
  }}
  async function saveJson(url, payload) {{
    const r = await fetch(url, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload),
    }});
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || 'save failed');
    return j;
  }}
  function bindSave(btn) {{
    btn.addEventListener('click', async () => {{
      const row = btn.closest('tr');
      const ticker_id = row.dataset.ticker;
      const pillar = row.querySelector('.row-pillar').value || null;
      const node = row.querySelector('.row-node').value.trim() || null;
      const folders = parseFolders(row.querySelector('.row-folders').value);
      const msg = row.querySelector('.row-msg');
      btn.disabled = true;
      msg.textContent = 'saving...';
      msg.className = 'row-msg';
      try {{
        if (pillar) await saveJson(`/g/${{TOKEN}}/classify`, {{ ticker_id, pillar, node }});
        await saveJson(`/t/${{TOKEN}}/folders`, {{ ticker_id, folders }});
        const idx = DIRECTORY.findIndex(t => t.id === ticker_id);
        if (idx >= 0) {{
          if (pillar) {{
            DIRECTORY[idx].pillar = pillar;
            DIRECTORY[idx].node = node || '';
          }}
          DIRECTORY[idx].folders = folders;
        }}
        msg.textContent = 'saved';
        msg.className = 'row-msg ok';
        syncFolders();
        applyFilters();
      }} catch (err) {{
        msg.textContent = err.message;
        msg.className = 'row-msg err';
      }} finally {{
        btn.disabled = false;
      }}
    }});
  }}
  search.addEventListener('input', applyFilters);
  folderFilter.addEventListener('change', applyFilters);
  syncFolders();
  render();
}})();
</script>
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


def update_ticker_folders(payload: dict) -> JSONResponse:
    """Persist user-defined ticker folders/lists in dim_ticker.tags."""
    ticker_id = (payload.get("ticker_id") or "").strip()
    raw_folders = payload.get("folders") or []
    if not _TICKER_ID_RE.match(ticker_id):
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid ticker_id"})
    if not isinstance(raw_folders, list):
        return JSONResponse(status_code=400, content={"ok": False, "error": "folders must be a list"})

    folders: list[str] = []
    for item in raw_folders:
        folder = str(item).strip()
        if not folder:
            continue
        if not _FOLDER_RE.match(folder):
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": f"invalid folder: {folder[:48]}"},
            )
        if folder not in folders:
            folders.append(folder)
        if len(folders) >= 12:
            break

    sql = """
        UPDATE dim_ticker
           SET tags = %s,
               updated_at = now()
         WHERE ticker_id = %s
    """
    try:
        with db_v2.pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (folders, ticker_id))
                if cur.rowcount == 0:
                    return JSONResponse(status_code=404, content={"ok": False, "error": "ticker not found"})
            conn.commit()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"{type(e).__name__}: {e}",
                     "trace": traceback.format_exc().splitlines()[-3:]},
        )
    return JSONResponse(content={"ok": True, "ticker_id": ticker_id, "folders": folders})
