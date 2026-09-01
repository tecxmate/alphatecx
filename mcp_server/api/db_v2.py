"""Database queries for the v2 MCP server.

All queries target materialized views or read-only tables.
Uses psycopg3 connection pool (same as alphatecx v1).
"""
from __future__ import annotations

import os

from psycopg_pool import ConnectionPool

try:
    from query_safety import safe_flow_col
except ModuleNotFoundError:  # package import path used by local tests
    from .query_safety import safe_flow_col

DATABASE_URL = os.getenv("MCP_DATABASE_URL") or os.getenv("DATABASE_URL", "")
_pool: ConnectionPool | None = None

def _safe_col(col: str, default: str) -> str:
    return safe_flow_col(col, default)


def _configure(conn):
    """Neon's pooler clears session settings on reset and rejects
    `options=-csearch_path` at startup. Set search_path per-connection."""
    with conn.cursor() as c:
        c.execute("SET search_path TO public, neon_auth")
    conn.commit()


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL, min_size=0, max_size=3, open=True,
            configure=_configure,
        )
    return _pool


def _fetch(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT and return rows as dicts."""
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _serialize(rows: list[dict]) -> list[dict]:
    """Ensure all values are JSON-serializable."""
    import decimal
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
            elif isinstance(v, decimal.Decimal):
                row[k] = float(v)
    return rows


# ── Sector Momentum ────────────────────────────────────────────────────────

def query_sector_momentum(
    pillar: str | None = None,
    order_col: str = "foreign_5d",
    limit: int = 10,
) -> list[dict]:
    conditions = ["ai_pillar != 'unclassified'"]
    params: list = []

    if pillar:
        conditions.append("ai_pillar = %s")
        params.append(pillar)

    order_col = _safe_col(order_col, "foreign_5d")
    where = " AND ".join(conditions)
    sql = f"""
        SELECT ai_pillar, node,
               foreign_1d, total_1d,
               foreign_3d, total_3d,
               foreign_5d, total_5d,
               foreign_10d, total_10d,
               foreign_20d, total_20d,
               tickers_5d,
               top_ticker_5d, top_ticker_5d_name,
               refreshed_at
        FROM view_sector_momentum
        WHERE {where}
        ORDER BY {order_col} DESC
        LIMIT %s
    """
    params.append(limit)
    return _serialize(_fetch(sql, tuple(params)))


# ── Ticker Momentum ────────────────────────────────────────────────────────

def query_ticker_momentum(
    pillar: str | None = None,
    node: str | None = None,
    ticker_id: str | None = None,
    order_col: str = "foreign_5d",
    limit: int = 15,
    min_streak: int = 0,
) -> list[dict]:
    conditions: list[str] = []
    params: list = []

    if pillar:
        conditions.append("ai_pillar = %s")
        params.append(pillar)
    if node:
        conditions.append("node = %s")
        params.append(node)
    if ticker_id:
        conditions.append("ticker_id = %s")
        params.append(ticker_id)
    if min_streak > 0:
        conditions.append("consecutive_foreign_buy_days >= %s")
        params.append(min_streak)

    where = " AND ".join(conditions) if conditions else "1=1"
    order_col = _safe_col(order_col, "foreign_5d")

    sql = f"""
        SELECT ticker_id, company_name, market, ai_pillar, node,
               foreign_1d, total_1d,
               foreign_3d, total_3d,
               foreign_5d, total_5d,
               foreign_10d, total_10d,
               foreign_20d, total_20d,
               consecutive_foreign_buy_days,
               refreshed_at
        FROM view_ticker_momentum
        WHERE {where}
        ORDER BY {order_col} DESC
        LIMIT %s
    """
    params.append(limit)
    return _serialize(_fetch(sql, tuple(params)))


def query_limit_board_enrichment(ticker_ids: list[str], as_of: str) -> dict[str, dict]:
    """Batch-join flow/valuation/ownership context for limit-board hits.

    One query for the whole hit list — the board is fetched live from the
    exchanges, so this is the only database round trip the scan makes.

    Every source is read as-of `as_of` rather than "latest", so a post-mortem
    of an old session reports what was knowable that day instead of today's
    numbers. Signals and valuation are LEFT JOINed: coverage is partial
    (OHLCV-derived signals exist only where the price harvester has run; TWSE
    BWIBBU carries no TPEX names), and a hit is never dropped for missing
    enrichment.
    """
    if not ticker_ids:
        return {}

    sql = """
        WITH ids AS (SELECT unnest(%s::text[]) AS ticker_id)
        SELECT
          i.ticker_id,
          dt.company_name, dt.market, dt.ai_pillar, dt.node,
          val.pe_ratio, val.pb_ratio, val.dividend_yield,
          COALESCE(val.valuation_known, false) AS valuation_known,
          flow.foreign_net_5d, flow.trust_net_5d, flow.dealer_net_5d,
          flow.foreign_net_z20, flow.flow_days,
          sig.rsi_14, sig.sma_50, sig.sma_200,
          sig.rs_vs_market_60, sig.pct_below_52w_high, sig.signals_as_of,
          hold.foreign_held_pct, hold.foreign_room_pct,
          mar.margin_balance, mar.margin_limit, mar.short_balance,
          rev.yoy_pct AS revenue_yoy_pct, rev.mom_pct AS revenue_mom_pct,
          rev.industry, rev.ym AS revenue_ym
        FROM ids i
        LEFT JOIN dim_ticker dt ON dt.ticker_id = i.ticker_id
        LEFT JOIN LATERAL (
          -- `valuation_known` separates "issuer has no positive earnings"
          -- (row present, pe_ratio NULL) from "we hold no valuation row for
          -- this name" (no row — most TPEX names). §6's no_earnings
          -- anti-flag may only fire on the former.
          SELECT v.pe_ratio, v.pb_ratio, v.dividend_yield, true AS valuation_known
          FROM raw_twse_valuation v
          WHERE v.ticker_id = i.ticker_id AND v.date <= %s
          ORDER BY v.date DESC LIMIT 1
        ) val ON true
        -- Flow comes straight from raw_twse_t86 rather than from
        -- signal_value/view_latest_signals. T86 is all-market (~12.8k
        -- tickers) while the signal tables only cover the ~58 classified
        -- names, and a limit-board hit is almost never one of those. Reading
        -- z20 from signal_value left it NULL for nearly every hit, which
        -- meant the `accumulating` flag never fired and `triage='sleeper'`
        -- was unreachable — the one verdict the scanner exists to produce.
        --
        -- Same definition as src/quant/indicators.zscore: (latest - mean20)
        -- / sample stddev20, so the classified names agree with q_indicators.
        LEFT JOIN LATERAL (
          SELECT
            SUM(t.foreign_net) FILTER (WHERE t.rn <= 5) AS foreign_net_5d,
            SUM(t.trust_net)   FILTER (WHERE t.rn <= 5) AS trust_net_5d,
            SUM(t.dealer_net)  FILTER (WHERE t.rn <= 5) AS dealer_net_5d,
            CASE WHEN COUNT(*) = 20 THEN
              (MAX(t.foreign_net) FILTER (WHERE t.rn = 1) - AVG(t.foreign_net))
              / NULLIF(STDDEV_SAMP(t.foreign_net), 0)
            END AS foreign_net_z20,
            COUNT(*) AS flow_days
          FROM (
            SELECT foreign_net, trust_net, dealer_net,
                   ROW_NUMBER() OVER (ORDER BY date DESC) AS rn
            FROM raw_twse_t86
            WHERE ticker_id = i.ticker_id AND date <= %s
            ORDER BY date DESC LIMIT 20
          ) t
        ) flow ON true
        LEFT JOIN LATERAL (
          SELECT
            MAX(s.date) AS signals_as_of,
            MAX(s.value) FILTER (WHERE s.signal_name = 'rsi_14')             AS rsi_14,
            MAX(s.value) FILTER (WHERE s.signal_name = 'sma_50')             AS sma_50,
            MAX(s.value) FILTER (WHERE s.signal_name = 'sma_200')            AS sma_200,
            MAX(s.value) FILTER (WHERE s.signal_name = 'rs_vs_market_60')    AS rs_vs_market_60,
            MAX(s.value) FILTER (WHERE s.signal_name = 'pct_below_52w_high') AS pct_below_52w_high
          FROM signal_value s
          WHERE s.ticker_id = i.ticker_id
            AND s.date = (
              SELECT MAX(date) FROM signal_value
              WHERE ticker_id = i.ticker_id AND date <= %s
            )
        ) sig ON true
        LEFT JOIN LATERAL (
          SELECT h.foreign_held_pct, h.foreign_room_pct
          FROM raw_twse_holdings h
          WHERE h.ticker_id = i.ticker_id AND h.date <= %s
          ORDER BY h.date DESC LIMIT 1
        ) hold ON true
        LEFT JOIN LATERAL (
          SELECT m.margin_balance, m.margin_limit, m.short_balance
          FROM raw_twse_margin m
          WHERE m.ticker_id = i.ticker_id AND m.date <= %s
          ORDER BY m.date DESC LIMIT 1
        ) mar ON true
        LEFT JOIN LATERAL (
          SELECT r.yoy_pct, r.mom_pct, r.industry, r.ym
          FROM raw_monthly_revenue r
          WHERE r.ticker_id = i.ticker_id AND r.ym <= %s
          ORDER BY r.ym DESC LIMIT 1
        ) rev ON true
    """
    params = (list(ticker_ids), as_of, as_of, as_of, as_of, as_of, as_of[:7])
    rows = _serialize(_fetch(sql, params))
    return {r["ticker_id"]: r for r in rows}


def query_flow_leaders(
    as_of: str,
    window_days: int = 20,
    markets: list[str] | None = None,
) -> list[dict]:
    """Market-wide per-ticker aggregation for `flow_leaders_scan`.

    One SQL pass computes, as-of `as_of`, everything the pure scorer in
    ``flow_leaders.score_row`` needs. The scan's whole edge is finding
    accumulation *before* the price moves, so this must cover the broad market,
    not the ~58 classified names — hence flow comes straight from
    ``raw_twse_t86`` (all-market, ~12.8k tickers) exactly as the limit-board
    enrichment does.

    The scoreable universe is bounded by where a **price** exists: TWSE BWIBBU
    (``raw_twse_valuation``, ~1.1k TWSE names, carries close + PE/PB/yield)
    unioned with the OHLCV top-500 harvest. Names with flow but no price (most
    TPEX) can't be measured for flatness and are excluded here rather than
    returned unscoreable. Driving the query off that priced set (~1.2k) instead
    of all of T86 keeps the per-ticker LATERAL joins ~10× cheaper.

    Price stats are **median-anchored** (median, p10, p90) rather than
    min/max/first/last: a single corrupt TWSE print — e.g. 4536's 87.3 on
    2026-05-13 between ~152 closes — otherwise wrecks every flatness metric.
    See flow_leaders.price_move_pct.

    z20 is the 20-day single-day z (same definition as
    ``query_limit_board_enrichment`` and ``src/quant/indicators.zscore``);
    ``buy_day_ratio`` and ``foreign_net_sum`` use the caller's `window_days`.
    """
    mkts = markets or ["TWSE", "TPEX"]
    w = max(2, min(int(window_days), 60))

    sql = """
        WITH px_raw AS (
          SELECT date, ticker_id, close FROM raw_twse_ohlcv
          WHERE date <= %(d)s AND close > 0
          UNION
          SELECT date, ticker_id, close FROM raw_twse_valuation
          WHERE date <= %(d)s AND close > 0
        ),
        px_win AS (
          SELECT ticker_id, close,
                 ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
          FROM px_raw
        ),
        px_stats AS (
          -- Median-anchored + percentile range: robust to a lone bad tick.
          SELECT ticker_id,
                 (array_agg(close ORDER BY rn ASC))[1]              AS close_today,
                 percentile_cont(0.5) WITHIN GROUP (ORDER BY close) AS med_close,
                 percentile_cont(0.1) WITHIN GROUP (ORDER BY close) AS p10,
                 percentile_cont(0.9) WITHIN GROUP (ORDER BY close) AS p90,
                 count(*)                                           AS price_days
          FROM px_win WHERE rn <= %(w)s GROUP BY ticker_id
        ),
        flow_win AS (
          SELECT ticker_id, foreign_net,
                 ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
          FROM raw_twse_t86 WHERE date <= %(d)s
        ),
        flow_stats AS (
          SELECT ticker_id,
                 sum(foreign_net) FILTER (WHERE rn <= %(w)s)                    AS foreign_net_sum,
                 (count(*) FILTER (WHERE rn <= %(w)s AND foreign_net > 0))::float
                   / NULLIF(count(*) FILTER (WHERE rn <= %(w)s), 0)             AS buy_day_ratio,
                 count(*) FILTER (WHERE rn <= %(w)s)                            AS flow_days,
                 CASE WHEN count(*) FILTER (WHERE rn <= 20) = 20 THEN
                   (max(foreign_net) FILTER (WHERE rn = 1) - avg(foreign_net) FILTER (WHERE rn <= 20))
                   / NULLIF(stddev_samp(foreign_net) FILTER (WHERE rn <= 20), 0)
                 END                                                            AS foreign_net_z20
          FROM flow_win GROUP BY ticker_id
        )
        SELECT dt.ticker_id, dt.company_name AS name, dt.market, dt.ai_pillar, dt.node,
               ps.close_today, ps.med_close, ps.p10, ps.p90, ps.price_days,
               fs.foreign_net_sum, fs.buy_day_ratio, fs.flow_days, fs.foreign_net_z20,
               v.pe_ratio, v.pb_ratio, v.dividend_yield,
               COALESCE(v.valuation_known, false) AS valuation_known,
               h.foreign_held_pct, h.foreign_room_pct,
               m.margin_balance, m.margin_limit, m.short_balance,
               o.turnover_twd,
               r.yoy_pct AS revenue_yoy_pct, r.mom_pct AS revenue_mom_pct,
               du.ex_date AS upcoming_ex_date, du.cash_value AS upcoming_cash_value,
               du.ex_type AS upcoming_ex_type,
               dr.ex_date AS recent_ex_date, dr.ex_type AS recent_ex_type,
               fd.cash_dividend AS fm_cash_dividend, fd.stock_dividend AS fm_stock_dividend,
               fx.finmind_recent_ex,
               COALESCE(fn.recent_news_count, 0) AS recent_news_count,
               COALESCE(fn.governance_news_count, 0) AS governance_news_count,
               fn.news_headlines
        FROM px_stats ps
        JOIN dim_ticker dt USING (ticker_id)
        JOIN flow_stats fs USING (ticker_id)
        LEFT JOIN LATERAL (
          SELECT pe_ratio, pb_ratio, dividend_yield, true AS valuation_known
          FROM raw_twse_valuation
          WHERE ticker_id = ps.ticker_id AND date <= %(d)s ORDER BY date DESC LIMIT 1
        ) v ON true
        LEFT JOIN LATERAL (
          SELECT foreign_held_pct, foreign_room_pct FROM raw_twse_holdings
          WHERE ticker_id = ps.ticker_id AND date <= %(d)s ORDER BY date DESC LIMIT 1
        ) h ON true
        LEFT JOIN LATERAL (
          SELECT margin_balance, margin_limit, short_balance FROM raw_twse_margin
          WHERE ticker_id = ps.ticker_id AND date <= %(d)s ORDER BY date DESC LIMIT 1
        ) m ON true
        LEFT JOIN LATERAL (
          SELECT turnover_twd FROM raw_twse_ohlcv
          WHERE ticker_id = ps.ticker_id AND date <= %(d)s ORDER BY date DESC LIMIT 1
        ) o ON true
        LEFT JOIN LATERAL (
          SELECT yoy_pct, mom_pct FROM raw_monthly_revenue
          WHERE ticker_id = ps.ticker_id AND ym <= %(ym)s ORDER BY ym DESC LIMIT 1
        ) r ON true
        -- Next scheduled ex-dividend (forecast or actual) — carries the cash-only
        -- figure that gates the forward-yield flag + ex-div proximity (v2 #1/#3).
        LEFT JOIN LATERAL (
          SELECT ex_date, cash_value, ex_type FROM raw_twse_dividend
          WHERE ticker_id = ps.ticker_id AND ex_date > %(d)s ORDER BY ex_date ASC LIMIT 1
        ) du ON true
        -- Most recent past ex (for recently_ex — a fresh ex-drop can look 'flat').
        LEFT JOIN LATERAL (
          SELECT ex_date, ex_type FROM raw_twse_dividend
          WHERE ticker_id = ps.ticker_id AND ex_date <= %(d)s ORDER BY ex_date DESC LIMIT 1
        ) dr ON true
        -- FinMind dividend policy (latest fiscal year): cash/stock split (v2 #1).
        LEFT JOIN LATERAL (
          SELECT cash_dividend, stock_dividend FROM raw_finmind_dividend
          WHERE ticker_id = ps.ticker_id ORDER BY year DESC LIMIT 1
        ) fd ON true
        -- FinMind's most recent *past* ex across cash+stock legs. Fuller history
        -- than TWT49U (which only starts mid-2026) — it is what catches 晶華's
        -- April ex for the dividend_trap check (v2 #2).
        LEFT JOIN LATERAL (
          SELECT max(ex) AS finmind_recent_ex FROM (
            SELECT cash_ex_date AS ex FROM raw_finmind_dividend
              WHERE ticker_id = ps.ticker_id AND cash_ex_date <= %(d)s
            UNION ALL
            SELECT stock_ex_date FROM raw_finmind_dividend
              WHERE ticker_id = ps.ticker_id AND stock_ex_date <= %(d)s
          ) e
        ) fx ON true
        -- Material/governance news in the trailing 30d (v2 #4). Headlines capped
        -- at 3 for the agent to surface; governance flag precomputed at load.
        LEFT JOIN LATERAL (
          SELECT count(*) AS recent_news_count,
                 count(*) FILTER (WHERE is_governance) AS governance_news_count,
                 (array_agg(title ORDER BY news_date DESC))[1:3] AS news_headlines
          FROM raw_finmind_news
          WHERE ticker_id = ps.ticker_id AND news_date >= (%(d)s::date - 30)
        ) fn ON true
        WHERE fs.flow_days >= 5 AND dt.market = ANY(%(markets)s)
    """
    params = {"d": as_of, "w": w, "ym": as_of[:7], "markets": mkts}
    return _serialize(_fetch(sql, params))


def latest_flow_date() -> str | None:
    """Most recent date with institutional-flow rows (the flow ETL's high-water
    mark). `flow_leaders_scan` defaults its as-of to this so a scan always
    reflects the freshest harvested session, not a half-loaded 'today'."""
    rows = _fetch("SELECT MAX(date) AS d FROM raw_twse_t86")
    d = rows[0]["d"] if rows else None
    return d.isoformat() if hasattr(d, "isoformat") else d


def query_dividend(ticker_id: str, as_of: str) -> dict:
    """Most-recent-past and next-upcoming ex-dividend/ex-rights for a ticker,
    relative to `as_of`. The ex trading date is decisive: a buyer on or after it
    does NOT receive that distribution."""
    cols = ("ex_date, ex_type, cash_value, pre_ex_close, reference_price, status")
    recent = _fetch(
        f"SELECT {cols} FROM raw_twse_dividend "
        "WHERE ticker_id = %s AND ex_date <= %s ORDER BY ex_date DESC LIMIT 1",
        (ticker_id, as_of),
    )
    upcoming = _fetch(
        f"SELECT {cols} FROM raw_twse_dividend "
        "WHERE ticker_id = %s AND ex_date > %s ORDER BY ex_date ASC LIMIT 1",
        (ticker_id, as_of),
    )
    return {
        "most_recent": _serialize(recent)[0] if recent else None,
        "upcoming": _serialize(upcoming)[0] if upcoming else None,
    }


def ticker_markets(ticker_ids: list[str]) -> dict[str, str]:
    """Map each ticker_id to its market ('TWSE'/'TPEX') from dim_ticker, for
    building MIS `ex_ch` prefixes. Unknown ids are simply absent — the quote
    tool then probes both boards for them."""
    if not ticker_ids:
        return {}
    rows = _fetch(
        "SELECT ticker_id, market FROM dim_ticker WHERE ticker_id = ANY(%s)",
        (list(ticker_ids),),
    )
    return {r["ticker_id"]: r["market"] for r in rows}


def market_closure(date_iso: str) -> dict | None:
    """Return the closure record for `date_iso` (YYYY-MM-DD) if the market is
    shut that day per the calendar, else None. Weekends are handled by the
    caller in code; this covers statutory holidays and manual typhoon inserts."""
    rows = _fetch(
        "SELECT name, source, note FROM market_holidays "
        "WHERE cal_date = %s AND is_closed",
        (date_iso,),
    )
    return rows[0] if rows else None


def query_market_flow_screener(
    market: str | None = None,
    classification: str = "all",
    search: str | None = None,
    min_streak: int = 0,
    foreign_1d_above: int | None = None,
    foreign_5d_above: int | None = None,
    foreign_20d_above: int | None = None,
    total_5d_above: int | None = None,
    sort_by: str = "foreign_5d",
    sort_direction: str = "desc",
    limit: int = 50,
) -> list[dict]:
    """Screen the full TWSE/TPEX flow universe from view_ticker_momentum.

    This is intentionally flow-first: T86 coverage is all-market, while
    OHLCV-derived technical indicators currently exist only where the daily
    price harvester has populated history. Signal fields are included via a
    LEFT JOIN when available, but lack of signal coverage does not exclude
    an otherwise valid all-market flow row.
    """
    conditions: list[str] = []
    params: list = []

    if market:
        market_norm = market.upper()
        if market_norm not in ("TWSE", "TPEX"):
            return [{"error": "market must be 'TWSE' or 'TPEX'"}]
        conditions.append("tm.market = %s")
        params.append(market_norm)

    if classification == "classified":
        conditions.append("tm.ai_pillar != 'unclassified'")
    elif classification == "unclassified":
        conditions.append("tm.ai_pillar = 'unclassified'")
    elif classification != "all":
        return [{"error": "classification must be 'all', 'classified', or 'unclassified'"}]

    if search:
        q = f"%{search.strip()}%"
        conditions.append("(tm.ticker_id ILIKE %s OR tm.company_name ILIKE %s)")
        params.extend([q, q])

    if min_streak > 0:
        conditions.append("tm.consecutive_foreign_buy_days >= %s")
        params.append(int(min_streak))
    if foreign_1d_above is not None:
        conditions.append("tm.foreign_1d >= %s")
        params.append(int(foreign_1d_above))
    if foreign_5d_above is not None:
        conditions.append("tm.foreign_5d >= %s")
        params.append(int(foreign_5d_above))
    if foreign_20d_above is not None:
        conditions.append("tm.foreign_20d >= %s")
        params.append(int(foreign_20d_above))
    if total_5d_above is not None:
        conditions.append("tm.total_5d >= %s")
        params.append(int(total_5d_above))

    where = " AND ".join(conditions) if conditions else "1=1"
    order_col = _safe_col(sort_by, "foreign_5d")
    direction = "ASC" if str(sort_direction).lower() == "asc" else "DESC"
    limit = max(1, min(int(limit), 200))

    sql = f"""
        SELECT
          tm.ticker_id, tm.company_name, tm.market,
          tm.ai_pillar, tm.node,
          tm.foreign_1d, tm.total_1d,
          tm.foreign_3d, tm.total_3d,
          tm.foreign_5d, tm.total_5d,
          tm.foreign_10d, tm.total_10d,
          tm.foreign_20d, tm.total_20d,
          tm.consecutive_foreign_buy_days,
          ls.as_of AS signals_as_of,
          ls.rsi_14, ls.sma_50, ls.sma_200, ls.rs_vs_market_60,
          ls.pct_below_52w_high, ls.foreign_net_z20,
          tm.refreshed_at
        FROM view_ticker_momentum tm
        LEFT JOIN view_latest_signals ls ON ls.ticker_id = tm.ticker_id
        WHERE {where}
        ORDER BY tm.{order_col} {direction}, tm.ticker_id
        LIMIT %s
    """
    params.append(limit)
    return _serialize(_fetch(sql, tuple(params)))


# ── Supply Chain Map ───────────────────────────────────────────────────────

def query_supply_chain(
    pillar: str | None = None,
    node: str | None = None,
    search: str | None = None,
) -> list[dict]:
    conditions = ["ai_pillar IS NOT NULL"]
    params: list = []

    if pillar:
        conditions.append("ai_pillar = %s")
        params.append(pillar)
    if node:
        conditions.append("node = %s")
        params.append(node)
    if search:
        conditions.append("(ticker_id ILIKE %s OR company_name ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    sql = f"""
        SELECT ticker_id, company_name, market, ai_pillar, node, us_partners
        FROM dim_supply_chain
        WHERE {where}
        ORDER BY ai_pillar, node, ticker_id
    """
    return _serialize(_fetch(sql, tuple(params)))


# ── Ticker Lookup ──────────────────────────────────────────────────────────

def query_ticker_lookup(query: str, limit: int = 8) -> list[dict]:
    """Search the full ticker directory by ticker code or company name."""
    q = (query or "").strip()
    if not q:
        return []

    exact_ticker = q.upper()
    prefix = f"{q}%"
    contains = f"%{q}%"
    sql = """
        SELECT ticker_id, company_name, ai_pillar, node
        FROM dim_ticker
        WHERE ticker_id = %s
           OR ticker_id ILIKE %s
           OR company_name = %s
           OR company_name ILIKE %s
        ORDER BY
          CASE
            WHEN ticker_id = %s THEN 0
            WHEN company_name = %s THEN 1
            WHEN company_name ILIKE %s THEN 2
            WHEN ticker_id ILIKE %s THEN 3
            ELSE 4
          END,
          ticker_id
        LIMIT %s
    """
    return _serialize(_fetch(sql, (
        exact_ticker,
        prefix,
        q,
        contains,
        exact_ticker,
        q,
        prefix,
        prefix,
        max(1, min(int(limit), 20)),
    )))


# ── Flow History ───────────────────────────────────────────────────────────

def query_flow_history(ticker_id: str, days: int = 20) -> list[dict]:
    sql = """
        SELECT date, ticker_id, company_name, market,
               foreign_net, trust_net, dealer_net, total_net
        FROM raw_twse_t86
        WHERE ticker_id = %s
        ORDER BY date DESC
        LIMIT %s
    """
    rows = _fetch(sql, (ticker_id, days))
    rows.reverse()  # oldest first for time series
    return _serialize(rows)


# ── Compare Nodes ──────────────────────────────────────────────────────────

def query_compare_nodes(
    nodes: list[str],
    foreign_col: str = "foreign_5d",
    total_col: str = "total_5d",
) -> list[dict]:
    if not nodes:
        return []
    foreign_col = _safe_col(foreign_col, "foreign_5d")
    total_col = _safe_col(total_col, "total_5d")
    placeholders = ", ".join(["%s"] * len(nodes))
    sql = f"""
        SELECT ai_pillar, node,
               {foreign_col} AS foreign_flow,
               {total_col} AS total_flow,
               tickers_5d,
               top_ticker_5d, top_ticker_5d_name
        FROM view_sector_momentum
        WHERE node IN ({placeholders})
        ORDER BY {foreign_col} DESC
    """
    return _serialize(_fetch(sql, tuple(nodes)))


# ── Quant signals ─────────────────────────────────────────────────────────
#
# Phase 1 of the analysis-system plan. Reads from view_latest_signals
# (wide-form snapshot, refreshed by compute_signals.py) and signal_value
# (long-form history, used by backtest queries).

# Allowlist of signal names that callers can interrogate. Same enforcement
# pattern as _ALLOWED_FLOW_COLS — keeps callers from injecting arbitrary
# strings into SQL identifiers or filters.
_ALLOWED_SIGNALS = frozenset({
    "rsi_14", "macd_line", "macd_signal_line", "macd_histogram",
    "bb_pct_b", "atr_14", "sma_50", "sma_200", "rs_vs_market_60",
    "pct_below_52w_high",
    "foreign_net_z20", "foreign_net_5d_sum", "total_net_z20",
})


def query_indicators(ticker_id: str) -> dict:
    """Latest indicator stack for one ticker. Reads view_latest_signals."""
    sql = """
        SELECT ticker_id, as_of, rsi_14, macd_line, macd_signal_line,
               macd_histogram, bb_pct_b, atr_14, sma_50, sma_200,
               rs_vs_market_60, pct_below_52w_high,
               foreign_net_z20, foreign_net_5d_sum, total_net_z20
        FROM view_latest_signals WHERE ticker_id = %s
    """
    rows = _fetch(sql, (ticker_id,))
    if not rows:
        return {"ticker_id": ticker_id, "found": False}
    return {**_serialize(rows)[0], "found": True}


def query_price_history(ticker_id: str, days: int = 90) -> list[dict]:
    """Chart-ready OHLCV history for one ticker, oldest first."""
    days = max(1, min(int(days), 365))
    sql = """
        SELECT date, ticker_id, open, high, low, close,
               volume_shares AS volume, turnover_twd
        FROM raw_twse_ohlcv
        WHERE ticker_id = %s
          AND close IS NOT NULL
        ORDER BY date DESC
        LIMIT %s
    """
    rows = _fetch(sql, (ticker_id, days))
    rows.reverse()
    return _serialize(rows)


def query_beginner_stock_card(ticker_id: str) -> dict:
    """Beginner-facing factual stock card.

    This intentionally avoids buy/sell/quality judgments. It gathers the
    same raw fields used by advanced tools, then groups them into plain
    sections that product clients can render as cards, charts, or LINE text.
    """
    company = query_supply_chain(search=ticker_id)
    company_row = next((row for row in company if row.get("ticker_id") == ticker_id), company[0] if company else {})
    indicators = query_indicators(ticker_id)
    valuation_rows = query_valuation(ticker_id=ticker_id, top_n=1)
    valuation = valuation_rows[0] if valuation_rows else {}
    momentum_rows = query_ticker_momentum(ticker_id=ticker_id, limit=1)
    momentum = momentum_rows[0] if momentum_rows else {}
    price_rows = query_price_history(ticker_id=ticker_id, days=90)
    latest_price = price_rows[-1] if price_rows else {}
    previous_price = price_rows[-2] if len(price_rows) >= 2 else {}

    close = latest_price.get("close") or valuation.get("close")
    prev_close = previous_price.get("close")
    change_pct = None
    if close is not None and prev_close not in (None, 0):
        change_pct = (float(close) / float(prev_close) - 1.0) * 100.0

    chart_points = [
        {
            "date": row.get("date"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
        }
        for row in price_rows[-90:]
    ]

    return {
        "ticker_id": ticker_id,
        "company_name": company_row.get("company_name") or valuation.get("company_name"),
        "market": company_row.get("market") or momentum.get("market"),
        "pillar": company_row.get("ai_pillar") or momentum.get("ai_pillar"),
        "node": company_row.get("node") or momentum.get("node"),
        "as_of": indicators.get("as_of") or valuation.get("date") or latest_price.get("date"),
        "price": {
            "open": latest_price.get("open"),
            "high": latest_price.get("high"),
            "low": latest_price.get("low"),
            "close": close,
            "previous_close": prev_close,
            "change_pct": change_pct,
            "volume": latest_price.get("volume"),
            "turnover_twd": latest_price.get("turnover_twd"),
            "date": latest_price.get("date") or valuation.get("date"),
        },
        "trend_numbers": {
            "rsi_14": indicators.get("rsi_14"),
            "macd_histogram": indicators.get("macd_histogram"),
            "bb_pct_b": indicators.get("bb_pct_b"),
            "sma_50": indicators.get("sma_50"),
            "sma_200": indicators.get("sma_200"),
            "rs_vs_market_60": indicators.get("rs_vs_market_60"),
            "pct_below_52w_high": indicators.get("pct_below_52w_high"),
        },
        "flow_numbers": {
            "foreign_1d": momentum.get("foreign_1d"),
            "foreign_5d": momentum.get("foreign_5d"),
            "foreign_10d": momentum.get("foreign_10d"),
            "foreign_20d": momentum.get("foreign_20d"),
            "total_5d": momentum.get("total_5d"),
            "consecutive_foreign_buy_days": momentum.get("consecutive_foreign_buy_days"),
            "foreign_net_z20": indicators.get("foreign_net_z20"),
        },
        "valuation_numbers": {
            "pe_ratio": valuation.get("pe_ratio"),
            "pb_ratio": valuation.get("pb_ratio"),
            "dividend_yield": valuation.get("dividend_yield"),
            "dividend_year": valuation.get("dividend_year"),
            "fiscal_period": valuation.get("fiscal_period"),
        },
        "beginner_labels": [
            {"key": "RSI", "meaning": "Momentum scale from 0 to 100."},
            {"key": "MACD histogram", "meaning": "Trend momentum number."},
            {"key": "BB%B", "meaning": "Price location inside Bollinger Bands."},
            {"key": "Foreign flow", "meaning": "Foreign investor net buying or selling over a time window."},
            {"key": "PE/PB/yield", "meaning": "Common valuation numbers."},
        ],
        "chart": {
            "type": "line",
            "period_days": 90,
            "points": chart_points,
        },
    }


def query_screener(
    rsi_below: float | None = None,
    rsi_above: float | None = None,
    macd_hist_above: float | None = None,
    above_sma_200: bool | None = None,
    rs_above: float | None = None,
    rs_below: float | None = None,
    foreign_z_above: float | None = None,
    foreign_z_below: float | None = None,
    pct_below_52w_high_above: float | None = None,
    pct_below_52w_high_below: float | None = None,
    universe: str = "classified",
) -> list[dict]:
    """Screen latest signals across classified or all signal-covered tickers.

    Combines conditions with AND. Joins view_latest_signals with
    raw_twse_ohlcv to expose latest close + dim_ticker for pillar/node.
    """
    conditions: list[str] = []
    params: list = []

    if universe == "classified":
        conditions.append("dt.ai_pillar IS NOT NULL")
    elif universe != "all_with_signals":
        return [{"error": "universe must be 'classified' or 'all_with_signals'"}]

    if rsi_below is not None:
        conditions.append("ls.rsi_14 < %s")
        params.append(rsi_below)
    if rsi_above is not None:
        conditions.append("ls.rsi_14 > %s")
        params.append(rsi_above)
    if macd_hist_above is not None:
        conditions.append("ls.macd_histogram > %s")
        params.append(macd_hist_above)
    if above_sma_200 is True:
        conditions.append("o.close > ls.sma_200")
    elif above_sma_200 is False:
        conditions.append("o.close < ls.sma_200")
    if rs_above is not None:
        conditions.append("ls.rs_vs_market_60 > %s")
        params.append(rs_above)
    if rs_below is not None:
        conditions.append("ls.rs_vs_market_60 < %s")
        params.append(rs_below)
    if foreign_z_above is not None:
        conditions.append("ls.foreign_net_z20 > %s")
        params.append(foreign_z_above)
    if foreign_z_below is not None:
        conditions.append("ls.foreign_net_z20 < %s")
        params.append(foreign_z_below)
    if pct_below_52w_high_above is not None:
        # Stored as a negative or zero number; "above" a threshold like -5
        # means "within 5% of the high" (i.e. closer to high than -5%).
        conditions.append("ls.pct_below_52w_high > %s")
        params.append(pct_below_52w_high_above)
    if pct_below_52w_high_below is not None:
        # Useful for finding names far from their highs, e.g. below -20.
        conditions.append("ls.pct_below_52w_high < %s")
        params.append(pct_below_52w_high_below)

    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""
        SELECT ls.ticker_id, dt.company_name, dt.market, dt.ai_pillar, dt.node,
               o.close AS latest_close, ls.as_of,
               ls.rsi_14, ls.macd_histogram, ls.bb_pct_b,
               ls.sma_50, ls.sma_200, ls.rs_vs_market_60,
               ls.pct_below_52w_high, ls.foreign_net_z20,
               ls.foreign_net_5d_sum, ls.total_net_z20
        FROM view_latest_signals ls
        JOIN dim_ticker dt ON dt.ticker_id = ls.ticker_id
        LEFT JOIN raw_twse_ohlcv o
          ON o.ticker_id = ls.ticker_id AND o.date = ls.as_of
        WHERE {where}
        ORDER BY ls.ticker_id
    """
    return _serialize(_fetch(sql, tuple(params)))


def query_backtest(
    signal_name: str,
    threshold: float,
    direction: str = "below",
    forward_days: int = 5,
    lookback_days: int = 365,
) -> dict:
    """Backtest a single-threshold signal rule. Mirrors src/quant/backtest.py."""
    if signal_name not in _ALLOWED_SIGNALS:
        return {"error": f"Unknown signal '{signal_name}'. "
                         f"Allowed: {sorted(_ALLOWED_SIGNALS)}"}
    if direction not in ("below", "above"):
        return {"error": "direction must be 'below' or 'above'"}
    op = "<" if direction == "below" else ">"

    sql = f"""
        WITH triggers AS (
            SELECT s.ticker_id, s.date AS trigger_date, s.value AS signal_value
            FROM signal_value s
            WHERE s.signal_name = %s
              AND s.value {op} %s
              AND s.date >= current_date - (%s || ' days')::interval
        ),
        bars AS (
            SELECT ticker_id, date, close,
                   LEAD(close, %s) OVER (PARTITION BY ticker_id ORDER BY date) AS forward_close
            FROM raw_twse_ohlcv
        )
        SELECT t.ticker_id, t.trigger_date,
               (b.forward_close / b.close - 1.0) * 100.0 AS pct_return
        FROM triggers t
        JOIN bars b ON b.ticker_id = t.ticker_id AND b.date = t.trigger_date
        WHERE b.forward_close IS NOT NULL
    """
    rows = _fetch(sql, (signal_name, threshold, str(lookback_days), forward_days))

    if not rows:
        return {
            "signal": signal_name,
            "rule": f"{signal_name} {op} {threshold}",
            "n_observations": 0,
            "sample_warning": "No triggers in lookback window",
        }

    returns = [float(r["pct_return"]) for r in rows]
    n = len(returns)
    n_winners = sum(1 for r in returns if r > 0)
    by_ticker: dict[str, int] = {}
    for r in rows:
        by_ticker[r["ticker_id"]] = by_ticker.get(r["ticker_id"], 0) + 1

    sample_warning = None
    if n < 30:
        sample_warning = (
            f"Only {n} observations — illustrative, not predictive. "
            f"More history needed for robust validation."
        )

    avg = sum(returns) / n
    sorted_r = sorted(returns)
    median = sorted_r[n // 2] if n % 2 == 1 else (sorted_r[n//2 - 1] + sorted_r[n//2]) / 2

    return {
        "signal": signal_name,
        "rule": f"{signal_name} {op} {threshold}",
        "forward_days": forward_days,
        "lookback_days": lookback_days,
        "n_observations": n,
        "hit_rate_pct": round(100.0 * n_winners / n, 2),
        "avg_return_pct": round(avg, 3),
        "median_return_pct": round(median, 3),
        "best_return_pct": round(max(returns), 3),
        "worst_return_pct": round(min(returns), 3),
        "sample_warning": sample_warning,
        "samples_by_ticker": dict(sorted(by_ticker.items())),
    }


def query_backtest_compound(
    conditions: list[dict],
    forward_days: int = 5,
    lookback_days: int = 365,
) -> dict:
    """AND-combined multi-condition backtest. Each condition self-joins
    signal_value once; capped at 4 conditions to keep planner happy."""
    if not conditions:
        return {"error": "compound rule needs at least one condition"}
    if len(conditions) > 4:
        return {"error": "max 4 conditions"}

    for i, cond in enumerate(conditions):
        if cond.get("signal") not in _ALLOWED_SIGNALS:
            return {"error": f"condition {i}: unknown signal '{cond.get('signal')}'"}
        if cond.get("op") not in ("<", ">"):
            return {"error": f"condition {i}: op must be '<' or '>'"}

    joins, where_clauses = [], []
    params: list = []
    for i, cond in enumerate(conditions):
        alias = f"s{i}"
        if i == 0:
            joins.append(f"FROM signal_value {alias}")
        else:
            joins.append(
                f"JOIN signal_value {alias} "
                f"ON {alias}.ticker_id = s0.ticker_id "
                f"AND {alias}.date = s0.date"
            )
        where_clauses.append(f"{alias}.signal_name = %s AND {alias}.value {cond['op']} %s")
        params.extend([cond["signal"], cond["threshold"]])

    where_clauses.append("s0.date >= current_date - (%s || ' days')::interval")
    params.append(str(lookback_days))

    rule = " AND ".join(f"{c['signal']} {c['op']} {c['threshold']}" for c in conditions)
    sql = f"""
        WITH triggers AS (
            SELECT s0.ticker_id, s0.date AS trigger_date
            {' '.join(joins)}
            WHERE {' AND '.join(where_clauses)}
        ),
        bars AS (
            SELECT ticker_id, date, close,
                   LEAD(close, %s) OVER (PARTITION BY ticker_id ORDER BY date) AS forward_close
            FROM raw_twse_ohlcv
        )
        SELECT t.ticker_id, t.trigger_date,
               (b.forward_close / b.close - 1.0) * 100.0 AS pct_return
        FROM triggers t
        JOIN bars b ON b.ticker_id = t.ticker_id AND b.date = t.trigger_date
        WHERE b.forward_close IS NOT NULL
    """
    params.append(forward_days)
    rows = _fetch(sql, tuple(params))

    if not rows:
        return {"rule": rule, "n_observations": 0,
                "sample_warning": "No triggers met all conditions"}

    returns = [float(r["pct_return"]) for r in rows]
    n = len(returns)
    n_winners = sum(1 for r in returns if r > 0)
    by_ticker: dict[str, int] = {}
    for r in rows:
        by_ticker[r["ticker_id"]] = by_ticker.get(r["ticker_id"], 0) + 1

    sorted_r = sorted(returns)
    median = sorted_r[n // 2] if n % 2 == 1 else (sorted_r[n // 2 - 1] + sorted_r[n // 2]) / 2

    return {
        "rule": rule,
        "forward_days": forward_days,
        "lookback_days": lookback_days,
        "n_observations": n,
        "hit_rate_pct": round(100.0 * n_winners / n, 2),
        "avg_return_pct": round(sum(returns) / n, 3),
        "median_return_pct": round(median, 3),
        "best_return_pct": round(max(returns), 3),
        "worst_return_pct": round(min(returns), 3),
        "sample_warning": (f"Only {n} obs — illustrative" if n < 30 else None),
        "samples_by_ticker": dict(sorted(by_ticker.items())),
    }


# ── News (Phase 2a — ingestion only, no sentiment yet) ───────────────────

def query_news_recent(
    days: int = 1,
    source: str | None = None,
    lang: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Recent articles. Sorted by published_at, falling back to fetched_at
    when the source feed didn't include a date (Nikkei Asia, some Atom
    feeds). Cap at 200 to keep response sizes sane."""
    limit = min(max(limit, 1), 200)
    conditions = ["COALESCE(published_at, fetched_at) >= now() - (%s || ' days')::interval"]
    params: list = [str(days)]
    if source:
        conditions.append("source = %s")
        params.append(source)
    if lang:
        conditions.append("lang = %s")
        params.append(lang)

    where = " AND ".join(conditions)
    sql = f"""
        SELECT url, source, feed_name, lang, title, raw_summary,
               published_at, fetched_at
        FROM raw_news
        WHERE {where}
        ORDER BY COALESCE(published_at, fetched_at) DESC
        LIMIT {limit}
    """
    return _serialize(_fetch(sql, tuple(params)))


def query_news_for_ticker(
    ticker_id: str,
    days: int = 14,
    limit: int = 30,
) -> list[dict]:
    """Articles mentioning a ticker.

    Until Phase 2b's entity-extraction populates ticker_mentions, falls
    back to text matching: ticker code in title (e.g. '2330') OR company
    name. Looks up names from dim_ticker so we get the curated company
    name and any aliases stored there.
    """
    limit = min(max(limit, 1), 100)

    # Look up the ticker's company name + ai_pillar context
    name_rows = _fetch(
        "SELECT company_name, ai_pillar, node FROM dim_ticker WHERE ticker_id = %s",
        (ticker_id,),
    )
    if not name_rows:
        return []
    company_name = name_rows[0]["company_name"]

    # Build a flexible match: code-as-substring OR name-as-substring.
    # Code match needs to be word-boundary-aware (avoid '2330' matching
    # '23300') — Postgres doesn't have \b, so use a regex.
    sql = """
        SELECT url, source, feed_name, lang, title, raw_summary,
               published_at, fetched_at
        FROM raw_news
        WHERE COALESCE(published_at, fetched_at) >= now() - (%s || ' days')::interval
          AND (
              -- ticker mentions array (Phase 2b will populate)
              %s = ANY(COALESCE(ticker_mentions, ARRAY[]::TEXT[]))
              -- text fallback: code as a standalone token
              OR title ~ ('(^|[^0-9])' || %s || '([^0-9]|$)')
              -- text fallback: company name substring (case-insensitive)
              OR title ILIKE %s
              OR (raw_summary IS NOT NULL AND raw_summary ILIKE %s)
          )
        ORDER BY COALESCE(published_at, fetched_at) DESC
        LIMIT %s
    """
    name_pattern = f"%{company_name}%"
    return _serialize(_fetch(sql, (
        str(days),
        ticker_id, ticker_id,
        name_pattern, name_pattern,
        limit,
    )))


def query_news_source_status() -> list[dict]:
    """Per-source freshness — how recent is each feed's content?
    Useful for catching dead/stale sources."""
    sql = """
        SELECT source, feed_name, count(*) AS articles,
               max(published_at) AS latest_published,
               max(fetched_at) AS latest_fetched
        FROM raw_news
        GROUP BY source, feed_name
        ORDER BY source
    """
    return _serialize(_fetch(sql))


# ── Watchlist (Phase 3.5 — bot-managed, DB source of truth) ──────────────

def query_universe(filter: str = "all") -> list[dict]:
    """Read view_universe — one row per classified ticker, watch-state
    + signals + static knowledge in a single result.

    Filters:
      'all'        — every classified ticker (~26 rows; default)
      'watching'   — only watch_status='active'
      'extreme'    — names tripping signal-extreme thresholds
                     (RSI>80/<20, BB outside [0,1], abs(foreign_z)>2)
    """
    if filter == "watching":
        sql = "SELECT * FROM view_universe WHERE watch_status = 'active'"
    elif filter == "extreme":
        sql = """
            SELECT * FROM view_universe
            WHERE rsi_14 > 80 OR rsi_14 < 20
               OR bb_pct_b > 1.0 OR bb_pct_b < 0.0
               OR abs(foreign_net_z20) > 2.0
        """
    elif filter == "all":
        sql = "SELECT * FROM view_universe"
    else:
        return [{"error": f"unknown filter '{filter}' "
                          "(use 'all'|'watching'|'extreme')"}]
    return _serialize(_fetch(sql))


# ── Watchlist mutations (writer-via-mcp_viewer scoped INSERT/UPDATE) ─────
#
# These bypass _fetch (which is SELECT-only) and use the pool's
# connection directly so we can run INSERT/UPDATE statements. mcp_viewer
# was granted INSERT+UPDATE on watchlist (and ONLY watchlist) in 003.
# Every other DDL/DML attempt would fail at the role level — defense
# in depth even if a future code path tries to mutate something else.

def mutate_watchlist_add(
    ticker_id: str,
    reason: str | None = None,
    escalation_trigger: str | None = None,
) -> dict:
    """Add a ticker to the watchlist (or reactivate an archived one).
    Validates the ticker exists in dim_supply_chain — same rule the bot
    enforces — so the watchlist stays bounded to the curated 26."""
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT company_name, ai_pillar, node "
                "FROM dim_supply_chain WHERE ticker_id = %s",
                (ticker_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"ok": False,
                        "error": f"{ticker_id} not in classified "
                                 "supply chain (dim_supply_chain)"}
            company, pillar, node = row
            cur.execute("""
                INSERT INTO watchlist (ticker_id, company_name, ai_pillar, node,
                                       reason, escalation_trigger,
                                       added_at, updated_at, status)
                VALUES (%s, %s, %s, %s, %s, %s, now(), now(), 'active')
                ON CONFLICT (ticker_id) DO UPDATE SET
                    reason = COALESCE(NULLIF(EXCLUDED.reason, ''), watchlist.reason),
                    escalation_trigger = COALESCE(
                        NULLIF(EXCLUDED.escalation_trigger, ''),
                        watchlist.escalation_trigger),
                    status = 'active',
                    updated_at = now()
                """, (ticker_id, company, pillar, node, reason, escalation_trigger))
            conn.commit()
    return {"ok": True, "ticker_id": ticker_id, "company": company,
            "ai_pillar": pillar, "node": node, "status": "active"}


def mutate_watchlist_remove(ticker_id: str) -> dict:
    """Archive a watchlist entry (status='archived'). Idempotent: re-running on
    an already-archived ticker reports success and changes nothing.

    The UPDATE matching no row means one of two different things, and conflating
    them broke the idempotency this docstring promises: a second w_remove used to
    answer ok:false, so a caller checking `ok` read a completed archive as a
    failed one. Distinguish them — already archived is the no-op success,
    never-on-the-watchlist is the real error.
    """
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE watchlist SET status = 'archived', updated_at = now() "
                "WHERE ticker_id = %s AND status = 'active' "
                "RETURNING company_name",
                (ticker_id,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT company_name FROM watchlist WHERE ticker_id = %s",
                    (ticker_id,),
                )
                existing = cur.fetchone()
            else:
                existing = None
            conn.commit()
    if row:
        return {"ok": True, "ticker_id": ticker_id, "company": row[0],
                "status": "archived"}
    if existing:
        return {"ok": True, "ticker_id": ticker_id, "company": existing[0],
                "status": "archived", "already_archived": True}
    return {"ok": False, "ticker_id": ticker_id,
            "error": "not on watchlist"}


def query_watchlist(status: str = "active") -> list[dict]:
    """List watchlist rows. status='active' (default) | 'archived' | 'all'."""
    if status == "all":
        sql = """
            SELECT ticker_id, company_name, ai_pillar, node, reason,
                   escalation_trigger, status, added_at, updated_at
            FROM watchlist ORDER BY added_at DESC
        """
        rows = _fetch(sql, ())
    elif status in ("active", "archived"):
        sql = """
            SELECT ticker_id, company_name, ai_pillar, node, reason,
                   escalation_trigger, status, added_at, updated_at
            FROM watchlist WHERE status = %s ORDER BY added_at DESC
        """
        rows = _fetch(sql, (status,))
    else:
        return [{"error": f"unknown status '{status}'"}]
    return _serialize(rows)


# ── Digests (Phase 3 — cron-generated briefs) ─────────────────────────────

def query_digest_recent(days: int = 3, kind: str | None = None) -> list[dict]:
    """Recent digests written by cron briefs. Each row is one (date, kind)."""
    conditions = ["digest_date >= current_date - (%s || ' days')::interval"]
    params: list = [str(days)]
    if kind:
        if kind not in ("pre_market", "intraday_alert", "post_close", "thesis_status"):
            return [{"error": f"unknown kind '{kind}'"}]
        conditions.append("kind = %s")
        params.append(kind)
    where = " AND ".join(conditions)
    sql = f"""
        SELECT digest_date, kind, title, body, source_inputs, alerts,
               generated_at, telegram_sent_at
        FROM daily_digest
        WHERE {where}
        ORDER BY digest_date DESC, generated_at DESC
    """
    return _serialize(_fetch(sql, tuple(params)))


def query_digest_for_date(digest_date: str, kind: str | None = None) -> list[dict]:
    """All digests for a specific date (YYYY-MM-DD), optionally filtered by kind."""
    conditions = ["digest_date = %s"]
    params: list = [digest_date]
    if kind:
        conditions.append("kind = %s")
        params.append(kind)
    where = " AND ".join(conditions)
    sql = f"""
        SELECT digest_date, kind, title, body, source_inputs, alerts,
               generated_at, telegram_sent_at
        FROM daily_digest
        WHERE {where}
        ORDER BY generated_at DESC
    """
    return _serialize(_fetch(sql, tuple(params)))


# ── Data Status ────────────────────────────────────────────────────────────

def query_valuation(
    ticker_id: str | None = None,
    pillar: str | None = None,
    max_pe: float | None = None,
    max_pb: float | None = None,
    min_yield: float | None = None,
    top_n: int = 30,
) -> list[dict]:
    """Latest P/E, P/B, dividend yield from raw_twse_valuation joined with
    dim_ticker for pillar/node context.

    Filters compose AND-style: pillar='semiconductor' + max_pe=20 returns
    only semi names trading below P/E 20. NULL pe_ratio means the issuer
    has no positive earnings — those rows are excluded by max_pe filter.
    """
    where = ["v.date = (SELECT MAX(date) FROM raw_twse_valuation)"]
    params: list = []
    if ticker_id:
        where.append("v.ticker_id = %s")
        params.append(ticker_id)
    if pillar:
        where.append("dt.ai_pillar = %s")
        params.append(pillar)
    if max_pe is not None:
        where.append("v.pe_ratio IS NOT NULL AND v.pe_ratio <= %s")
        params.append(max_pe)
    if max_pb is not None:
        where.append("v.pb_ratio IS NOT NULL AND v.pb_ratio <= %s")
        params.append(max_pb)
    if min_yield is not None:
        where.append("v.dividend_yield >= %s")
        params.append(min_yield)
    params.append(int(top_n))

    sql = f"""
        SELECT v.ticker_id, v.company_name, dt.ai_pillar, dt.node,
               v.close, v.dividend_yield, v.dividend_year,
               v.pe_ratio, v.pb_ratio, v.fiscal_period, v.date
          FROM raw_twse_valuation v
          LEFT JOIN dim_ticker dt ON dt.ticker_id = v.ticker_id
         WHERE {' AND '.join(where)}
         ORDER BY v.pb_ratio NULLS LAST, v.pe_ratio NULLS LAST
         LIMIT %s
    """
    return _serialize(_fetch(sql, tuple(params)))


def query_index_history(
    index_name: str | None = None,
    days: int = 30,
) -> list[dict]:
    """Recent close + change for a given sector / cross-market index, or
    a one-day snapshot of all indices if index_name is None."""
    if index_name:
        sql = """
            SELECT date, index_name, close, change_pts, change_pct, direction
              FROM raw_twse_index
             WHERE index_name = %s
             ORDER BY date DESC LIMIT %s
        """
        return _serialize(_fetch(sql, (index_name, int(days))))
    sql = """
        SELECT date, index_name, close, change_pts, change_pct, direction
          FROM raw_twse_index
         WHERE date = (SELECT MAX(date) FROM raw_twse_index)
         ORDER BY index_name
    """
    return _serialize(_fetch(sql))


def query_lead_lag(
    upstream: str | None = None,
    downstream: str | None = None,
    min_corr: float = 0.4,
    min_gain: float = 0.0,
    top_n: int = 20,
) -> list[dict]:
    """Forward-lag pairs from the latest snapshot.

    Returns rows where the upstream's returns at day t correlate with the
    downstream's returns at day t+lag (lag > 0). `min_corr` filters absolute
    forward correlation; `min_gain` filters how much the forward correlation
    beats the same-day baseline. Sorted by gain descending.
    """
    where = ["forward.lag_days BETWEEN 1 AND 7",
             "forward.correlation >= %s",
             "(forward.correlation - coincident.correlation) >= %s",
             "forward.asof = (SELECT MAX(asof) FROM lead_lag)"]
    params: list = [min_corr, min_gain]
    if upstream:
        where.append("forward.upstream_id = %s")
        params.append(upstream)
    if downstream:
        where.append("forward.downstream_id = %s")
        params.append(downstream)
    params.append(int(top_n))

    sql = f"""
        WITH coincident AS (
            SELECT upstream_id, downstream_id, correlation
              FROM lead_lag
             WHERE lag_days = 0
               AND asof = (SELECT MAX(asof) FROM lead_lag)
        )
        SELECT forward.upstream_id,
               up.company_name AS upstream_name, up.ai_pillar AS upstream_pillar,
               forward.downstream_id,
               down.company_name AS downstream_name, down.ai_pillar AS downstream_pillar,
               forward.lag_days,
               ROUND(forward.correlation::numeric, 3) AS rho_lag,
               ROUND(coincident.correlation::numeric, 3) AS rho_0,
               ROUND((forward.correlation - coincident.correlation)::numeric, 3) AS gain,
               forward.n_obs, forward.window_days, forward.asof
          FROM lead_lag forward
          JOIN coincident USING (upstream_id, downstream_id)
          LEFT JOIN dim_ticker up   ON up.ticker_id   = forward.upstream_id
          LEFT JOIN dim_ticker down ON down.ticker_id = forward.downstream_id
         WHERE {' AND '.join(where)}
         ORDER BY gain DESC, forward.correlation DESC
         LIMIT %s
    """
    return _serialize(_fetch(sql, tuple(params)))


def query_momentum_leaders(
    as_of: str,
    rs_window: int = 60,
    markets: list[str] | None = None,
    min_turnover_twd: int = 30_000_000,
) -> list[dict]:
    """Per-ticker trend aggregation for `momentum_leaders_scan`.

    One SQL pass computing everything the pure scorer in
    ``momentum_leaders.score_row`` needs: 50/200-day means and their prior
    values (so "rising" is measurable), the 3-month high, a 20-day volume
    ratio, ATR(14), a recent swing low, relative strength versus TAIEX over
    `rs_window`, institutional flow over the same window, and the length of the
    consolidation preceding the current leg.

    UNIVERSE — narrower than flow_leaders', and unavoidably so. That scan can
    read price from ``raw_twse_valuation`` (~1.1k TWSE names, close only), but
    momentum needs HIGH, LOW and VOLUME for ATR, the breakout test and the
    climax guard. Only ``raw_twse_ohlcv`` carries those, and it is a top-500
    harvest. So this reads the OHLCV set and requires ~200 sessions of history
    for the 200-day mean, leaving a few hundred scoreable names. Small caps
    outside that harvest cannot be scored at all rather than being scored
    badly — see the `universe` note the tool returns.

    Relative strength is return-vs-TAIEX over `rs_window`, percentile-ranked
    across the scoreable set with PERCENT_RANK, so `rs_percentile` means "beat
    this share of the measurable market" and not "beat this share of everything
    listed". The distinction matters when reading a 96th percentile.

    Flow comes from ``raw_twse_t86`` (all-market) like every other scanner
    here, summed over `rs_window` so "institutions bought WITH the trend" is
    measured over the same window the trend is.
    """
    mkts = markets or ["TWSE", "TPEX"]
    sql = """
        WITH px AS (
          SELECT ticker_id, date, open, high, low, close, volume_shares, turnover_twd,
                 ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
          FROM raw_twse_ohlcv
          WHERE date <= %(d)s AND close IS NOT NULL AND close > 0
        ),
        -- Enough history for the 200-day mean; anything shorter cannot have a
        -- trend structure and is dropped rather than scored on a partial mean.
        eligible AS (
          SELECT ticker_id FROM px GROUP BY ticker_id HAVING COUNT(*) >= 200
        ),
        latest AS (
          SELECT ticker_id, close, high, low, turnover_twd
          FROM px WHERE rn = 1
        ),
        mas AS (
          SELECT ticker_id,
                 AVG(close) FILTER (WHERE rn <= 50)                AS ma_50,
                 AVG(close) FILTER (WHERE rn BETWEEN 6 AND 55)     AS ma_50_prev,
                 AVG(close) FILTER (WHERE rn <= 200)               AS ma_200,
                 AVG(close) FILTER (WHERE rn BETWEEN 6 AND 205)    AS ma_200_prev,
                 MAX(close) FILTER (WHERE rn <= 63)                AS high_3m,
                 MIN(low)   FILTER (WHERE rn <= 20)                AS recent_swing_low,
                 AVG(volume_shares) FILTER (WHERE rn BETWEEN 2 AND 21) AS avg_vol_20,
                 MAX(volume_shares) FILTER (WHERE rn = 1)          AS vol_today
          FROM px GROUP BY ticker_id
        ),
        -- ATR(14) as the mean true range. The full Wilder smoothing needs a
        -- recursive seed; over 14 sessions the simple mean is within a rounding
        -- error of it and is one aggregate rather than a window function chain.
        tr AS (
          SELECT ticker_id,
                 GREATEST(high - low,
                          ABS(high - LAG(close) OVER (PARTITION BY ticker_id ORDER BY date)),
                          ABS(low  - LAG(close) OVER (PARTITION BY ticker_id ORDER BY date))) AS true_range,
                 ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
          FROM px WHERE rn <= 30
        ),
        atr AS (
          SELECT ticker_id, AVG(true_range) AS atr_14
          FROM tr WHERE rn <= 14 GROUP BY ticker_id
        ),
        -- Return over the RS window, and the same for TAIEX, so relative
        -- strength is a difference of two returns over identical dates.
        rets AS (
          SELECT p.ticker_id,
                 (MAX(p.close) FILTER (WHERE p.rn = 1)
                  / NULLIF(MAX(p.close) FILTER (WHERE p.rn = %(w)s), 0) - 1) * 100 AS ret_pct
          FROM px p WHERE p.rn <= %(w)s GROUP BY p.ticker_id
        ),
        taiex AS (
          SELECT (MAX(close) FILTER (WHERE rn = 1)
                  / NULLIF(MAX(close) FILTER (WHERE rn = %(w)s), 0) - 1) * 100 AS ret_pct
          FROM (
            SELECT close, ROW_NUMBER() OVER (ORDER BY date DESC) AS rn
            FROM raw_twse_index
            WHERE index_name = '發行量加權股價指數' AND date <= %(d)s
          ) t WHERE rn <= %(w)s
        ),
        flow AS (
          SELECT ticker_id,
                 SUM(foreign_net) AS foreign_trend_net,
                 SUM(trust_net)   AS trust_trend_net
          FROM (
            SELECT ticker_id, foreign_net, trust_net,
                   ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
            FROM raw_twse_t86 WHERE date <= %(d)s
          ) f WHERE rn <= %(w)s GROUP BY ticker_id
        ),
        -- The consolidation before the current leg: how many of the sessions
        -- before the last 5 sat inside a +/-5% band. Vertical-from-nothing
        -- scores 0 here and trips the no_base guard.
        base AS (
          SELECT ticker_id,
                 COUNT(*) FILTER (
                   WHERE ABS(close / NULLIF(band.med, 0) - 1) <= 0.05
                 ) AS base_days_before_leg
          FROM px
          JOIN LATERAL (
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p2.close) AS med
            FROM px p2
            WHERE p2.ticker_id = px.ticker_id AND p2.rn BETWEEN 6 AND 40
          ) band ON true
          WHERE px.rn BETWEEN 6 AND 40
          GROUP BY ticker_id
        )
        SELECT dt.ticker_id, dt.company_name AS name, dt.market,
               l.close, l.high, l.low,
               m.ma_50, m.ma_50_prev, m.ma_200, m.ma_200_prev,
               m.high_3m, m.recent_swing_low,
               CASE WHEN m.avg_vol_20 > 0
                    THEN m.vol_today::float / m.avg_vol_20 END AS volume_ratio_20,
               a.atr_14,
               r.ret_pct AS trend_return_pct,
               r.ret_pct - x.ret_pct AS rs_vs_taiex_pct,
               PERCENT_RANK() OVER (ORDER BY r.ret_pct - x.ret_pct) * 100 AS rs_percentile,
               f.foreign_trend_net, f.trust_trend_net,
               b.base_days_before_leg,
               val.pe_ratio, val.pb_ratio,
               rev.yoy_pct AS rev_yoy_pct, rev.yoy_pct_prev AS rev_yoy_pct_prev
          FROM eligible e
          JOIN latest l USING (ticker_id)
          JOIN mas m USING (ticker_id)
          JOIN rets r USING (ticker_id)
          JOIN dim_ticker dt USING (ticker_id)
          CROSS JOIN taiex x
          LEFT JOIN atr a USING (ticker_id)
          LEFT JOIN flow f USING (ticker_id)
          LEFT JOIN base b USING (ticker_id)
          LEFT JOIN LATERAL (
            SELECT pe_ratio, pb_ratio FROM raw_twse_valuation v
            WHERE v.ticker_id = e.ticker_id AND v.date <= %(d)s
            ORDER BY v.date DESC LIMIT 1
          ) val ON true
          LEFT JOIN LATERAL (
            SELECT MAX(yoy_pct) FILTER (WHERE rn = 1) AS yoy_pct,
                   MAX(yoy_pct) FILTER (WHERE rn = 2) AS yoy_pct_prev
            FROM (
              SELECT yoy_pct, ROW_NUMBER() OVER (ORDER BY ym DESC) AS rn
              FROM raw_monthly_revenue rm WHERE rm.ticker_id = e.ticker_id
            ) rr WHERE rn <= 2
          ) rev ON true
         WHERE dt.market = ANY(%(mkts)s)
           AND COALESCE(l.turnover_twd, 0) >= %(min_to)s
    """
    return _serialize(_fetch(sql, {
        "d": as_of, "w": int(rs_window), "mkts": mkts,
        "min_to": int(min_turnover_twd),
    }))


def query_macro(series: str | None = None, days: int = 30) -> list[dict]:
    """Macro series rows, newest first.

    `series` is matched with a parameter, never interpolated — the column is
    free text written by the harvester, so it is data, not an identifier, and
    query_safety.safe_flow_col does not apply here.

    Dates are US-session dates in UTC (see src/harvester/macro._utc_date), NOT
    Taiwan trading dates. A caller joining this to a TWSE date must decide what
    "the same day" means; the tool docstring says so out loud.
    """
    days = max(1, min(int(days), 365))
    sql = """
        SELECT date, series, close, prev_close, pct_change, source, ingested_at
          FROM raw_macro
         WHERE (%s::text IS NULL OR series = %s)
           AND date >= (CURRENT_DATE - %s::int)
         ORDER BY date DESC, series
    """
    return _serialize(_fetch(sql, (series, series, days)))


def query_macro_latest() -> list[dict]:
    """The most recent row per series — what the pre-market brief needs.

    DISTINCT ON rather than a MAX(date) subquery join: series publish on
    different calendars (FRED skips US holidays, FX trades through them), so a
    single global MAX would silently drop whichever series lagged by a day.
    """
    sql = """
        SELECT DISTINCT ON (series)
               date, series, close, prev_close, pct_change, source, ingested_at
          FROM raw_macro
         ORDER BY series, date DESC
    """
    return _serialize(_fetch(sql))


def query_data_status() -> dict:
    table_names = [
        "raw_twse_t86", "raw_twse_holdings", "raw_twse_margin",
        "raw_twse_ohlcv", "raw_monthly_revenue", "dim_ticker",
        # Without this line raw_macro is invisible in sc_data_status AND in the
        # operator console overview (console_pages renders exactly this list),
        # so a macro harvest that silently stopped would look like nothing at all.
        "raw_macro",
    ]
    # Use pg_stat_user_tables for O(1) approximate counts instead of full scans.
    # Stats lag slightly behind ANALYZE; that's fine for a status endpoint.
    stat_rows = _fetch(
        "SELECT relname, n_live_tup FROM pg_stat_user_tables "
        "WHERE relname = ANY(%s)",
        (table_names,),
    )
    counts_by_name = {r["relname"]: int(r["n_live_tup"] or 0) for r in stat_rows}
    tables = {t: counts_by_name.get(t, 0) for t in table_names}

    # Latest ingestion
    latest = _fetch("""
        SELECT source, target_date, rows_upserted, status, finished_at
        FROM ingestion_log
        ORDER BY finished_at DESC
        LIMIT 5
    """)

    # Latest T86 date
    t86_latest = _fetch("SELECT MAX(date) AS latest FROM raw_twse_t86")
    latest_date = t86_latest[0]["latest"] if t86_latest else None

    return _serialize([{
        "table_counts": tables,
        "latest_t86_date": latest_date,
        "recent_ingestions": latest,
    }])[0]
