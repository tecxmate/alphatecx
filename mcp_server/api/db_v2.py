"""Database queries for the v2 MCP server.

All queries target materialized views or read-only tables.
Uses psycopg3 connection pool (same as alphatecx v1).
"""
from __future__ import annotations

import os
from typing import Optional

from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv("MCP_DATABASE_URL") or os.getenv("DATABASE_URL", "")
_pool: ConnectionPool | None = None

# Whitelisted column identifiers that may be interpolated into SQL.
# Anything outside this set gets rejected — no f-string identifier ever reaches
# the database without passing through here.
_ALLOWED_FLOW_COLS = frozenset({
    "foreign_1d", "foreign_3d", "foreign_5d", "foreign_10d", "foreign_20d",
    "total_1d", "total_3d", "total_5d", "total_10d", "total_20d",
    "consecutive_foreign_buy_days",
})


def _safe_col(col: str, default: str) -> str:
    return col if col in _ALLOWED_FLOW_COLS else default


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
            return [dict(zip(cols, row)) for row in cur.fetchall()]


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
    pillar: Optional[str] = None,
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
    pillar: Optional[str] = None,
    node: Optional[str] = None,
    ticker_id: Optional[str] = None,
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


# ── Supply Chain Map ───────────────────────────────────────────────────────

def query_supply_chain(
    pillar: Optional[str] = None,
    node: Optional[str] = None,
    search: Optional[str] = None,
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


# ── Data Status ────────────────────────────────────────────────────────────

def query_data_status() -> dict:
    table_names = [
        "raw_twse_t86", "raw_twse_holdings", "raw_twse_margin",
        "raw_twse_ohlcv", "raw_monthly_revenue", "dim_supply_chain",
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
