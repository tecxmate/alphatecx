"""Risk Guard read layer for the MCP tools (PRD §6 介面三).

Thin by design: every rg_* tool except rg_journal_add is a read with no side
effects, so the Claude conversation, the Telegram bot, and the dashboard all
answer from one row of truth rather than three recomputations that can disagree.

Reuses db_v2's connection pool instead of opening a second one — the Vercel
function is a single process and Neon's pooler charges for every connection.
"""
from __future__ import annotations

try:
    import db_v2
except ModuleNotFoundError:  # package import path used by local tests
    from .. import db_v2  # type: ignore

_fetch = db_v2._fetch
_serialize = db_v2._serialize


# ── M1 ──────────────────────────────────────────────────────────────────────

def latest_market_daily() -> dict | None:
    rows = _serialize(_fetch(
        "SELECT * FROM rg_market_daily ORDER BY date DESC LIMIT 1"
    ))
    return rows[0] if rows else None


def market_daily_range(days: int = 10) -> list[dict]:
    return _serialize(_fetch(
        "SELECT date, taiex_close, taiex_pct, risk_light, risk_score "
        "FROM rg_market_daily ORDER BY date DESC LIMIT %s",
        (int(days),),
    ))


# ── M2 ──────────────────────────────────────────────────────────────────────

def positions(include_inactive: bool = False) -> list[dict]:
    sql = ("SELECT ticker_id, name, kind, cost, qty_lots, warn_price, exit_price, "
           "       hard_stop_pct, note, active "
           "  FROM rg_positions ")
    if not include_inactive:
        sql += " WHERE active "
    sql += " ORDER BY kind, ticker_id"
    return _serialize(_fetch(sql))


def latest_closes(ticker_ids: list[str]) -> dict[str, float]:
    """Most recent official close per ticker from the harvested OHLCV table.

    DISTINCT ON is the cheap way to get "latest row per ticker" on Postgres and
    keeps this a single round trip regardless of list length.
    """
    if not ticker_ids:
        return {}
    rows = _fetch(
        "SELECT DISTINCT ON (ticker_id) ticker_id, close "
        "  FROM raw_twse_ohlcv WHERE ticker_id = ANY(%s) "
        " ORDER BY ticker_id, date DESC",
        (list(ticker_ids),),
    )
    return {r["ticker_id"]: float(r["close"]) for r in rows if r["close"] is not None}


def gain_5d_pct(ticker_id: str) -> float | None:
    """Trailing 5-session return, the input to checklist Q3."""
    rows = _fetch(
        "SELECT close FROM raw_twse_ohlcv WHERE ticker_id = %s "
        " ORDER BY date DESC LIMIT 6",
        (ticker_id,),
    )
    closes = [float(r["close"]) for r in rows if r["close"] is not None]
    if len(closes) < 6 or not closes[5]:
        return None
    return round((closes[0] / closes[5] - 1) * 100, 2)


# ── Alerts ──────────────────────────────────────────────────────────────────

def recent_alerts(days: int = 3) -> list[dict]:
    return _serialize(_fetch(
        "SELECT id, ts, date, kind, ticker_id, dedup_key, severity, payload, "
        "       message, pushed "
        "  FROM rg_alerts WHERE ts >= now() - make_interval(days => %s) "
        " ORDER BY ts DESC LIMIT 100",
        (int(days),),
    ))


# ── M2b ─────────────────────────────────────────────────────────────────────

def settlement_schedule(today: str) -> list[dict]:
    return _serialize(_fetch(
        "SELECT date, net_amount, note FROM rg_settlements "
        " WHERE date >= %s ORDER BY date LIMIT 10",
        (today,),
    ))


def latest_balance() -> dict | None:
    rows = _serialize(_fetch(
        "SELECT amount, ts FROM rg_balances ORDER BY ts DESC LIMIT 1"
    ))
    return rows[0] if rows else None


# ── M7 ──────────────────────────────────────────────────────────────────────

def no_trade_reason(date_iso: str) -> str | None:
    """Checklist Q5 input. This is the only read of rg_no_trade_days in the
    whole system — it must never reach a scoring path (PRD §5 M7)."""
    rows = _fetch("SELECT reason FROM rg_no_trade_days WHERE date = %s", (date_iso,))
    return rows[0]["reason"] if rows else None


def trading_days(start: str, end: str) -> list[str]:
    """Ascending ISO trading dates in [start, end], excluding weekends and
    anything market_holidays marks closed. Used for the T+2 settlement walk."""
    rows = _fetch(
        "SELECT d::date AS cal_date FROM generate_series(%s::date, %s::date, '1 day') d "
        " WHERE EXTRACT(ISODOW FROM d) < 6 "
        "   AND NOT EXISTS (SELECT 1 FROM market_holidays h "
        "                    WHERE h.cal_date = d::date AND h.is_closed) "
        " ORDER BY d",
        (start, end),
    )
    return [r["cal_date"].isoformat() for r in rows]


# ── Journal (the one write) ─────────────────────────────────────────────────

def journal_add(text: str, ticker_id: str | None = None) -> dict:
    """Append a decision to the journal. Returns the new row id.

    Needs INSERT on rg_journal for the mcp_viewer role — granted in
    sql/018_riskguard.sql, same precedent as watchlist / w_add.
    """
    with db_v2.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO rg_journal (text, ticker_id) VALUES (%s, %s) "
                "RETURNING id, ts",
                (text, ticker_id),
            )
            row = cur.fetchone()
        conn.commit()
    return {"id": row[0], "ts": row[1].isoformat(), "text": text, "ticker_id": ticker_id}


def journal_recent(limit: int = 20) -> list[dict]:
    return _serialize(_fetch(
        "SELECT id, ts, text, ticker_id FROM rg_journal ORDER BY ts DESC LIMIT %s",
        (int(limit),),
    ))


# ── Composite: everything the checklist needs in one place ──────────────────

def checklist_facts(
    ticker_id: str,
    today: str,
    buy_amount: float | None = None,
    available_cash: float | None = None,
) -> dict:
    """Gather checklist inputs. Unavailable modules stay None so the checklist
    reports them as skipped rather than inventing a pass or a fail."""
    market = latest_market_daily()
    rows = _fetch(
        "SELECT name, note, active FROM rg_positions WHERE ticker_id = %s",
        (ticker_id,),
    )
    pos = rows[0] if rows else {}
    note = pos.get("note") or ""

    name = pos.get("name")
    if not name:
        lookup = _fetch(
            "SELECT company_name FROM dim_ticker WHERE ticker_id = %s LIMIT 1",
            (ticker_id,),
        )
        name = lookup[0]["company_name"] if lookup else None

    if available_cash is None:
        bal = latest_balance()
        available_cash = float(bal["amount"]) if bal else None

    return {
        "ticker_id": ticker_id,
        "name": name,
        "risk_light": market.get("risk_light") if market else None,
        "sector_rank": None,          # M3 — Phase 2
        "gain_5d_pct": gain_5d_pct(ticker_id),
        "is_disposition": None,       # M6 — Phase 4
        "no_trade_reason": no_trade_reason(today),
        "buy_amount": buy_amount,
        "available_cash": available_cash,
        "blacklisted": "拉黑" in note,
        "blacklist_note": note or None,
    }
