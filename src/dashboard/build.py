#!/usr/bin/env python3
"""Build the static data dashboard at mcp_server/api/static/dashboard.html.

Four tabs:
  - Watchlist     active rows + current signals
  - Theses        active theses + current vs as-of metrics
  - Discovery     unclassified tickers tracking a pillar
  - Lead-lag      top forward-leading pairs

Output is plain HTML <table>s with vanilla-JS sort + filter — no plotly,
no JS frameworks, ~50 LOC of inline JS. Regenerated nightly by the cron.

Run:
    python -m src.dashboard.build
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Optional

import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]
THESES_DIR = Path(__file__).resolve().parents[2] / "docs" / "theses"
SNAPSHOT = (Path(__file__).resolve().parents[2]
            / "mcp_server" / "api" / "static" / "graph_snapshot.json")
OUT_PATH = (Path(__file__).resolve().parents[2]
            / "mcp_server" / "api" / "static" / "dashboard.html")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard")


PILLAR_COLOR = {
    "semiconductor":  "#2563eb",
    "infrastructure": "#ea580c",
    "equipment":      "#7c3aed",
    "energy":         "#16a34a",
}


# ── helpers ────────────────────────────────────────────────────────────────
def _pct(x, prec=1):
    if x is None:
        return ""
    return f"{x*100:+.{prec}f}%"


def _num(x, prec=2):
    if x is None:
        return ""
    return f"{x:.{prec}f}"


def _int_thousands(x):
    if x is None:
        return ""
    try:
        return f"{int(x):,}"
    except Exception:
        return str(x)


def _pill(text, color):
    """Coloured inline pill for pillar/status."""
    return (f'<span style="display:inline-block;padding:1px 7px;border-radius:10px;'
            f'background:{color};color:white;font-size:11px;font-weight:600">'
            f'{escape(str(text))}</span>')


def _ticker_link(ticker: str, label: str | None = None) -> str:
    """Anchor to the per-ticker detail page (relative to /d/{TOKEN}/)."""
    if not ticker:
        return ""
    return (f'<a href="t/{escape(ticker)}" '
            f'style="color:#2563eb;text-decoration:none;font-weight:600">'
            f'{escape(label or ticker)}</a>')


def _row_html(cells, classes=""):
    cls = f' class="{classes}"' if classes else ""
    tds = "".join(f"<td>{c}</td>" for c in cells)
    return f"<tr{cls}>{tds}</tr>"


def _table_html(table_id: str, headers: list[str], rows: list[list[str]],
                empty_msg: str = "Nothing here yet.") -> str:
    """Plain <table> with sortable headers (the JS at the bottom of the page
    wires this up). Each header cell is `data-sort-type="num"|"text"`."""
    if not rows:
        return f'<div class="empty">{empty_msg}</div>'
    th = "".join(
        f'<th data-sort-type="{t}" data-col="{i}">{escape(h)}</th>'
        for i, (h, t) in enumerate(headers)
    )
    body = "\n".join(_row_html(r) for r in rows)
    return (f'<div class="scroll-x"><table id="{table_id}" class="dt">'
            f'<thead><tr>{th}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


# ── frontmatter parsing (duplicate from thesis_status to keep self-contained) ──
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
def parse_frontmatter(text: str) -> dict:
    m = _FM_RE.match(text)
    if not m: return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" not in line: continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


# ── data loaders ───────────────────────────────────────────────────────────
def load_watchlist(conn) -> list[dict]:
    sql = """
        SELECT w.ticker_id, w.company_name, w.ai_pillar, w.node, w.reason,
               w.escalation_trigger, w.added_at,
               ls.rsi_14, ls.foreign_net_z20, ls.foreign_net_5d_sum,
               ohlcv_close.close
          FROM watchlist w
          LEFT JOIN view_latest_signals ls ON ls.ticker_id = w.ticker_id
          LEFT JOIN LATERAL (
              SELECT close FROM raw_twse_ohlcv
               WHERE ticker_id = w.ticker_id AND close IS NOT NULL
               ORDER BY date DESC LIMIT 1
          ) ohlcv_close ON TRUE
         WHERE w.status = 'active'
         ORDER BY w.added_at DESC
    """
    with conn.cursor() as c:
        c.execute(sql)
        return [
            {"ticker_id": r[0], "company_name": r[1], "ai_pillar": r[2], "node": r[3],
             "reason": r[4], "escalation_trigger": r[5], "added_at": r[6],
             "rsi_14": r[7], "foreign_z": r[8], "foreign_5d": r[9],
             "close": float(r[10]) if r[10] is not None else None}
            for r in c.fetchall()
        ]


def load_active_theses(conn) -> list[dict]:
    out = []
    if not THESES_DIR.exists():
        return out
    for p in sorted(THESES_DIR.glob("*.md")):
        if p.name == "README.md": continue
        text = p.read_text()
        fm = parse_frontmatter(text)
        if fm.get("status", "").lower() != "active": continue
        ticker = fm.get("ticker", "")
        if not ticker: continue
        # Current signals + latest close
        with conn.cursor() as c:
            c.execute("""
                SELECT ls.rsi_14, ls.foreign_net_z20, ls.foreign_net_5d_sum,
                       ls.sma_50
                  FROM view_latest_signals ls WHERE ls.ticker_id = %s
            """, (ticker,))
            row = c.fetchone() or (None, None, None, None)
            rsi, fz, f5d, sma50 = row
            c.execute("""
                SELECT close FROM raw_twse_ohlcv
                 WHERE ticker_id = %s AND close IS NOT NULL
                 ORDER BY date DESC LIMIT 1
            """, (ticker,))
            crow = c.fetchone()
            cur_close = float(crow[0]) if crow else None
            # Open-date close (or nearest)
            opened = fm.get("opened", "")
            opened_close = None
            try:
                d_open = datetime.strptime(opened, "%Y-%m-%d").date()
                c.execute("""
                    SELECT close FROM raw_twse_ohlcv
                     WHERE ticker_id = %s AND date <= %s AND close IS NOT NULL
                     ORDER BY date DESC LIMIT 1
                """, (ticker, d_open))
                row = c.fetchone()
                opened_close = float(row[0]) if row else None
            except Exception:
                pass
        days_open = None
        try:
            days_open = (date.today() - datetime.strptime(opened, "%Y-%m-%d").date()).days
        except Exception:
            pass
        out.append({
            "ticker": ticker,
            "company": fm.get("company", ""),
            "opened": opened,
            "days_open": days_open,
            "horizon": fm.get("horizon", ""),
            "naive": fm.get("naive_conviction", ""),
            "aware": fm.get("aware_conviction", ""),
            "catalyst": fm.get("catalyst", ""),
            "invalidation": fm.get("invalidation", ""),
            "current_close": cur_close,
            "opened_close": opened_close,
            "ret_since_open": (cur_close / opened_close - 1.0) if (cur_close and opened_close) else None,
            "rsi_14": rsi, "foreign_z": fz, "foreign_5d": f5d, "sma_50": sma50,
            "filename": p.name,
        })
    return out


def load_discovery() -> list[dict]:
    if not SNAPSHOT.exists():
        return []
    try:
        snap = json.loads(SNAPSHOT.read_text())
    except Exception as e:
        log.warning("snapshot read failed: %s", e)
        return []
    return list(snap.get("discovery", []))


def load_leadlag(conn) -> list[dict]:
    sql = """
        WITH coincident AS (
            SELECT upstream_id, downstream_id, correlation AS rho_0
              FROM lead_lag
             WHERE lag_days = 0
               AND asof = (SELECT MAX(asof) FROM lead_lag)
        )
        SELECT f.upstream_id, up.company_name, up.ai_pillar,
               f.downstream_id, dn.company_name, dn.ai_pillar,
               f.lag_days,
               ROUND(f.correlation::numeric, 3),
               ROUND(coincident.rho_0::numeric, 3),
               ROUND((f.correlation - coincident.rho_0)::numeric, 3),
               f.n_obs, f.window_days, f.asof
          FROM lead_lag f
          JOIN coincident USING (upstream_id, downstream_id)
          LEFT JOIN dim_ticker up ON up.ticker_id = f.upstream_id
          LEFT JOIN dim_ticker dn ON dn.ticker_id = f.downstream_id
         WHERE f.lag_days BETWEEN 1 AND 7
           AND f.asof = (SELECT MAX(asof) FROM lead_lag)
           AND f.correlation >= 0.3
         ORDER BY (f.correlation - coincident.rho_0) DESC
         LIMIT 50
    """
    with conn.cursor() as c:
        c.execute(sql)
        return [
            {"up": r[0], "up_name": r[1], "up_pillar": r[2],
             "down": r[3], "down_name": r[4], "down_pillar": r[5],
             "lag": r[6], "rho_lag": float(r[7]), "rho_0": float(r[8]),
             "gain": float(r[9]), "n_obs": r[10], "window_days": r[11],
             "asof": r[12]}
            for r in c.fetchall()
        ]


# ── tab renderers ──────────────────────────────────────────────────────────
def render_watchlist(rows: list[dict]) -> str:
    headers = [
        ("Ticker", "text"), ("Name", "text"), ("Pillar", "text"), ("Node", "text"),
        ("Close", "num"), ("RSI", "num"), ("Foreign-z", "num"), ("Foreign-5d", "num"),
        ("Reason", "text"), ("Trigger", "text"),
    ]
    body = []
    for r in rows:
        pillar = r["ai_pillar"] or ""
        pill = _pill(pillar, PILLAR_COLOR.get(pillar, "#94a3b8")) if pillar else ""
        body.append([
            _ticker_link(r["ticker_id"]),
            escape(r["company_name"] or ""),
            pill,
            escape(r["node"] or ""),
            _num(r["close"], 2),
            _num(r["rsi_14"], 1),
            _num(r["foreign_z"], 2),
            _int_thousands(r["foreign_5d"]),
            escape((r["reason"] or "")[:80]),
            escape((r["escalation_trigger"] or "")[:60]),
        ])
    return _table_html("watchlist", headers, body,
                       "Watchlist is empty.")


def render_theses(rows: list[dict]) -> str:
    headers = [
        ("Ticker", "text"), ("Company", "text"), ("Days", "num"),
        ("Close", "num"), ("Δ since open", "num"), ("RSI", "num"),
        ("Foreign-z", "num"), ("Conviction", "text"), ("Catalyst", "text"),
    ]
    body = []
    for r in rows:
        ret = r["ret_since_open"]
        ret_html = _pct(ret) if ret is not None else ""
        cls = ""
        if ret is not None:
            cls = "pos" if ret >= 0 else "neg"
        body.append([
            _ticker_link(r["ticker"]),
            escape(r["company"]),
            r["days_open"] if r["days_open"] is not None else "",
            _num(r["current_close"], 2),
            f'<span class="{cls}">{ret_html}</span>',
            _num(r["rsi_14"], 1),
            _num(r["foreign_z"], 2),
            f'{escape(r["naive"])}/{escape(r["aware"])}',
            escape((r["catalyst"] or "")[:120]),
        ])
    return _table_html("theses", headers, body,
                       "No active theses. Open one with the decide-on-ticker Skill.")


def render_discovery(rows: list[dict]) -> str:
    headers = [
        ("Ticker", "text"), ("Name", "text"),
        ("Suggested pillar", "text"), ("Suggested node", "text"),
        ("Conviction ρ", "num"), ("Top neighbours", "text"),
    ]
    body = []
    for r in rows:
        pillar = r.get("suggested_pillar") or ""
        pill = _pill(pillar, PILLAR_COLOR.get(pillar, "#94a3b8")) if pillar else ""
        neighbours = ", ".join(
            f'{n["id"]} ({n["rho"]})' for n in (r.get("neighbours") or [])[:5]
        )
        body.append([
            _ticker_link(r["ticker"]),
            escape(r["name"]),
            pill,
            escape(r.get("suggested_node") or ""),
            r.get("conviction"),
            escape(neighbours),
        ])
    return _table_html("discovery", headers, body,
                       "No discovery candidates above threshold.")


def render_leadlag(rows: list[dict]) -> str:
    headers = [
        ("Upstream", "text"), ("→", "text"), ("Downstream", "text"),
        ("Lag (d)", "num"), ("ρ at lag", "num"), ("ρ at 0", "num"),
        ("Gain", "num"), ("N obs", "num"),
    ]
    body = []
    for r in rows:
        up_pill = _pill(r["up_pillar"], PILLAR_COLOR.get(r["up_pillar"], "#94a3b8")) if r["up_pillar"] else ""
        dn_pill = _pill(r["down_pillar"], PILLAR_COLOR.get(r["down_pillar"], "#94a3b8")) if r["down_pillar"] else ""
        gain_cls = "pos" if r["gain"] > 0 else ("neg" if r["gain"] < 0 else "")
        body.append([
            f'{_ticker_link(r["up"])} {escape(r["up_name"] or "")} {up_pill}',
            "→",
            f'{_ticker_link(r["down"])} {escape(r["down_name"] or "")} {dn_pill}',
            r["lag"],
            r["rho_lag"],
            r["rho_0"],
            f'<span class="{gain_cls}">{r["gain"]:+.3f}</span>',
            r["n_obs"],
        ])
    return _table_html("leadlag", headers, body,
                       "Lead-lag table is empty. Run src.quant.leadlag.")


# ── full page ──────────────────────────────────────────────────────────────
def build_html(watchlist, theses, discovery, leadlag) -> str:
    today = date.today().isoformat()
    counts = (f"{len(watchlist)} watchlist · {len(theses)} active "
              f"thes{'es' if len(theses)!=1 else 'is'} · "
              f"{len(discovery)} discovery · {len(leadlag)} lead-lag")

    # CSS + JS live in mcp_server/api/static/dashboard.{css,js}, served by
    # FastAPI at /d/{TOKEN}/dashboard.{css,js}. Keeping them out of this
    # template means UI tweaks no longer require regenerating the data HTML.
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>alphatecx · data dashboard</title>
<link rel="stylesheet" href="dashboard.css">
</head><body>
<div class="wrap">
  <div class="header">
    <div>
      <div class="meta"><a href="home">Home</a></div>
      <h1>Taiwan AI universe — data dashboard</h1>
    </div>
    <div class="header-actions">
      <button id="theme-toggle" class="terminal-btn" type="button">Dark</button>
      <div class="meta">{counts} · as of {today}</div>
    </div>
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="watchlist">Watchlist · {len(watchlist)}</button>
    <button class="tab" data-tab="theses">Theses · {len(theses)}</button>
    <button class="tab" data-tab="discovery">Discovery · {len(discovery)}</button>
    <button class="tab" data-tab="leadlag">Lead-lag · {len(leadlag)}</button>
  </div>
  <div class="toolbar">
    <input id="q" type="search" placeholder="Filter rows in current tab — try a ticker, name, or keyword">
    <span class="meta">tip: click any column header to sort</span>
  </div>
  <div class="panel active" data-panel="watchlist">{render_watchlist(watchlist)}</div>
  <div class="panel" data-panel="theses">{render_theses(theses)}</div>
  <div class="panel" data-panel="discovery">{render_discovery(discovery)}</div>
  <div class="panel" data-panel="leadlag">{render_leadlag(leadlag)}</div>
</div>
<script src="dashboard.js"></script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, default=str(OUT_PATH))
    args = ap.parse_args()

    with psycopg.connect(DATABASE_URL) as conn:
        watchlist = load_watchlist(conn)
        theses    = load_active_theses(conn)
        discovery = load_discovery()
        leadlag   = load_leadlag(conn)

    log.info("watchlist=%d theses=%d discovery=%d leadlag=%d",
             len(watchlist), len(theses), len(discovery), len(leadlag))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(watchlist, theses, discovery, leadlag))
    log.info("wrote %s (%d bytes)", out, out.stat().st_size)


if __name__ == "__main__":
    main()
