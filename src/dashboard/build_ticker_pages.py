#!/usr/bin/env python3
"""Per-ticker analytical detail pages.

For each ticker in (classified ∪ watchlist ∪ active-thesis), pre-render
a single HTML page combining:

  1. Candlestick + volume + Bollinger Bands + SMA-50/200 (last 12 months)
  2. Foreign-net flow bars (last 90 days, T86)
  3. Relative strength vs the ticker's sector index (normalised to 100)
  4. Thesis levels (catalyst / invalidation horizontal lines, if open thesis)
  5. Latest valuation pill (P/E, P/B, yield)
  6. News mentions (last 30 days)

Output: mcp_server/api/static/ticker/{ticker}.html  (one file per ticker)

Run:
    python -m src.dashboard.build_ticker_pages
"""
from __future__ import annotations

import argparse
import logging
import os
import re
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]
THESES_DIR = Path(__file__).resolve().parents[2] / "docs" / "theses"
OUT_DIR    = (Path(__file__).resolve().parents[2]
              / "mcp_server" / "api" / "static" / "ticker")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("ticker_pages")

PILLAR_COLOR = {
    "semiconductor":  "#2563eb",
    "infrastructure": "#ea580c",
    "equipment":      "#7c3aed",
    "energy":         "#16a34a",
}

# Pillar → preferred TWSE sector index for relative-strength benchmarking
PILLAR_INDEX = {
    "semiconductor":  "半導體類指數",
    "infrastructure": "數位雲端類指數",
    "equipment":      "機電類指數",
    "energy":         "油電燃氣類指數",
}

# Frontmatter parser (same shape as thesis_status / dashboard build)
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
def parse_frontmatter(text: str) -> dict:
    m = _FM_RE.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def get_target_tickers(conn) -> list[dict]:
    """Tickers we want pages for: classified ∪ watchlist (active) ∪ theses (active)."""
    out: dict[str, dict] = {}
    with conn.cursor() as c:
        c.execute("""
            SELECT ticker_id, company_name, ai_pillar, node
              FROM dim_supply_chain
             ORDER BY ai_pillar, node, ticker_id
        """)
        for tid, name, pillar, node in c.fetchall():
            out[tid] = {"ticker_id": tid, "company_name": name,
                        "ai_pillar": pillar, "node": node, "source": "classified"}
        c.execute("""
            SELECT w.ticker_id, w.company_name, w.ai_pillar, w.node
              FROM watchlist w WHERE w.status = 'active'
        """)
        for tid, name, pillar, node in c.fetchall():
            if tid not in out:
                out[tid] = {"ticker_id": tid, "company_name": name,
                            "ai_pillar": pillar, "node": node, "source": "watchlist"}
    if THESES_DIR.exists():
        for p in THESES_DIR.glob("*.md"):
            if p.name == "README.md":
                continue
            fm = parse_frontmatter(p.read_text())
            if fm.get("status", "").lower() != "active":
                continue
            tid = fm.get("ticker", "")
            if tid and tid not in out:
                out[tid] = {"ticker_id": tid, "company_name": fm.get("company", ""),
                            "ai_pillar": None, "node": None, "source": "thesis"}
    return list(out.values())


def load_ohlcv_by_ticker(conn, tickers: list[str], days: int = 252) -> dict[str, list]:
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    with conn.cursor() as c:
        c.execute("""
            SELECT ticker_id, date, open, high, low, close, volume_shares
              FROM raw_twse_ohlcv
             WHERE ticker_id = ANY(%s) AND date >= %s
               AND close IS NOT NULL
             ORDER BY ticker_id, date
        """, (tickers, cutoff))
        rows = c.fetchall()
    out: dict[str, list] = {}
    for ticker_id, *row in rows:
        out.setdefault(ticker_id, []).append(tuple(row))
    return out


def load_t86_flow_by_ticker(conn, tickers: list[str], days: int = 90) -> dict[str, list]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with conn.cursor() as c:
        c.execute("""
            SELECT ticker_id, date, foreign_net, trust_net, total_net
              FROM raw_twse_t86
             WHERE ticker_id = ANY(%s) AND date >= %s
             ORDER BY ticker_id, date
        """, (tickers, cutoff))
        rows = c.fetchall()
    out: dict[str, list] = {}
    for ticker_id, *row in rows:
        out.setdefault(ticker_id, []).append(tuple(row))
    return out


def load_valuation_by_ticker(conn, tickers: list[str]) -> dict[str, list]:
    with conn.cursor() as c:
        c.execute("""
            SELECT ticker_id, date, close, pe_ratio, pb_ratio, dividend_yield
              FROM raw_twse_valuation
             WHERE ticker_id = ANY(%s)
             ORDER BY ticker_id, date
        """, (tickers,))
        rows = c.fetchall()
    out: dict[str, list] = {}
    for ticker_id, *row in rows:
        out.setdefault(ticker_id, []).append(tuple(row))
    return out


def load_sector_index(conn, index_name: str, days: int = 252):
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    with conn.cursor() as c:
        c.execute("""
            SELECT date, close FROM raw_twse_index
             WHERE index_name = %s AND date >= %s AND close IS NOT NULL
             ORDER BY date
        """, (index_name, cutoff))
        return c.fetchall()


def load_signals_by_ticker(conn, tickers: list[str]) -> dict[str, dict]:
    keys = ["as_of", "rsi_14", "macd_line", "macd_signal_line", "macd_histogram",
            "bb_pct_b", "atr_14", "sma_50", "sma_200", "rs_vs_market_60",
            "pct_below_52w_high", "foreign_net_z20", "foreign_net_5d_sum"]
    with conn.cursor() as c:
        c.execute("""
            SELECT ticker_id, as_of, rsi_14, macd_line, macd_signal_line,
                   macd_histogram, bb_pct_b, atr_14, sma_50, sma_200,
                   rs_vs_market_60, pct_below_52w_high, foreign_net_z20,
                   foreign_net_5d_sum
              FROM view_latest_signals WHERE ticker_id = ANY(%s)
        """, (tickers,))
        rows = c.fetchall()
    return {ticker_id: dict(zip(keys, row, strict=True)) for ticker_id, *row in rows}


def load_news_by_ticker(conn, metas: list[dict], days: int = 30) -> dict[str, list]:
    """Load recent news once and apply the existing title substring match per ticker."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with conn.cursor() as c:
        c.execute("""
            SELECT title, url, source, published_at
              FROM raw_news
             WHERE published_at >= %s
             ORDER BY published_at DESC
        """, (cutoff,))
        articles = c.fetchall()

    out: dict[str, list] = {}
    matchers = []
    for meta in metas:
        ticker = meta["ticker_id"]
        company_name = meta["company_name"]
        if company_name:
            matchers.append((ticker, ticker.lower(), company_name.lower()))

    for title, url, source, published_at in articles:
        title_l = (title or "").lower()
        for ticker, ticker_l, company_l in matchers:
            if ticker_l in title_l or company_l in title_l:
                ticker_news = out.setdefault(ticker, [])
                if len(ticker_news) < 15:
                    ticker_news.append((title, url, source, published_at))
    return out


def load_active_theses_by_ticker() -> dict[str, dict]:
    """Load active thesis frontmatter once per build."""
    out: dict[str, dict] = {}
    if not THESES_DIR.exists():
        return out
    for p in THESES_DIR.glob("*.md"):
        if p.name == "README.md":
            continue
        fm = parse_frontmatter(p.read_text())
        if fm.get("status", "").lower() != "active":
            continue
        ticker = fm.get("ticker", "")
        if ticker:
            out[ticker] = fm
    return out


def render_page(meta, ohlcv, flow, valuation, sector_idx, signals, news, thesis):
    """Compose the plotly figure + HTML wrapper."""
    import numpy as np
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    ticker = meta["ticker_id"]
    name = meta["company_name"] or ticker
    pillar = meta.get("ai_pillar")

    # ── Build subplots: 3 rows (price/volume merged, flow, RS) ────────────
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.04,
        subplot_titles=("Price + Bollinger + SMA-50/200",
                        "Foreign net flow (T86)",
                        f"Relative strength vs {PILLAR_INDEX.get(pillar, '—')}"
                          if pillar else "Relative strength (no sector index)"),
    )

    if ohlcv:
        dates  = [r[0] for r in ohlcv]
        opens  = [r[1] for r in ohlcv]
        highs  = [r[2] for r in ohlcv]
        lows   = [r[3] for r in ohlcv]
        closes = [r[4] for r in ohlcv]

        fig.add_trace(go.Candlestick(
            x=dates, open=opens, high=highs, low=lows, close=closes,
            name=ticker, increasing_line_color="#16a34a",
            decreasing_line_color="#dc2626",
        ), row=1, col=1)

        # Rolling SMA-20 / SMA-50 / SMA-200 + Bollinger Bands
        c = np.array(closes, dtype=float)
        def sma(arr, w):
            out = np.full_like(arr, np.nan, dtype=float)
            if len(arr) >= w:
                cs = np.cumsum(np.insert(arr, 0, 0))
                out[w-1:] = (cs[w:] - cs[:-w]) / w
            return out

        sma20  = sma(c, 20)
        sma50  = sma(c, 50)
        sma200 = sma(c, 200)
        std20  = np.array([np.std(c[max(0,i-19):i+1]) if i >= 19 else np.nan
                           for i in range(len(c))])
        bb_up  = sma20 + 2 * std20
        bb_dn  = sma20 - 2 * std20

        fig.add_trace(go.Scatter(x=dates, y=sma50, name="SMA-50",
                                 line=dict(color="#2563eb", width=1.4)),
                      row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=sma200, name="SMA-200",
                                 line=dict(color="#7c3aed", width=1.4)),
                      row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=bb_up, name="BB upper",
                                 line=dict(color="#94a3b8", width=0.8, dash="dot")),
                      row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=bb_dn, name="BB lower",
                                 line=dict(color="#94a3b8", width=0.8, dash="dot"),
                                 fill="tonexty", fillcolor="rgba(148,163,184,0.06)"),
                      row=1, col=1)

        # Thesis levels (horizontal lines on price panel)
        if thesis:
            opened = thesis.get("opened", "")
            try:
                d_open = datetime.strptime(opened, "%Y-%m-%d").date()
                # Find close on/before opened date
                for r in reversed(ohlcv):
                    if r[0] <= d_open:
                        opened_close = r[4]
                        fig.add_hline(y=opened_close, line=dict(color="#94a3b8",
                                      width=1, dash="dash"),
                                      annotation_text=f"opened {opened} @ {opened_close:.0f}",
                                      annotation_position="top left",
                                      row=1, col=1)
                        break
            except Exception:
                pass
            # Try to parse a simple "close < <number>" invalidation
            inv = thesis.get("invalidation", "")
            m = re.search(r"close\s*<\s*(?:SMA-?50\s*\(\s*)?(\d{2,5})", inv)
            if m:
                level = float(m.group(1))
                fig.add_hline(y=level, line=dict(color="#dc2626", width=1, dash="dot"),
                              annotation_text=f"invalidation @ {int(level)}",
                              annotation_position="bottom left",
                              row=1, col=1)

    # ── Foreign-net flow bars ────────────────────────────────────────────
    if flow:
        f_dates = [r[0] for r in flow]
        f_vals  = [r[1] for r in flow]
        colors  = ["#16a34a" if v > 0 else "#dc2626" for v in f_vals]
        fig.add_trace(go.Bar(x=f_dates, y=f_vals, name="foreign_net",
                             marker_color=colors, showlegend=False),
                      row=2, col=1)
        fig.add_hline(y=0, line=dict(color="#cbd5e0", width=0.8), row=2, col=1)

    # ── Relative strength vs sector ──────────────────────────────────────
    if pillar and sector_idx and ohlcv:
        ix_dates = [r[0] for r in sector_idx]
        ix_close = np.array([r[1] for r in sector_idx], dtype=float)
        oh_dates = [r[0] for r in ohlcv]
        oh_close = np.array([r[4] for r in ohlcv], dtype=float)

        # Align by intersect of dates
        ix_map = {d: c for d, c in zip(ix_dates, ix_close, strict=True)}
        oh_map = {d: c for d, c in zip(oh_dates, oh_close, strict=True)}
        common = sorted(set(ix_dates) & set(oh_dates))
        if len(common) > 5:
            ic = np.array([ix_map[d] for d in common])
            oc = np.array([oh_map[d] for d in common])
            # Normalise so first day = 100 for both, then take ratio
            rs = (oc / oc[0]) / (ic / ic[0]) * 100
            fig.add_trace(go.Scatter(x=common, y=rs, name="RS (norm 100)",
                                     line=dict(color="#0f172a", width=1.4),
                                     showlegend=False),
                          row=3, col=1)
            fig.add_hline(y=100, line=dict(color="#cbd5e0", width=0.8, dash="dash"),
                          row=3, col=1)

    fig.update_layout(
        height=820, margin=dict(l=50, r=30, t=50, b=40),
        paper_bgcolor="white", plot_bgcolor="#fafbfc",
        font=dict(family="-apple-system,system-ui,sans-serif", size=11, color="#334155"),
        hovermode="x unified",
        xaxis=dict(rangeslider=dict(visible=False)),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=1.06,
                    bgcolor="rgba(248,250,252,0.85)", bordercolor="#e2e8f0",
                    borderwidth=1, font=dict(size=10)),
        # Hide weekend gaps:
        xaxis_rangebreaks=[dict(bounds=["sat", "mon"])],
        xaxis2_rangebreaks=[dict(bounds=["sat", "mon"])],
        xaxis3_rangebreaks=[dict(bounds=["sat", "mon"])],
    )

    plot_html = fig.to_html(full_html=False, include_plotlyjs="cdn",
                            config={"displayModeBar": True, "displaylogo": False,
                                    "responsive": True,
                                    "modeBarButtonsToRemove": ["lasso2d", "select2d"]})

    # ── Valuation pill ───────────────────────────────────────────────────
    val_pill = ""
    if valuation:
        latest = valuation[-1]
        d_, c_, pe, pb, dy = latest
        parts = []
        if pe is not None:
            parts.append(f"P/E <b>{pe:.1f}</b>")
        if pb is not None:
            parts.append(f"P/B <b>{pb:.2f}</b>")
        if dy is not None:
            parts.append(f"yield <b>{dy:.2f}%</b>")
        if parts:
            val_pill = f'<span class="valpill">{" · ".join(parts)}</span>'

    # ── Signal pill ──────────────────────────────────────────────────────
    sig_pill = ""
    if signals:
        s = signals
        rsi = s.get("rsi_14")
        fz  = s.get("foreign_net_z20")
        below52 = s.get("pct_below_52w_high")
        parts = []
        if rsi is not None:
            parts.append(f"RSI <b>{rsi:.0f}</b>")
        if fz is not None:
            parts.append(f"foreign-z <b>{fz:+.2f}</b>")
        if below52 is not None:
            parts.append(f"{below52 * 100:+.1f}% vs 52wH")
        if parts:
            sig_pill = f'<span class="sigpill">{" · ".join(parts)}</span>'

    # ── Thesis box ───────────────────────────────────────────────────────
    thesis_html = ""
    if thesis:
        thesis_html = f"""
        <div class="thesis-box">
          <div class="thesis-head">📝 Active thesis</div>
          <div>opened {escape(thesis.get('opened',''))} · horizon {escape(thesis.get('horizon',''))} · conviction {escape(thesis.get('naive_conviction','?'))}/{escape(thesis.get('aware_conviction','?'))}</div>
          <div class="thesis-line">📈 catalyst: {escape(thesis.get('catalyst','')[:200])}</div>
          <div class="thesis-line">🚫 invalidation: {escape(thesis.get('invalidation','')[:200])}</div>
        </div>"""

    # ── News list ────────────────────────────────────────────────────────
    news_html = ""
    if news:
        items = "".join(
            f'<li><a href="{escape(url)}" target="_blank">{escape(title[:140])}</a> '
            f'<span class="meta">{escape(source or "")} · {pub.strftime("%Y-%m-%d") if pub else ""}</span></li>'
            for title, url, source, pub in news
        )
        news_html = f"""
        <div class="news">
          <h3>News mentions (last 30d)</h3>
          <ul>{items}</ul>
        </div>"""

    pillar_pill = ""
    if pillar:
        c = PILLAR_COLOR.get(pillar, "#94a3b8")
        node = meta.get("node") or ""
        pillar_pill = (f'<span class="pillpill" style="background:{c}">'
                       f'{escape(pillar)}{(" / " + escape(node)) if node else ""}</span>')

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(ticker)} {escape(name)} · alphatecx</title>
<link rel="stylesheet" href="../dashboard.css">
<style>
  .ticker-header {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px;
    margin-bottom:10px; }}
  .ticker-header h1 {{ font-size:20px; margin:0; }}
  .pillpill {{ display:inline-block; padding:2px 9px; border-radius:12px;
    background:#94a3b8; color:white; font-size:11px; font-weight:600; }}
  .valpill, .sigpill {{ display:inline-block; padding:2px 9px; border-radius:12px;
    background:#f1f5f9; color:#334155; font-size:12px; font-weight:500; }}
  .valpill b, .sigpill b {{ color:#0f172a; }}
  .thesis-box {{ margin:10px 0; padding:12px 16px; background:#fffbeb;
    border:1px solid #fcd34d; border-radius:8px; font-size:13px; line-height:1.6; }}
  .thesis-head {{ font-weight:600; margin-bottom:4px; }}
  .thesis-line {{ font-size:12px; color:#475569; margin-top:3px; }}
  .news {{ margin-top:14px; padding:10px 16px; background:#f8fafc;
    border:1px solid #e2e8f0; border-radius:8px; font-size:12px; }}
  .news h3 {{ font-size:13px; margin:0 0 6px; }}
  .news ul {{ margin:0; padding-left:20px; line-height:1.7; }}
  .news a {{ color:#2563eb; text-decoration:none; }}
  .news a:hover {{ text-decoration:underline; }}
  .news .meta {{ color:#94a3b8; font-size:11px; }}
  .nav-back {{ font-size:12px; color:#64748b; }}
  .nav-back a {{ color:#2563eb; text-decoration:none; }}
</style></head><body>
<div class="wrap">
  <div class="nav-back"><a href="../home">Home</a> · <a href="../">Dashboard</a></div>
  <div class="ticker-header">
    <h1>{escape(ticker)} <span style="color:#64748b; font-weight:500">{escape(name)}</span></h1>
    {pillar_pill} {val_pill} {sig_pill}
  </div>
  {thesis_html}
  {plot_html}
  {news_html}
</div>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=str, default=str(OUT_DIR))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_written = 0
    n_empty = 0

    with psycopg.connect(DATABASE_URL) as conn:
        targets = get_target_tickers(conn)
        target_ids = [meta["ticker_id"] for meta in targets]
        ohlcv_by_ticker = load_ohlcv_by_ticker(conn, target_ids)
        flow_by_ticker = load_t86_flow_by_ticker(conn, target_ids)
        valuation_by_ticker = load_valuation_by_ticker(conn, target_ids)
        signals_by_ticker = load_signals_by_ticker(conn, target_ids)
        news_by_ticker = load_news_by_ticker(conn, targets)
        theses_by_ticker = load_active_theses_by_ticker()
        sector_index_cache: dict[str, list] = {}
        log.info("targets: %d tickers", len(targets))

        for meta in targets:
            ticker = meta["ticker_id"]
            ohlcv = ohlcv_by_ticker.get(ticker, [])
            if len(ohlcv) < 20:
                log.warning("skip %s — only %d ohlcv rows", ticker, len(ohlcv))
                n_empty += 1
                continue
            flow      = flow_by_ticker.get(ticker, [])
            valuation = valuation_by_ticker.get(ticker, [])
            signals   = signals_by_ticker.get(ticker)
            news      = news_by_ticker.get(ticker, [])
            thesis    = theses_by_ticker.get(ticker)
            pillar    = meta.get("ai_pillar")
            if pillar in PILLAR_INDEX:
                index_name = PILLAR_INDEX[pillar]
                if index_name not in sector_index_cache:
                    sector_index_cache[index_name] = load_sector_index(conn, index_name)
                sector = sector_index_cache[index_name]
            else:
                sector = []
            html = render_page(meta, ohlcv, flow, valuation, sector,
                               signals, news, thesis)
            (out_dir / f"{ticker}.html").write_text(html)
            n_written += 1

    log.info("wrote %d ticker pages, skipped %d", n_written, n_empty)


if __name__ == "__main__":
    main()
