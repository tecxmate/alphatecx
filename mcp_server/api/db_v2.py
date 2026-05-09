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


def query_screener(
    rsi_below: Optional[float] = None,
    rsi_above: Optional[float] = None,
    macd_hist_above: Optional[float] = None,
    above_sma_200: Optional[bool] = None,
    rs_above: Optional[float] = None,
    foreign_z_above: Optional[float] = None,
    pct_below_52w_high_above: Optional[float] = None,
) -> list[dict]:
    """Screen latest signals across all classified tickers.

    Combines conditions with AND. Joins view_latest_signals with
    raw_twse_ohlcv to expose latest close + dim_supply_chain for pillar/node.
    """
    conditions: list[str] = []
    params: list = []

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
    if foreign_z_above is not None:
        conditions.append("ls.foreign_net_z20 > %s")
        params.append(foreign_z_above)
    if pct_below_52w_high_above is not None:
        # Stored as a negative or zero number; "above" a threshold like -5
        # means "within 5% of the high" (i.e. closer to high than -5%).
        conditions.append("ls.pct_below_52w_high > %s")
        params.append(pct_below_52w_high_above)

    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""
        SELECT ls.ticker_id, sc.company_name, sc.ai_pillar, sc.node,
               o.close AS latest_close, ls.as_of,
               ls.rsi_14, ls.macd_histogram, ls.bb_pct_b,
               ls.sma_50, ls.sma_200, ls.rs_vs_market_60,
               ls.pct_below_52w_high, ls.foreign_net_z20,
               ls.foreign_net_5d_sum, ls.total_net_z20
        FROM view_latest_signals ls
        JOIN dim_supply_chain sc ON sc.ticker_id = ls.ticker_id
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
    source: Optional[str] = None,
    lang: Optional[str] = None,
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
    reason: Optional[str] = None,
    escalation_trigger: Optional[str] = None,
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
    """Archive a watchlist entry (status='archived'). Idempotent: re-runs
    on already-archived rows are a no-op."""
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE watchlist SET status = 'archived', updated_at = now() "
                "WHERE ticker_id = %s AND status = 'active' "
                "RETURNING company_name",
                (ticker_id,),
            )
            row = cur.fetchone()
            conn.commit()
    if not row:
        return {"ok": False, "ticker_id": ticker_id,
                "error": "not on active watchlist"}
    return {"ok": True, "ticker_id": ticker_id, "company": row[0],
            "status": "archived"}


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

def query_digest_recent(days: int = 3, kind: Optional[str] = None) -> list[dict]:
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


def query_digest_for_date(digest_date: str, kind: Optional[str] = None) -> list[dict]:
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

def query_lead_lag(
    upstream: Optional[str] = None,
    downstream: Optional[str] = None,
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


def query_data_status() -> dict:
    table_names = [
        "raw_twse_t86", "raw_twse_holdings", "raw_twse_margin",
        "raw_twse_ohlcv", "raw_monthly_revenue", "dim_ticker",
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
