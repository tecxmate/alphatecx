"""Neon Postgres loader — upserts Polars DataFrames into Neon tables.

Uses psycopg3 connection pool (same pattern as alphatecx v1).
All writes use ON CONFLICT DO UPDATE so backfill and daily runs are idempotent.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from psycopg_pool import ConnectionPool

from src.config import DATABASE_URL

_TPE = ZoneInfo("Asia/Taipei")

log = logging.getLogger("loader")

_pool: ConnectionPool | None = None


def _configure(conn):
    """Run on each new connection. Neon's pooler clears session settings on
    reset and rejects `options=-csearch_path` at startup, so we set it here."""
    with conn.cursor() as c:
        c.execute("SET search_path TO public, neon_auth")
    conn.commit()


def pool() -> ConnectionPool:
    """Lazy singleton connection pool.

    Note: GitHub Actions runners advertise IPv6 but the path is dead.
    The CI workflow pins the Neon pooler hostname to IPv4 in /etc/hosts
    so glibc's getaddrinfo returns only the IPv4 address — no Python-
    side DSN tweaking needed.
    """
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set in .env")
        _pool = ConnectionPool(
            DATABASE_URL, min_size=0, max_size=4, open=True,
            configure=_configure,
        )
    return _pool


@contextmanager
def cur():
    """Yield a cursor with auto-commit."""
    with pool().connection() as conn:
        conn.autocommit = True
        with conn.cursor() as c:
            yield c


@contextmanager
def atomic():
    """Yield a cursor inside a single transaction.

    Use when an upsert and its `log_ingestion` row must commit together —
    otherwise a mid-batch crash leaves a partially-written day marked
    'ok' in ingestion_log, and `get_ingested_dates` skips it on retry.
    """
    with pool().connection() as conn:
        conn.autocommit = False
        try:
            with conn.cursor() as c:
                yield c
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _df_to_records(df: pl.DataFrame) -> list[dict]:
    """Convert Polars DataFrame to list of dicts, serializing dates."""
    records = df.to_dicts()
    for rec in records:
        for k, v in rec.items():
            if hasattr(v, "isoformat"):
                rec[k] = v.isoformat()
    return records


@contextmanager
def _cursor_or_default(c):
    """Use the passed-in cursor if given; otherwise open an autocommit one."""
    if c is not None:
        yield c
    else:
        with cur() as c2:
            yield c2


def _save_local(df: pl.DataFrame, table: str, partition_col: str | None = None):
    """Save a local parquet copy of the dataframe."""
    base_dir = Path("data") / table
    base_dir.mkdir(parents=True, exist_ok=True)
    
    if partition_col and partition_col in df.columns:
        date_val = df[partition_col][0]
        date_str = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)
        out_path = base_dir / f"{date_str}.parquet"
    else:
        out_path = base_dir / "latest.parquet"
        
    df.write_parquet(out_path)

# ── Upsert functions ────────────────────────────────────────────────────────

def upsert_t86(df: pl.DataFrame, c=None) -> int:
    """Upsert T86 institutional flow data."""
    if df.is_empty():
        return 0
    _save_local(df, "raw_twse_t86", "date")
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
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_t86", len(records))
    return len(records)


def upsert_holdings(df: pl.DataFrame, c=None) -> int:
    """Upsert foreign holdings data."""
    if df.is_empty():
        return 0
    _save_local(df, "raw_twse_holdings", "date")
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
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_holdings", len(records))
    return len(records)


def upsert_margin(df: pl.DataFrame, c=None) -> int:
    """Upsert margin balance data."""
    if df.is_empty():
        return 0
    _save_local(df, "raw_twse_margin", "date")
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
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_margin", len(records))
    return len(records)


def upsert_ohlcv(df: pl.DataFrame, c=None) -> int:
    """Upsert OHLCV daily bars."""
    if df.is_empty():
        return 0
    _save_local(df, "raw_twse_ohlcv", "date")
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
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_ohlcv", len(records))
    return len(records)


def upsert_revenue(df: pl.DataFrame, c=None) -> int:
    """Upsert monthly revenue data."""
    if df.is_empty():
        return 0
    _save_local(df, "raw_monthly_revenue", "ym")
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
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, records)
    log.info("Upserted %d rows into raw_monthly_revenue", len(records))
    return len(records)


def upsert_supply_chain(df: pl.DataFrame, c=None) -> int:
    """Upsert ticker rows into the universe table (dim_ticker).

    Only fills company_name and market — does NOT overwrite existing
    ai_pillar/node classifications, which are manually curated and surface
    via the dim_supply_chain view. Function name kept for backwards
    compatibility with backfill/run.py and harvester/daily.py callers.
    """
    if df.is_empty():
        return 0
    _save_local(df, "dim_ticker")
    records = _df_to_records(df)
    sql = """
        INSERT INTO dim_ticker (ticker_id, company_name, market)
        VALUES (%(ticker_id)s, %(company_name)s, %(market)s)
        ON CONFLICT (ticker_id) DO UPDATE SET
            company_name = COALESCE(NULLIF(EXCLUDED.company_name, ''),
                                    dim_ticker.company_name),
            updated_at = now()
    """
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, records)
    log.info("Upserted %d tickers into dim_ticker", len(records))
    return len(records)


# ── Ingestion log ───────────────────────────────────────────────────────────

def log_ingestion(source: str, target_date: str | None, rows: int,
                  status: str = "ok", error_msg: str | None = None,
                  c=None) -> None:
    """Log an ingestion event. Pass `c` to commit atomically with an upsert."""
    sql = """
        INSERT INTO ingestion_log (source, target_date, rows_upserted,
                                    status, error_msg, finished_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    with _cursor_or_default(c) as cc:
        cc.execute(sql, (source, target_date, rows, status, error_msg,
                         datetime.now(_TPE).isoformat()))


def refresh_views() -> None:
    """Refresh the materialized views."""
    with cur() as c:
        c.execute("SELECT refresh_momentum_views()")
    log.info("Materialized views refreshed")


def get_ingested_dates(source: str) -> set[str]:
    """Dates to skip on retry: successes, plus empties on days the market was
    genuinely shut. Errors are never skipped.

    The calendar check is the whole point. `empty` used to mean two very
    different things — "the market was closed" and "the source had not
    published yet" — and both were skipped forever. TWSE releases
    融資融券彙總 after the 16:30 harvest window, so every trading day from
    ~2026-07-01 logged `empty`, was treated as a confirmed holiday, and could
    never be retried: `--only margin` reported "29 skipped, 0 rows" against an
    empty table while the endpoint served the data fine. A failure that records
    itself as a success is the worst kind, because nothing downstream can tell
    it happened.

    An empty on a real trading day is now retryable. Re-fetching a genuinely
    dead day costs one request that returns nothing.
    """
    sql = """
        SELECT target_date FROM ingestion_log
         WHERE source = %s
           AND (
                status = 'ok'
             OR (status = 'empty' AND (
                    EXTRACT(ISODOW FROM target_date) >= 6
                 OR EXISTS (SELECT 1 FROM market_holidays h
                             WHERE h.cal_date = target_date AND h.is_closed)
                ))
           )
    """
    with cur() as c:
        c.execute(sql, (source,))
        rows = c.fetchall()
    return {str(r[0]) for r in rows if r[0]}


def margin_sessions_missing(days: int = 10) -> list[str]:
    """Recent trading sessions with no rows in raw_twse_margin, oldest first.

    Keyed off the data itself rather than ingestion_log, so it repairs the gap
    whatever caused it — a late publish, a transient 500, or a log row that
    lied. `raw_twse_index` supplies the trading calendar: a session TWSE
    published an index for is a session that traded.
    """
    sql = """
        SELECT i.date
          FROM (SELECT DISTINCT date FROM raw_twse_index
                 ORDER BY date DESC LIMIT %s) i
         WHERE NOT EXISTS (SELECT 1 FROM raw_twse_margin m WHERE m.date = i.date)
         ORDER BY i.date
    """
    with cur() as c:
        c.execute(sql, (int(days),))
        return [r[0].isoformat() for r in c.fetchall()]


# ── Schema management ──────────────────────────────────────────────────────

def execute_sql_file(filepath: str) -> None:
    """Execute a SQL file against the database."""
    from pathlib import Path
    sql = Path(filepath).read_text()
    with cur() as c:
        c.execute(sql)
    log.info("Executed SQL file: %s", filepath)


def upsert_valuation(df: pl.DataFrame, c=None) -> int:
    """Upsert per-ticker P/E, P/B, dividend-yield (BWIBBU_d)."""
    if df.is_empty():
        return 0
    _save_local(df, "raw_twse_valuation", "date")
    records = _df_to_records(df)
    sql = """
        INSERT INTO raw_twse_valuation (date, ticker_id, company_name, market,
            close, dividend_yield, dividend_year, pe_ratio, pb_ratio, fiscal_period)
        VALUES (%(date)s, %(ticker_id)s, %(company_name)s, %(market)s,
                %(close)s, %(dividend_yield)s, %(dividend_year)s, %(pe_ratio)s,
                %(pb_ratio)s, %(fiscal_period)s)
        ON CONFLICT (date, ticker_id) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            close = EXCLUDED.close,
            dividend_yield = EXCLUDED.dividend_yield,
            dividend_year = EXCLUDED.dividend_year,
            pe_ratio = EXCLUDED.pe_ratio,
            pb_ratio = EXCLUDED.pb_ratio,
            fiscal_period = EXCLUDED.fiscal_period,
            ingested_at = now()
    """
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_valuation", len(records))
    return len(records)


def upsert_indices(df: pl.DataFrame, c=None) -> int:
    """Upsert sector / cross-market indices (MI_INDEX type=IND)."""
    if df.is_empty():
        return 0
    _save_local(df, "raw_twse_index", "date")
    records = _df_to_records(df)
    sql = """
        INSERT INTO raw_twse_index (date, index_name, close, change_pts, change_pct, direction)
        VALUES (%(date)s, %(index_name)s, %(close)s, %(change_pts)s, %(change_pct)s, %(direction)s)
        ON CONFLICT (date, index_name) DO UPDATE SET
            close = EXCLUDED.close,
            change_pts = EXCLUDED.change_pts,
            change_pct = EXCLUDED.change_pct,
            direction = EXCLUDED.direction,
            ingested_at = now()
    """
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, records)
    log.info("Upserted %d rows into raw_twse_index", len(records))
    return len(records)


def upsert_dividends(rows: list[dict], c=None) -> int:
    """Upsert ex-dividend/ex-rights rows (list of dicts, not a DataFrame).

    A later 'actual' (TWT49U) row for a date must overwrite the earlier
    'forecast' (TWT48U) placeholder; the reverse must not happen. So a forecast
    upsert leaves an existing actual row untouched.
    """
    if not rows:
        return 0
    sql = """
        INSERT INTO raw_twse_dividend (ex_date, ticker_id, name, ex_type,
            cash_value, pre_ex_close, reference_price, status, source)
        VALUES (%(ex_date)s, %(ticker_id)s, %(name)s, %(ex_type)s,
            %(cash_value)s, %(pre_ex_close)s, %(reference_price)s,
            %(status)s, 'twse')
        ON CONFLICT (ex_date, ticker_id) DO UPDATE SET
            name = EXCLUDED.name,
            ex_type = EXCLUDED.ex_type,
            cash_value = EXCLUDED.cash_value,
            pre_ex_close = COALESCE(EXCLUDED.pre_ex_close, raw_twse_dividend.pre_ex_close),
            reference_price = COALESCE(EXCLUDED.reference_price, raw_twse_dividend.reference_price),
            status = EXCLUDED.status,
            ingested_at = now()
        WHERE raw_twse_dividend.status <> 'actual' OR EXCLUDED.status = 'actual'
    """
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, rows)
    log.info("Upserted %d rows into raw_twse_dividend", len(rows))
    return len(rows)


def upsert_market_holidays(rows: list[dict], c=None) -> int:
    """Upsert market-calendar rows (list of dicts, not a DataFrame).

    A TWSE-sourced re-harvest must not clobber a `source='manual'` typhoon row
    someone inserted by hand — the schedule endpoint never knows about those.
    So an incoming `twse` row leaves an existing `manual` row for the same date
    untouched; every other conflict updates in place.
    """
    if not rows:
        return 0
    sql = """
        INSERT INTO market_holidays (cal_date, name, is_closed, note, source)
        VALUES (%(cal_date)s, %(name)s, %(is_closed)s, %(note)s, %(source)s)
        ON CONFLICT (cal_date) DO UPDATE SET
            name = EXCLUDED.name,
            is_closed = EXCLUDED.is_closed,
            note = EXCLUDED.note,
            source = EXCLUDED.source,
            ingested_at = now()
        WHERE market_holidays.source <> 'manual' OR EXCLUDED.source = 'manual'
    """
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, rows)
    log.info("Upserted %d rows into market_holidays", len(rows))
    return len(rows)


def upsert_finmind_dividend(rows: list[dict], c=None) -> int:
    """Upsert FinMind dividend-policy rows (cash/stock split per fiscal year)."""
    if not rows:
        return 0
    sql = """
        INSERT INTO raw_finmind_dividend (ticker_id, year, cash_dividend,
            stock_dividend, cash_ex_date, stock_ex_date, announcement_date)
        VALUES (%(ticker_id)s, %(year)s, %(cash_dividend)s, %(stock_dividend)s,
            %(cash_ex_date)s, %(stock_ex_date)s, %(announcement_date)s)
        ON CONFLICT (ticker_id, year) DO UPDATE SET
            cash_dividend = EXCLUDED.cash_dividend,
            stock_dividend = EXCLUDED.stock_dividend,
            cash_ex_date = EXCLUDED.cash_ex_date,
            stock_ex_date = EXCLUDED.stock_ex_date,
            announcement_date = EXCLUDED.announcement_date,
            ingested_at = now()
    """
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, rows)
    log.info("Upserted %d rows into raw_finmind_dividend", len(rows))
    return len(rows)


def upsert_finmind_dividend_result(rows: list[dict], c=None) -> int:
    """Upsert FinMind dividend-result rows (per-ex before/after/max prices)."""
    if not rows:
        return 0
    sql = """
        INSERT INTO raw_finmind_dividend_result (ticker_id, ex_date, before_price,
            after_price, reference_price, max_price, min_price)
        VALUES (%(ticker_id)s, %(ex_date)s, %(before_price)s, %(after_price)s,
            %(reference_price)s, %(max_price)s, %(min_price)s)
        ON CONFLICT (ticker_id, ex_date) DO UPDATE SET
            before_price = EXCLUDED.before_price,
            after_price = EXCLUDED.after_price,
            reference_price = EXCLUDED.reference_price,
            max_price = EXCLUDED.max_price,
            min_price = EXCLUDED.min_price,
            ingested_at = now()
    """
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, rows)
    log.info("Upserted %d rows into raw_finmind_dividend_result", len(rows))
    return len(rows)


def upsert_finmind_fill_stats(rows: list[dict], c=None) -> int:
    """Upsert precomputed 填息 stats (one row per ticker)."""
    if not rows:
        return 0
    sql = """
        INSERT INTO finmind_fill_stats (ticker_id, fill_probability_5y,
            events_5y, last_ex_date, computed_as_of)
        VALUES (%(ticker_id)s, %(fill_probability_5y)s, %(events_5y)s,
            %(last_ex_date)s, %(computed_as_of)s)
        ON CONFLICT (ticker_id) DO UPDATE SET
            fill_probability_5y = EXCLUDED.fill_probability_5y,
            events_5y = EXCLUDED.events_5y,
            last_ex_date = EXCLUDED.last_ex_date,
            computed_as_of = EXCLUDED.computed_as_of,
            ingested_at = now()
    """
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, rows)
    log.info("Upserted %d rows into finmind_fill_stats", len(rows))
    return len(rows)


def upsert_finmind_news(rows: list[dict], c=None) -> int:
    """Upsert FinMind news rows (stable title_hash PK; governance flag precomputed)."""
    if not rows:
        return 0
    sql = """
        INSERT INTO raw_finmind_news (ticker_id, news_date, title, title_hash,
            news_source, url, is_governance)
        VALUES (%(ticker_id)s, %(news_date)s, %(title)s, %(title_hash)s,
            %(news_source)s, %(url)s, %(is_governance)s)
        ON CONFLICT (ticker_id, news_date, title_hash) DO UPDATE SET
            news_source = EXCLUDED.news_source,
            url = EXCLUDED.url,
            is_governance = EXCLUDED.is_governance,
            ingested_at = now()
    """
    with _cursor_or_default(c) as cc:
        cc.executemany(sql, rows)
    log.info("Upserted %d rows into raw_finmind_news", len(rows))
    return len(rows)
