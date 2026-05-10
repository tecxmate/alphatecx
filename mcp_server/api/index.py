"""alphatecx v2 MCP server — supply chain intelligence.

Tool naming convention:
  sc_*     supply chain views — pre-computed sector & ticker momentum
  raw_*    raw data queries   — drill-down into historical flow/holdings

Every response includes:
  _source     — e.g. "view_sector_momentum", "raw_twse_t86"
  _as_of      — ISO date of the data
  _freshness  — "T+1" (data from previous trading day)

Auth: URL-as-secret. Mount path is /mcp/<MCP_BEARER_TOKEN>/.
"""
from __future__ import annotations

import contextlib
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

# TWSE publishes data in Asia/Taipei. Using UTC mislabels _as_of for ~8 hours
# every day; provenance has to match the source's wall clock.
_TPE = ZoneInfo("Asia/Taipei")

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE.parent / ".env")
sys.path.insert(0, str(_HERE))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import db_v2
import graph_view

MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "")


def _stamp(payload: dict, source: str, as_of: Optional[str], freshness: str) -> dict:
    """Annotate a response with provenance + freshness."""
    return {
        "_source": source,
        "_as_of": as_of,
        "_freshness": freshness,
        **payload,
    }


def _today_iso() -> str:
    return datetime.now(_TPE).date().isoformat()


# ── MCP server ──────────────────────────────────────────────────────────────

mcp = FastMCP(
    "alphatecx-v2",
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


# ── Tool: Sector Momentum ──────────────────────────────────────────────────

@mcp.tool()
def sc_sector_momentum(
    pillar: Optional[str] = None,
    window: str = "5d",
    top_n: int = 10,
) -> dict:
    """Get sector-level institutional flow momentum across AI supply chain pillars.

    Shows aggregated foreign investor (FINI), investment trust, and dealer
    net flows by AI pillar and supply chain node. Useful for detecting which
    parts of the Taiwan AI supply chain are being accumulated or distributed.

    Args:
        pillar: Filter to a specific AI pillar: 'semiconductor', 'equipment',
                'infrastructure', 'energy', or None for all.
        window: Flow aggregation window: '1d', '3d', '5d', '10d', '20d'.
        top_n: Number of results (default 10).
    """
    col = f"foreign_{window}"
    valid_cols = ["foreign_1d", "foreign_3d", "foreign_5d", "foreign_10d", "foreign_20d"]
    if col not in valid_cols:
        return {"error": f"Invalid window '{window}'. Use: 1d, 3d, 5d, 10d, 20d"}

    rows = db_v2.query_sector_momentum(pillar=pillar, order_col=col, limit=top_n)
    return _stamp(
        {"sectors": rows, "window": window, "count": len(rows)},
        source="view_sector_momentum",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Ticker Momentum ──────────────────────────────────────────────────

@mcp.tool()
def sc_ticker_momentum(
    pillar: Optional[str] = None,
    node: Optional[str] = None,
    ticker_id: Optional[str] = None,
    window: str = "5d",
    top_n: int = 15,
    min_streak: int = 0,
) -> dict:
    """Get per-ticker institutional flow momentum with consecutive buy streak tracking.

    Drill down to individual stocks within a supply chain pillar or node.
    Shows multi-day net flows and how many consecutive days foreign investors
    have been net buying.

    Args:
        pillar: Filter by AI pillar: 'semiconductor', 'equipment',
                'infrastructure', 'energy'.
        node: Filter by supply chain node: e.g. 'server-odm', 'thermal-cooling',
              'advanced-foundry', 'asic-custom-ip', etc.
        ticker_id: Look up a specific ticker (e.g. '2330' for TSMC).
        window: Sort by flow window: '1d', '3d', '5d', '10d', '20d'.
        top_n: Number of results (default 15).
        min_streak: Minimum consecutive foreign buy days to filter (default 0).
    """
    col = f"foreign_{window}"
    valid_cols = ["foreign_1d", "foreign_3d", "foreign_5d", "foreign_10d", "foreign_20d"]
    if col not in valid_cols:
        return {"error": f"Invalid window '{window}'. Use: 1d, 3d, 5d, 10d, 20d"}

    rows = db_v2.query_ticker_momentum(
        pillar=pillar, node=node, ticker_id=ticker_id,
        order_col=col, limit=top_n, min_streak=min_streak,
    )
    return _stamp(
        {"tickers": rows, "window": window, "count": len(rows)},
        source="view_ticker_momentum",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Supply Chain Map ─────────────────────────────────────────────────

@mcp.tool()
def sc_supply_chain_map(
    pillar: Optional[str] = None,
    node: Optional[str] = None,
    search: Optional[str] = None,
) -> dict:
    """Look up the Taiwan AI supply chain classification for tickers.

    Returns which AI pillar, node, and US partners each company maps to.
    Use this to understand the strategic position of a ticker before
    analyzing its flow data.

    Args:
        pillar: Filter by pillar: 'semiconductor', 'equipment',
                'infrastructure', 'energy'.
        node: Filter by node: 'server-odm', 'thermal-cooling', etc.
        search: Search by ticker_id or company name (partial match).
    """
    rows = db_v2.query_supply_chain(pillar=pillar, node=node, search=search)
    return _stamp(
        {"companies": rows, "count": len(rows)},
        source="dim_supply_chain",
        as_of=_today_iso(),
        freshness="static",
    )


# ── Tool: Flow History (time series) ───────────────────────────────────────

@mcp.tool()
def raw_flow_history(
    ticker_id: str,
    days: int = 20,
) -> dict:
    """Get daily institutional flow history for a specific ticker.

    Returns a time series of daily foreign/trust/dealer net flows.
    Useful for charting accumulation patterns and identifying entry points.

    Args:
        ticker_id: TWSE/TPEX ticker code (e.g. '2330', '3324').
        days: Number of trading days to return (default 20, max 90).
    """
    days = min(days, 90)
    rows = db_v2.query_flow_history(ticker_id=ticker_id, days=days)
    return _stamp(
        {"ticker_id": ticker_id, "history": rows, "count": len(rows)},
        source="raw_twse_t86",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Compare Nodes ───────────────────────────────────────────────────

@mcp.tool()
def sc_compare_nodes(
    nodes: list[str],
    window: str = "5d",
) -> dict:
    """Compare institutional flow between supply chain nodes.

    Side-by-side comparison of foreign capital flow across different parts
    of the AI supply chain. Useful for detecting "trickle down" rotation
    patterns (e.g., money flowing from foundry → server ODM → cooling).

    Args:
        nodes: List of node names to compare (e.g. ['server-odm',
               'thermal-cooling', 'advanced-foundry']).
        window: Flow window: '1d', '3d', '5d', '10d', '20d'.
    """
    col = f"foreign_{window}"
    total_col = f"total_{window}"
    valid_cols = ["foreign_1d", "foreign_3d", "foreign_5d", "foreign_10d", "foreign_20d"]
    if col not in valid_cols:
        return {"error": f"Invalid window '{window}'. Use: 1d, 3d, 5d, 10d, 20d"}

    results = db_v2.query_compare_nodes(nodes=nodes, foreign_col=col, total_col=total_col)
    return _stamp(
        {"comparison": results, "window": window, "nodes_requested": nodes},
        source="view_sector_momentum",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Accumulation Screener ────────────────────────────────────────────

@mcp.tool()
def sc_accumulation_screen(
    min_streak: int = 3,
    min_foreign_5d: int = 0,
    pillar: Optional[str] = None,
    top_n: int = 20,
) -> dict:
    """Screen for tickers with sustained foreign accumulation.

    Finds stocks where foreign investors have been consistently net buying.
    Combines consecutive buy days with absolute flow volume.

    Args:
        min_streak: Minimum consecutive days of foreign net buying (default 3).
        min_foreign_5d: Minimum 5-day foreign net flow (shares, default 0).
        pillar: Optional pillar filter.
        top_n: Max results (default 20).
    """
    rows = db_v2.query_ticker_momentum(
        pillar=pillar, order_col="consecutive_foreign_buy_days",
        limit=top_n, min_streak=min_streak,
    )
    # Filter by min_foreign_5d
    if min_foreign_5d > 0:
        rows = [r for r in rows if (r.get("foreign_5d") or 0) >= min_foreign_5d]

    return _stamp(
        {"accumulated_tickers": rows, "min_streak": min_streak, "count": len(rows)},
        source="view_ticker_momentum",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Quant Indicators (per ticker) ────────────────────────────────────

@mcp.tool()
def q_indicators(ticker_id: str) -> dict:
    """Latest technical indicator stack for one ticker.

    Returns RSI-14, MACD (line/signal/histogram), Bollinger %B, ATR-14,
    SMA-50, SMA-200, and 60-day relative strength vs the broad market
    (Yuanta Taiwan 50 / 0050).

    Indicators are recomputed daily from OHLCV data after market close.
    Read this before forming an opinion on a ticker — it tells you where
    momentum, volatility, and trend stand right now.

    Args:
        ticker_id: TWSE/TPEX code, e.g. '2330' for TSMC.
    """
    payload = db_v2.query_indicators(ticker_id)
    return _stamp(
        payload,
        source="view_latest_signals",
        as_of=str(payload.get("as_of") or _today_iso()),
        freshness="T+1",
    )


# ── Tool: Quant Screener ───────────────────────────────────────────────────

@mcp.tool()
def q_screener(
    rsi_below: Optional[float] = None,
    rsi_above: Optional[float] = None,
    macd_hist_above: Optional[float] = None,
    above_sma_200: Optional[bool] = None,
    rs_above: Optional[float] = None,
    foreign_z_above: Optional[float] = None,
    pct_below_52w_high_above: Optional[float] = None,
) -> dict:
    """Filter the classified universe by indicator conditions (AND-combined).

    Combines technical + flow signals. Examples:
      - oversold-in-uptrend: rsi_below=40, above_sma_200=true, macd_hist_above=0
      - foreign-buying surge: foreign_z_above=1.5
      - near-highs momentum: pct_below_52w_high_above=-3, rs_above=1.0

    Args:
        rsi_below: RSI-14 below this value.
        rsi_above: RSI-14 above this value.
        macd_hist_above: MACD histogram above this value.
        above_sma_200: True = price above 200-day MA; False = below.
        rs_above: 60d relative strength vs market threshold (1.0 = neutral).
        foreign_z_above: 20-day z-score of daily foreign net flow.
        pct_below_52w_high_above: Filter to tickers within X% of 52w high
            (pass -3 to mean "within 3% of the high"; pass -10 for "within 10%").
    """
    rows = db_v2.query_screener(
        rsi_below=rsi_below, rsi_above=rsi_above,
        macd_hist_above=macd_hist_above,
        above_sma_200=above_sma_200, rs_above=rs_above,
        foreign_z_above=foreign_z_above,
        pct_below_52w_high_above=pct_below_52w_high_above,
    )
    return _stamp(
        {"matches": rows, "count": len(rows)},
        source="view_latest_signals",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Quant Backtest ──────────────────────────────────────────────────

@mcp.tool()
def q_backtest(
    signal_name: str,
    threshold: float,
    direction: str = "below",
    forward_days: int = 5,
    lookback_days: int = 365,
) -> dict:
    """Backtest a single-threshold signal rule on the classified universe.

    Returns hit-rate (% of triggers that produced positive returns N days
    later), average / median / best / worst return, and per-ticker sample
    counts. If n_observations < 30, a sample_warning is included — treat
    such results as illustrative, not predictive.

    Use this BEFORE acting on any signal idea to know whether the rule
    has historically had positive expectancy on this universe.

    Args:
        signal_name: One of rsi_14, macd_line, macd_signal_line,
                     macd_histogram, bb_pct_b, atr_14, sma_50, sma_200,
                     rs_vs_market_60.
        threshold: The numeric threshold to compare against.
        direction: 'below' (signal < threshold) or 'above' (signal > threshold).
        forward_days: Trading days to measure forward return (default 5).
        lookback_days: Calendar days of history to scan (default 365).

    Examples:
        q_backtest('rsi_14', 30, 'below', 5)   — oversold mean reversion
        q_backtest('rsi_14', 70, 'above', 5)   — overbought continuation
        q_backtest('macd_histogram', 0, 'above', 5)  — bullish momentum
    """
    payload = db_v2.query_backtest(
        signal_name, threshold, direction, forward_days, lookback_days,
    )
    if "error" in payload:
        return payload
    return _stamp(
        payload,
        source="signal_value + raw_twse_ohlcv",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Compound Backtest ───────────────────────────────────────────────

@mcp.tool()
def q_backtest_compound(
    conditions: list[dict],
    forward_days: int = 5,
    lookback_days: int = 365,
) -> dict:
    """Backtest a multi-condition AND rule. Up to 4 conditions.

    Each condition is {'signal': str, 'op': '<' | '>', 'threshold': float}.
    All must hold on the same (ticker, date) to count as a trigger.

    Use this to test combined hypotheses that single signals miss. For
    example: naive RSI < 30 has weak edge in a strong uptrend, but
    "RSI < 40 AND MACD histogram > 0" (oversold dip within an uptrend)
    historically has stronger expectancy.

    Args:
        conditions: list of {'signal','op','threshold'} dicts.
        forward_days: trading days to measure forward return (default 5).
        lookback_days: history to scan (default 365).

    Example:
        q_backtest_compound(
          [{"signal":"rsi_14","op":"<","threshold":40},
           {"signal":"macd_histogram","op":">","threshold":0}],
          forward_days=5)
    """
    payload = db_v2.query_backtest_compound(conditions, forward_days, lookback_days)
    if "error" in payload:
        return payload
    return _stamp(
        payload,
        source="signal_value + raw_twse_ohlcv",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: News Recent ─────────────────────────────────────────────────────

@mcp.tool()
def n_recent(
    days: int = 1,
    source: Optional[str] = None,
    lang: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Recent news articles harvested into raw_news.

    Articles come from RSS feeds (DigiTimes Asia, Nikkei Asia, Bloomberg
    Tech/Markets, Federal Reserve, ECB) and Google News query feeds
    (per-pillar, per-theme, both English and Traditional Chinese for
    Taiwan-domestic coverage).

    Phase 2a: titles + summaries only, no sentiment scores yet.

    Args:
        days: Lookback window in days (default 1 = last 24h).
        source: Filter to one feed key, e.g. 'digitimes', 'gnews-tw-ai-zh'.
                Use n_source_status() to list available source keys.
        lang: Filter to 'en' or 'zh-Hant'.
        limit: Max articles to return (default 50, capped at 200).
    """
    rows = db_v2.query_news_recent(days=days, source=source, lang=lang, limit=limit)
    return _stamp(
        {"articles": rows, "count": len(rows), "days_window": days},
        source="raw_news",
        as_of=_today_iso(),
        freshness="hourly",
    )


# ── Tool: News for Ticker ─────────────────────────────────────────────────

@mcp.tool()
def n_for_ticker(
    ticker_id: str,
    days: int = 14,
    limit: int = 30,
) -> dict:
    """Articles mentioning a specific ticker.

    Until the entity-extraction layer (Phase 2b) populates a structured
    ticker-mentions array, this falls back to text matching: ticker code
    appearing as a standalone token in the title, OR the company name
    appearing in title or summary. Company name comes from dim_ticker.

    Args:
        ticker_id: TWSE/TPEX code, e.g. '2330' for TSMC.
        days: Lookback window (default 14).
        limit: Max articles (default 30, capped at 100).
    """
    rows = db_v2.query_news_for_ticker(ticker_id, days=days, limit=limit)
    return _stamp(
        {"ticker_id": ticker_id, "articles": rows, "count": len(rows),
         "days_window": days},
        source="raw_news",
        as_of=_today_iso(),
        freshness="hourly",
    )


# ── Tool: News Source Status ──────────────────────────────────────────────

@mcp.tool()
def n_source_status() -> dict:
    """Per-source freshness report. Use to verify feeds are still updating."""
    rows = db_v2.query_news_source_status()
    return _stamp(
        {"sources": rows, "count": len(rows)},
        source="raw_news",
        as_of=_today_iso(),
        freshness="real_time",
    )


# ── Tool: Watchlist (Phase 3.5) ──────────────────────────────────────────

@mcp.tool()
def w_watchlist(status: str = "active") -> dict:
    """Active watchlist — names being monitored but not yet at thesis stage.

    Sourced from the `watchlist` table in Neon. Same source the Telegram
    bot reads/writes; the `w_add` / `w_remove` tools below mutate it
    from the Claude app.

    Args:
        status: 'active' (default), 'archived', or 'all'.
    """
    rows = db_v2.query_watchlist(status=status)
    return _stamp(
        {"watchlist": rows, "count": len(rows), "status": status},
        source="watchlist",
        as_of=_today_iso(),
        freshness="real_time",
    )


# ── Tool: Universe (unified view) ────────────────────────────────────────

@mcp.tool()
def u_universe(filter: str = "all") -> dict:
    """One row per classified ticker — knowledge + watch-state + signals.

    Watched names sort first. Most queries can replace a chain of
    `sc_supply_chain_map` + `q_indicators` + `w_watchlist` with a single
    call to this tool.

    Args:
        filter:
            'all' — every classified ticker (default, ~26 rows)
            'watching' — only watch_status='active'
            'extreme' — RSI>80 / RSI<20 / BB outside [0,1] / |foreign_z|>2
    """
    rows = db_v2.query_universe(filter=filter)
    return _stamp(
        {"universe": rows, "count": len(rows), "filter": filter},
        source="view_universe",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Watchlist mutations (write-capable, narrowly scoped) ───────────

@mcp.tool()
def w_add(ticker_id: str,
          reason: Optional[str] = None,
          escalation_trigger: Optional[str] = None) -> dict:
    """Add a ticker to the watchlist (or reactivate an archived row).

    Validates that the ticker exists in `dim_supply_chain` — the
    classified 26-name universe. Outside that universe, the watchlist
    rejects the add (the system's edge is supply-chain-mapped flow,
    not arbitrary screening).

    Args:
        ticker_id: e.g. '2330'.
        reason: optional one-line free-form note (why is this on the
                list).
        escalation_trigger: optional specific data condition that would
                            promote this to a thesis (e.g. 'foreign_z
                            stays >1.5 for 2 more sessions').
    """
    return db_v2.mutate_watchlist_add(
        ticker_id=ticker_id, reason=reason, escalation_trigger=escalation_trigger,
    )


@mcp.tool()
def w_remove(ticker_id: str) -> dict:
    """Archive a watchlist entry. Idempotent — re-running on an already-
    archived ticker is a no-op."""
    return db_v2.mutate_watchlist_remove(ticker_id=ticker_id)


# ── Tool: Lead-lag analysis ─────────────────────────────────────────────

@mcp.tool()
def q_valuation(
    ticker_id: Optional[str] = None,
    pillar: Optional[str] = None,
    max_pe: Optional[float] = None,
    max_pb: Optional[float] = None,
    min_yield: Optional[float] = None,
    top_n: int = 30,
) -> dict:
    """Latest valuation metrics (P/E, P/B, dividend yield) per ticker.

    Sourced from TWSE BWIBBU_d, harvested daily. Filters compose AND-style:
    e.g. pillar='semiconductor' + max_pb=2 returns AI-semi names trading
    below 2× book. NULL pe_ratio means the company has no positive
    earnings — those rows are excluded if max_pe is set.

    Args:
        ticker_id: Optional single-ticker lookup.
        pillar: 'semiconductor' | 'infrastructure' | 'equipment' | 'energy'.
        max_pe: Cap on P/E ratio. NULL P/E excluded when set.
        max_pb: Cap on P/B ratio.
        min_yield: Minimum dividend yield in % (e.g. 3.0 for 3%+).
        top_n: Result limit (default 30).

    Returns rows sorted by P/B asc (cheapest first), each with company_name,
    pillar, node, close, dividend_yield, dividend_year, pe, pb, fiscal_period.
    """
    rows = db_v2.query_valuation(
        ticker_id=ticker_id, pillar=pillar,
        max_pe=max_pe, max_pb=max_pb, min_yield=min_yield, top_n=top_n,
    )
    asof = rows[0]["date"] if rows else None
    return _stamp(
        {"valuations": rows, "count": len(rows)},
        source="raw_twse_valuation",
        as_of=asof,
        freshness="daily",
    )


@mcp.tool()
def q_index_history(
    index_name: Optional[str] = None,
    days: int = 30,
) -> dict:
    """Sector / cross-market index closes & changes from TWSE MI_INDEX.

    With index_name: returns up to `days` recent observations for that one
    index (e.g. '半導體類指數'). Without: snapshot of every index for the
    most recent date.

    Args:
        index_name: Exact Chinese index name. Common ones include
                    '發行量加權股價指數' (TAIEX), '半導體類指數',
                    '電子工業類指數', '金融保險類指數'.
        days: Trailing trading days when index_name is given (default 30).
    """
    rows = db_v2.query_index_history(index_name=index_name, days=days)
    asof = rows[0]["date"] if rows else None
    return _stamp(
        {"indices": rows, "count": len(rows)},
        source="raw_twse_index",
        as_of=asof,
        freshness="daily",
    )


@mcp.tool()
def q_pca_decompose(
    tickers: list[str],
    days: int = 120,
    k: int = 3,
) -> dict:
    """PCA risk decomposition on a basket of tickers.

    Decomposes daily log-returns into top-k orthogonal principal components
    and returns each ticker's loading on each PC, plus the % of variance
    explained. PC₁ is almost always a common-factor (≈ market β) for any
    correlated set; PC₂ and PC₃ usually split the universe along
    interpretable axes (e.g. "semi vs ODM", "AI-pure vs diversified",
    "memory vs logic").

    Use case: "I have N positions — am I diversified, or am I betting on
    one factor N different ways?"
      - PC₁ > 70% → concentration warning, the basket is effectively one
        position
      - PC₁ ~50%, PC₂ ~25% → genuine 2-factor split, real diversification
      - All PCs <40% → very diversified (rare for a focused basket)

    Args:
        tickers: 2-30 ticker IDs.
        days: trailing trading days for the regression (default 120).
        k: number of principal components to return (default 3).

    Returns: tickers, n_obs, components[] (each with pc index,
    explained_variance, explained_variance_pct, loadings dict, and an
    interpretation_hint), cumulative_variance_pct, and a plain-English
    `interpretation` string.
    """
    from src.quant.pca_decompose import compute_pca
    result = compute_pca(tickers=tickers, days=days, k=k)
    return _stamp(result, source="pca_decompose",
                  as_of=_today_iso(), freshness="on-demand")


@mcp.tool()
def q_factor_screen(
    pillar: Optional[str] = None,
    node: Optional[str] = None,
    tickers: Optional[list[str]] = None,
    days: int = 90,
    sort_by: str = "alpha_tstat",
    top_n: int = 25,
) -> dict:
    """Cross-sectional alpha hunting across the classified universe.

    Runs the same factor regression as `q_factor_alpha` (market + sector +
    flow) on every ticker matching the filter, in one DB roundtrip, then
    returns them ranked. Use this to find names with statistically real
    idiosyncratic alpha — the t-stat (|t|>2 → significant) is the primary
    signal, not the raw alpha number (which is noisy at short windows).

    Args:
        pillar: filter by AI pillar — 'semiconductor' | 'infrastructure' |
                'equipment' | 'energy'. If None, screens the full classified
                universe.
        node: filter by node (e.g. 'server-odm', 'high-speed-pcb',
              'memory-dram'); composes with pillar.
        tickers: explicit ticker list; overrides pillar/node when given.
        days: regression window (default 90).
        sort_by: 'alpha_tstat' (default) | 'alpha_annualized' | 'r_squared'
                 | 'n_obs'. Default surfaces statistically real alpha.
        top_n: cap on rows returned (default 25).

    Returns rows with: ticker_id, company_name, ai_pillar, node,
    sector_index, alpha_daily, alpha_annualized, alpha_tstat,
    alpha_significant, betas{market,sector,flow}, beta_tstats{...},
    r_squared, factors_used, n_obs.

    Practical reading: ignore tickers with alpha_significant=false. Among
    those with |t|>2, large positive alpha = real idiosyncratic
    outperformance; large negative alpha = real underperformance even
    though the index is rising (often the most overlooked short signal).
    """
    from src.quant.factor_alpha import compute_factor_screen
    rows = compute_factor_screen(
        pillar=pillar, node=node, tickers=tickers,
        days=days, sort_by=sort_by,
    )
    rows = rows[: int(top_n)]
    return _stamp(
        {"rows": rows, "count": len(rows),
         "filter": {"pillar": pillar, "node": node,
                    "tickers": tickers, "days": days, "sort_by": sort_by}},
        source="factor_alpha",
        as_of=_today_iso(),
        freshness="on-demand",
    )


@mcp.tool()
def q_factor_alpha(ticker_id: str, days: int = 120) -> dict:
    """Decompose a ticker's recent returns into factor exposures + residual α.

    Fits an OLS regression of the ticker's daily log-returns over the last
    `days` trading days against three factors:

      market  — 0050 ETF return (broad TW market)
      sector  — pillar sector index return (e.g. 半導體類指數 for semis)
      flow    — long-short portfolio of classified tickers ranked daily
                by 20-day rolling z-score of T86 foreign_net (top quintile
                minus bottom quintile, equal-weight). This isolates whether
                the ticker is exposed to the "foreign-buying tide" or has
                idiosyncratic drift on top of it.

    Returns:
      alpha_daily        residual mean daily return after factor exposure
      alpha_annualized   alpha_daily × 252 (rough annualisation)
      alpha_tstat        t-statistic on alpha; |t|>2 is significant
      alpha_significant  bool: |t|>2
      betas              dict: factor name -> beta
      beta_tstats        dict: factor name -> beta t-stat
      r_squared          % of variance explained by factors
      interpretation     plain-English summary suitable for direct quoting

    Use case: "is this ticker's recent outperformance real (positive α with
    significant t-stat), or is it just exposure to the flow factor that any
    name with similar foreign-buying would have shown?" Read alpha_tstat
    and the interpretation field together to decide.

    Args:
        ticker_id: e.g. '3231', '2330'.
        days: Trailing trading days for the regression window (default 120).
              Minimum ~30 needed; more is more reliable.
    """
    from src.quant.factor_alpha import compute_factor_alpha
    result = compute_factor_alpha(ticker_id, days=days)
    return _stamp(result, source="factor_alpha",
                  as_of=_today_iso(), freshness="on-demand")


@mcp.tool()
def q_lead_lag(
    upstream: Optional[str] = None,
    downstream: Optional[str] = None,
    min_corr: float = 0.4,
    min_gain: float = 0.0,
    top_n: int = 20,
) -> dict:
    """Pairs where the upstream ticker's price moves predict the downstream's
    price moves N days later.

    Computed nightly from the last 60 trading days of returns. For each pair
    of classified tickers we compute correlation at lags 0..7 days and keep
    rows where lag>0 has meaningful forward predictive correlation.

    Use this to find supply-chain lead-lag effects: e.g. TSMC's foreign-flow
    moves often precede downstream ODMs by 1-3 days. A high `gain` (forward
    rho minus same-day rho) is the strongest signal — it means tomorrow's
    move in `downstream_id` is better predicted by today's move in
    `upstream_id` than by today's same-day correlation.

    Args:
        upstream: Optional ticker filter — only return rows where this is
                  the leading ticker.
        downstream: Optional ticker filter — only return rows where this is
                    the lagging ticker.
        min_corr: Minimum forward correlation (default 0.4).
        min_gain: Minimum forward-correlation gain over coincident (default 0.0).
        top_n: Limit (default 20).

    Returns rows with: upstream_id/name/pillar, downstream_id/name/pillar,
    lag_days, rho_lag, rho_0, gain, n_obs, window_days, asof.
    """
    rows = db_v2.query_lead_lag(
        upstream=upstream, downstream=downstream,
        min_corr=min_corr, min_gain=min_gain, top_n=top_n,
    )
    asof = rows[0]["asof"] if rows else None
    return _stamp(
        {"pairs": rows, "count": len(rows)},
        source="lead_lag",
        as_of=asof,
        freshness="nightly",
    )


# ── Tool: Digests (Phase 3) ──────────────────────────────────────────────

@mcp.tool()
def d_recent(days: int = 3, kind: Optional[str] = None) -> dict:
    """Recent cron-generated briefs (pre_market / intraday_alert / post_close).

    Briefs are written by the GitHub Actions cron at meaningful times in
    the Taiwan trading day. Each one summarises news + signals and
    explicitly flags candidates that warrant deeper analysis.

    Args:
        days: Lookback window in days (default 3).
        kind: Optional filter — 'pre_market', 'intraday_alert',
              'post_close', or 'thesis_status'.
    """
    rows = db_v2.query_digest_recent(days=days, kind=kind)
    return _stamp(
        {"digests": rows, "count": len(rows)},
        source="daily_digest",
        as_of=_today_iso(),
        freshness="cron-driven",
    )


@mcp.tool()
def d_for_date(digest_date: str, kind: Optional[str] = None) -> dict:
    """All digests for one specific date.

    Args:
        digest_date: ISO date (YYYY-MM-DD) in Taiwan time.
        kind: Optional filter as in d_recent.
    """
    rows = db_v2.query_digest_for_date(digest_date, kind=kind)
    return _stamp(
        {"digests": rows, "count": len(rows), "date": digest_date},
        source="daily_digest",
        as_of=digest_date,
        freshness="cron-driven",
    )


# ── Tool: Data Status ─────────────────────────────────────────────────────

@mcp.tool()
def sc_data_status() -> dict:
    """Check the status of the alphatecx v2 data pipeline.

    Returns row counts, latest ingestion date, and data freshness
    for all tables. Use this to verify data is up to date before analysis.
    """
    stats = db_v2.query_data_status()
    return _stamp(
        stats,
        source="ingestion_log",
        as_of=_today_iso(),
        freshness="real_time",
    )


# ── Tool: Capabilities ────────────────────────────────────────────────────

@mcp.tool()
def sc_capabilities() -> dict:
    """Describe all available tools and what this MCP server provides.

    alphatecx v2 is a Taiwan AI supply chain intelligence system.
    It tracks institutional capital flows (foreign investors, investment
    trusts, dealers) across ~7000 TWSE/TPEX stocks, classified into
    4 AI pillars: semiconductor, equipment, infrastructure, energy.

    The system detects "trickle down" accumulation patterns as foreign
    capital flows from foundry (TSMC) → server ODMs → cooling/PCB → power.
    """
    return {
        "server": "alphatecx-v2",
        "description": "Taiwan AI supply chain intelligence — institutional flow tracking",
        "data_coverage": {
            "tickers": "~7000 TWSE + TPEX stocks",
            "classified": "~27 stocks across 4 AI pillars",
            "history": "up to 90 trading days",
            "update_frequency": "daily after 16:00 CST",
        },
        "ai_pillars": {
            "semiconductor": "Foundry (TSMC), ASIC/Custom IP (Alchip, GUC), Advanced Packaging (ASE, SPIL)",
            "equipment": "Testing (KYEC), Facility/Cleanroom (Marketech), Materials (GlobalWafers)",
            "infrastructure": "Server ODMs (Quanta, Wistron, Foxconn), Cooling (AVC, Auras), PCB (Unimicron), BMC (Aspeed)",
            "energy": "Power Supply (Delta, Lite-On), Heavy Electrical (Fortune), Green Energy (HDRE)",
        },
        "tools": [
            {"name": "sc_sector_momentum", "purpose": "Sector-level flow aggregation by pillar/node"},
            {"name": "sc_ticker_momentum", "purpose": "Per-ticker flow with buy streak tracking"},
            {"name": "sc_supply_chain_map", "purpose": "Look up ticker → pillar/node/US partner"},
            {"name": "raw_flow_history", "purpose": "Daily flow time series for one ticker"},
            {"name": "sc_compare_nodes", "purpose": "Side-by-side node flow comparison"},
            {"name": "sc_accumulation_screen", "purpose": "Find tickers with sustained FINI buying"},
            {"name": "sc_data_status", "purpose": "Pipeline health and data freshness"},
            {"name": "q_indicators", "purpose": "Latest technical + flow indicators for one ticker"},
            {"name": "q_screener", "purpose": "Filter classified universe by AND-combined indicator conditions"},
            {"name": "q_backtest", "purpose": "Backtest a single-threshold signal rule"},
            {"name": "q_backtest_compound", "purpose": "Backtest multi-condition (AND) compound rules; up to 4 conditions"},
            {"name": "n_recent", "purpose": "Recent news articles (RSS + Google News); titles + summaries"},
            {"name": "n_for_ticker", "purpose": "Articles mentioning a ticker (text-match fallback until Phase 2b entity extraction)"},
            {"name": "n_source_status", "purpose": "Per-source freshness — verify feeds still updating"},
            {"name": "d_recent", "purpose": "Recent cron-generated briefs (pre-market / intraday / post-close)"},
            {"name": "d_for_date", "purpose": "All digests for one specific date"},
            {"name": "w_watchlist", "purpose": "Active watchlist — bot-managed names being monitored"},
            {"name": "u_universe", "purpose": "Unified read: classified-ticker × knowledge × watch-state × signals"},
            {"name": "w_add", "purpose": "Add a ticker to the watchlist (writes to DB; same as bot /watch)"},
            {"name": "w_remove", "purpose": "Archive a watchlist entry (writes to DB; same as bot /unwatch)"},
        ],
    }


# ── FastAPI mount ──────────────────────────────────────────────────────────

mcp_app = mcp.streamable_http_app()


@contextlib.asynccontextmanager
async def lifespan(app):
    async with mcp._session_manager.run():
        yield


app = FastAPI(title="alphatecx-v2", version="0.2", lifespan=lifespan)


@app.get("/")
def root():
    return {"name": "alphatecx-v2", "ok": True}


@app.get("/health")
def health():
    return {"ok": True, "server": "alphatecx-v2"}


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if path in ("/", "/health"):
        return await call_next(request)
    if MCP_BEARER_TOKEN and path.startswith(f"/mcp/{MCP_BEARER_TOKEN}"):
        return await call_next(request)
    if MCP_BEARER_TOKEN and path.startswith(f"/g/{MCP_BEARER_TOKEN}"):
        return await call_next(request)
    if MCP_BEARER_TOKEN and path.startswith(f"/d/{MCP_BEARER_TOKEN}"):
        return await call_next(request)
    return JSONResponse(status_code=404, content={"error": "not_found"})


@app.get(f"/g/{{token}}/")
def graph_index(token: str):
    if token != MCP_BEARER_TOKEN:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_viewer_html()


@app.get(f"/g/{{token}}/data.json")
def graph_data(token: str):
    if token != MCP_BEARER_TOKEN:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_snapshot_json()


@app.get(f"/g/{{token}}/graph.png")
def graph_png(token: str):
    if token != MCP_BEARER_TOKEN:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_graph_png()


@app.get(f"/d/{{token}}/")
def dashboard(token: str):
    if token != MCP_BEARER_TOKEN:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_dashboard_html()


@app.get(f"/d/{{token}}/dashboard.css")
def dashboard_css(token: str):
    if token != MCP_BEARER_TOKEN:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_dashboard_css()


@app.get(f"/d/{{token}}/dashboard.js")
def dashboard_js(token: str):
    if token != MCP_BEARER_TOKEN:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_dashboard_js()


@app.get(f"/d/{{token}}/t/{{ticker}}")
def ticker_page(token: str, ticker: str):
    """Per-ticker analytical detail page (candlestick + flow + RS + thesis + news).

    Pages are pre-rendered nightly by `python -m src.dashboard.build_ticker_pages`
    and read from mcp_server/api/static/ticker/{ticker}.html. Same auth as /d/.
    """
    if token != MCP_BEARER_TOKEN:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_ticker_page(ticker)


if not MCP_BEARER_TOKEN:
    raise RuntimeError(
        "MCP_BEARER_TOKEN is not set. Refusing to start with no auth — "
        "the URL-as-secret mount path would be empty and the auth gate "
        "would silently 404 every request."
    )

app.mount(f"/mcp/{MCP_BEARER_TOKEN}", mcp_app)

