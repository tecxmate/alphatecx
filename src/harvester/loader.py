"""Neon Postgres loader — upserts Polars DataFrames into Neon tables.

Uses psycopg3 connection pool (same pattern as alphatecx v1).
All writes use ON CONFLICT DO UPDATE so backfill and daily runs are idempotent.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import polars as pl
from psycopg_pool import ConnectionPool

from src.config import DATABASE_URL

log = logging.getLogger("loader")

_pool: Optional[ConnectionPool] = None


def pool() -> ConnectionPool:
    """Lazy singleton connection pool."""
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set in .env")
        _pool = ConnectionPool(DATABASE_URL, min_size=0, max_size=4, open=True)
    return _pool


@contextmanager
def cur():
    """Yield a cursor with auto-commit."""
    with pool().connection() as conn:
        conn.autocommit = True
        with conn.cursor() as c:
            yield c


def _df_to_records(df: pl.DataFrame) -> list[dict]:
    """Convert Polars DataFrame to list of dicts, serializing dates."""
    records = df.to_dicts()
    for rec in records:
        for k, v in rec.items():
            if hasattr(v, "isoformat"):
                rec[k] = v.isoformat()
    return records


# ── Upsert functions ────────────────────────────────────────────────────────

def upsert_t86(df: pl.DataFrame) -> int:
    """Upsert T86 institutional flow data."""
    if df.is_empty():
        return 0
    records = _df_to_records(df)
    sql = """
        INSERT INTO raw_twse_t86 (date, ticker_id, company_name, market,
                                   foreign_net, trust_net, dealer_net, total_net)
        VALUES (%(date)s, %(ticker_id)s, %(company_name)s, %(market)s,
                %(foreign_net)s, %(trust_net)s, %(dealer_net)s, %(total_net)s)
        ON CONFLICT (date, ticker_id) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            market = EXCLUDED.market,
            foreign_net = EXCLUDED.foreign_net,
            trust_net = EXCLUDED.trust_net,
            dealer_net = EXCLUDED.dealer_net,
            total_net = EXCLUDED.total_net,
            ingested_at = now()
    """
    with cur() as c:
        c.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_t86", len(records))
    return len(records)


def upsert_holdings(df: pl.DataFrame) -> int:
    """Upsert foreign holdings data."""
    if df.is_empty():
        return 0
    records = _df_to_records(df)
    sql = """
        INSERT INTO raw_twse_holdings (date, ticker_id, company_name, market,
                                        shares_outstanding, foreign_held_shares,
                                        foreign_held_pct, foreign_room_pct)
        VALUES (%(date)s, %(ticker_id)s, %(company_name)s, %(market)s,
                %(shares_outstanding)s, %(foreign_held_shares)s,
                %(foreign_held_pct)s, %(foreign_room_pct)s)
        ON CONFLICT (date, ticker_id) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            shares_outstanding = EXCLUDED.shares_outstanding,
            foreign_held_shares = EXCLUDED.foreign_held_shares,
            foreign_held_pct = EXCLUDED.foreign_held_pct,
            foreign_room_pct = EXCLUDED.foreign_room_pct,
            ingested_at = now()
    """
    with cur() as c:
        c.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_holdings", len(records))
    return len(records)


def upsert_margin(df: pl.DataFrame) -> int:
    """Upsert margin balance data."""
    if df.is_empty():
        return 0
    records = _df_to_records(df)
    sql = """
        INSERT INTO raw_twse_margin (date, ticker_id, company_name, market,
                                      margin_balance, margin_change, margin_limit,
                                      short_balance, short_change, short_limit)
        VALUES (%(date)s, %(ticker_id)s, %(company_name)s, %(market)s,
                %(margin_balance)s, %(margin_change)s, %(margin_limit)s,
                %(short_balance)s, %(short_change)s, %(short_limit)s)
        ON CONFLICT (date, ticker_id) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            margin_balance = EXCLUDED.margin_balance,
            margin_change = EXCLUDED.margin_change,
            margin_limit = EXCLUDED.margin_limit,
            short_balance = EXCLUDED.short_balance,
            short_change = EXCLUDED.short_change,
            short_limit = EXCLUDED.short_limit,
            ingested_at = now()
    """
    with cur() as c:
        c.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_margin", len(records))
    return len(records)


def upsert_ohlcv(df: pl.DataFrame) -> int:
    """Upsert OHLCV daily bars."""
    if df.is_empty():
        return 0
    records = _df_to_records(df)
    sql = """
        INSERT INTO raw_twse_ohlcv (date, ticker_id, market,
                                     open, high, low, close,
                                     volume_shares, turnover_twd)
        VALUES (%(date)s, %(ticker_id)s, %(market)s,
                %(open)s, %(high)s, %(low)s, %(close)s,
                %(volume_shares)s, %(turnover_twd)s)
        ON CONFLICT (date, ticker_id) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high,
            low = EXCLUDED.low, close = EXCLUDED.close,
            volume_shares = EXCLUDED.volume_shares,
            turnover_twd = EXCLUDED.turnover_twd,
            ingested_at = now()
    """
    with cur() as c:
        c.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_ohlcv", len(records))
    return len(records)


def upsert_revenue(df: pl.DataFrame) -> int:
    """Upsert monthly revenue data."""
    if df.is_empty():
        return 0
    records = _df_to_records(df)
    sql = """
        INSERT INTO raw_monthly_revenue (ym, ticker_id, company_name, market,
                                          industry, revenue_k_twd, mom_pct,
                                          yoy_pct, ytd_revenue, ytd_prev_year,
                                          ytd_yoy_pct)
        VALUES (%(ym)s, %(ticker_id)s, %(company_name)s, %(market)s,
                %(industry)s, %(revenue_k_twd)s, %(mom_pct)s,
                %(yoy_pct)s, %(ytd_revenue)s, %(ytd_prev_year)s,
                %(ytd_yoy_pct)s)
        ON CONFLICT (ym, ticker_id) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            revenue_k_twd = EXCLUDED.revenue_k_twd,
            mom_pct = EXCLUDED.mom_pct,
            yoy_pct = EXCLUDED.yoy_pct,
            ytd_revenue = EXCLUDED.ytd_revenue,
            ytd_prev_year = EXCLUDED.ytd_prev_year,
            ytd_yoy_pct = EXCLUDED.ytd_yoy_pct,
            ingested_at = now()
    """
    with cur() as c:
        c.executemany(sql, records)
    log.info("Upserted %d rows into raw_monthly_revenue", len(records))
    return len(records)


def upsert_supply_chain(df: pl.DataFrame) -> int:
    """Upsert ticker mappings into dim_supply_chain.

    Only updates company_name and market — does NOT overwrite existing
    ai_pillar/node classifications (those are manually curated).
    """
    if df.is_empty():
        return 0
    records = _df_to_records(df)
    sql = """
        INSERT INTO dim_supply_chain (ticker_id, company_name, market)
        VALUES (%(ticker_id)s, %(company_name)s, %(market)s)
        ON CONFLICT (ticker_id) DO UPDATE SET
            company_name = COALESCE(NULLIF(EXCLUDED.company_name, ''),
                                    dim_supply_chain.company_name),
            updated_at = now()
    """
    with cur() as c:
        c.executemany(sql, records)
    log.info("Upserted %d tickers into dim_supply_chain", len(records))
    return len(records)


# ── Ingestion log ───────────────────────────────────────────────────────────

def log_ingestion(source: str, target_date: Optional[str], rows: int,
                  status: str = "ok", error_msg: Optional[str] = None) -> None:
    """Log an ingestion event."""
    sql = """
        INSERT INTO ingestion_log (source, target_date, rows_upserted,
                                    status, error_msg, finished_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    with cur() as c:
        c.execute(sql, (source, target_date, rows, status, error_msg,
                        datetime.utcnow().isoformat()))


def refresh_views() -> None:
    """Refresh the materialized views."""
    with cur() as c:
        c.execute("SELECT refresh_momentum_views()")
    log.info("Materialized views refreshed")


def get_ingested_dates(source: str) -> set[str]:
    """Get all dates already ingested for a given source (for gap detection)."""
    sql = """
        SELECT target_date FROM ingestion_log
        WHERE source = %s AND status = 'ok'
    """
    with cur() as c:
        c.execute(sql, (source,))
        rows = c.fetchall()
    return {str(r[0]) for r in rows if r[0]}


# ── Schema management ──────────────────────────────────────────────────────

def execute_sql_file(filepath: str) -> None:
    """Execute a SQL file against the database."""
    from pathlib import Path
    sql = Path(filepath).read_text()
    with cur() as c:
        c.execute(sql)
    log.info("Executed SQL file: %s", filepath)
