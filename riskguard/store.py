"""DB reads and writes for the Risk Guard cron side.

Assembles the M1 metric bundle from the market-data tables the harvester
already fills (raw_twse_index, raw_twse_margin) plus the two feeds Risk Guard
adds itself (breadth, TAIFEX). Writes go to rg_* only — this module never
touches the ingestion tables.

Uses src.harvester.loader's pool so the cron process holds one Neon connection
pool, not two.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from src.harvester.loader import cur

log = logging.getLogger("riskguard.store")

TAIEX = "發行量加權股價指數"


# ── M1 inputs ───────────────────────────────────────────────────────────────

def taiex_series(as_of: str, limit: int = 70) -> list[dict]:
    """TAIEX closes up to and including `as_of`, newest first.

    `limit` defaults to 70 so a 60-day MA still has room when the index table
    has gaps — raw_twse_index is only as complete as the harvest that filled it.
    """
    with cur() as c:
        c.execute(
            "SELECT date, close, change_pct FROM raw_twse_index "
            " WHERE index_name = %s AND date <= %s "
            " ORDER BY date DESC LIMIT %s",
            (TAIEX, as_of, limit),
        )
        return [{"date": r[0].isoformat(),
                 "close": float(r[1]) if r[1] is not None else None,
                 "change_pct": float(r[2]) if r[2] is not None else None}
                for r in c.fetchall()]


def margin_totals(as_of: str, limit: int = 10) -> list[dict]:
    """Whole-market margin balance per date, newest first.

    Summed from the per-stock MI_MARGN rows the harvester already stores, so
    this needs no new feed. Dates with partial ingestion will read low; the
    growth comparison is between two stored dates, which limits the damage.
    """
    with cur() as c:
        c.execute(
            "SELECT date, SUM(margin_balance) FROM raw_twse_margin "
            " WHERE date <= %s GROUP BY date ORDER BY date DESC LIMIT %s",
            (as_of, limit),
        )
        return [{"date": r[0].isoformat(), "margin_balance": float(r[1] or 0)}
                for r in c.fetchall()]


def breadth_history(as_of: str, limit: int = 5) -> list[dict]:
    """Stored advance/decline counts, newest first, up to and including `as_of`.

    Read back out of rg_market_daily rather than re-fetched: the 5-day mean
    needs four earlier sessions, and re-pulling them from TWSE on every run
    would be four extra rate-limited requests a day for data already held.
    """
    with cur() as c:
        c.execute(
            "SELECT date, adv_count, dec_count FROM rg_market_daily "
            " WHERE date <= %s AND adv_count IS NOT NULL "
            " ORDER BY date DESC LIMIT %s",
            (as_of, limit),
        )
        return [{"date": r[0].isoformat(), "adv_count": r[1], "dec_count": r[2]}
                for r in c.fetchall()]


def _pct_change(newest: float | None, older: float | None) -> float | None:
    if not newest or not older:
        return None
    return round((newest / older - 1) * 100, 3)


def _fut_change(series: dict | None, as_of: str, window: int) -> tuple:
    """(net OI on `as_of`, change vs `window` sessions earlier).

    Both None when the series does not reach back far enough — subitem 4 then
    reports data_missing rather than scoring a change it could not measure.
    """
    if not series:
        return None, None
    days = sorted(d for d in series if d <= as_of)
    if not days or days[-1] != as_of:
        return None, None
    level = series[as_of]
    if len(days) <= window:
        return level, None
    return level, level - series[days[-1 - window]]


def build_metrics(as_of: str, breadth_today: dict | None,
                  fut_series: dict | None = None,
                  breadth_prior: list[dict] | None = None) -> dict:
    """Assemble the M1 metric bundle for one session.

    Any component that is absent stays absent — scoring.score_day marks the
    corresponding subitem data_missing rather than substituting a neutral value,
    because a neutral substitute reads as "calm" and calm is the dangerous
    default for a system whose job is to warn.
    """
    from mcp_server.api.rg import config as cfg

    fut_level, fut_chg = _fut_change(fut_series, as_of, cfg.FUT_CHANGE_WINDOW)
    series = taiex_series(as_of)
    today = series[0] if series and series[0]["date"] == as_of else None
    closes = [r["close"] for r in series if r["close"] is not None]

    ma20 = (round(sum(closes[:cfg.MA_SHORT]) / cfg.MA_SHORT, 2)
            if len(closes) >= cfg.MA_SHORT else None)
    ma60 = (round(sum(closes[:cfg.MA_LONG]) / cfg.MA_LONG, 2)
            if len(closes) >= cfg.MA_LONG else None)
    ret_5d = _pct_change(closes[0], closes[5]) if len(closes) > 5 else None

    # Breadth: today's fresh counts, then the four sessions before it.
    #
    # `breadth_prior` lets a caller supply that history instead of reading it
    # back from rg_market_daily. The replay needs it: running without --write
    # leaves the table empty, so the "5-day mean" silently collapses to today's
    # single ratio — which scores far more bearishly and made report-only and
    # --write disagree about the same session. A calibration harness whose
    # answer depends on whether it saved is worse than no harness.
    history = breadth_prior if breadth_prior is not None else breadth_history(as_of)
    history = [r for r in history if r["date"] != as_of]
    counts = ([breadth_today] if breadth_today else []) + history
    counts = counts[:cfg.BREADTH_WINDOW]
    ratios = [
        r["adv_count"] / (r["adv_count"] + r["dec_count"])
        for r in counts
        if r and (r.get("adv_count") or 0) + (r.get("dec_count") or 0) > 0
    ]
    adv_ratio_5d = round(sum(ratios) / len(ratios), 4) if ratios else None

    # Margin only counts if it is actually *this* session's. `margin_totals`
    # returns the latest rows on or before `as_of`, so a stalled harvest would
    # otherwise hand June's balance to a July session and score it as current —
    # silently, since a stale number looks exactly like a fresh one.
    margins = margin_totals(as_of)
    fresh = bool(margins) and margins[0]["date"] == as_of
    margin_balance = margins[0]["margin_balance"] if fresh else None
    margin_chg = (_pct_change(margins[0]["margin_balance"],
                              margins[cfg.MARGIN_WINDOW]["margin_balance"])
                  if fresh and len(margins) > cfg.MARGIN_WINDOW else None)

    return {
        "date": as_of,
        "taiex_close": today["close"] if today else (closes[0] if closes else None),
        "taiex_pct": today["change_pct"] if today else None,
        "ma20": ma20,
        "ma60": ma60,
        "taiex_ret_5d_pct": ret_5d,
        "adv_count": breadth_today.get("adv_count") if breadth_today else None,
        "dec_count": breadth_today.get("dec_count") if breadth_today else None,
        "adv_ratio_5d": adv_ratio_5d,
        "margin_balance": margin_balance,
        "margin_chg_5d_pct": margin_chg,
        "fut_foreign_net_oi": fut_level,
        "fut_net_oi_chg_5d": fut_chg,
        "_closes": closes,          # for light.build_index_context
    }


# ── M1 output ───────────────────────────────────────────────────────────────

def prev_market_day(as_of: str) -> dict | None:
    with cur() as c:
        c.execute(
            "SELECT date, risk_light, risk_score FROM rg_market_daily "
            " WHERE date < %s ORDER BY date DESC LIMIT 1",
            (as_of,),
        )
        r = c.fetchone()
    return {"date": r[0].isoformat(), "risk_light": r[1], "risk_score": r[2]} if r else None


def upsert_market_daily(metrics: dict, light: str, score: int, reasons: list[dict]) -> None:
    with cur() as c:
        c.execute(
            """
            INSERT INTO rg_market_daily
                (date, taiex_close, taiex_pct, taiex_ma20, taiex_ma60,
                 taiex_ret_5d_pct, adv_count, dec_count, adv_ratio_5d,
                 margin_balance, margin_chg_5d_pct, fut_foreign_net_oi,
                 risk_light, risk_score, reasons, computed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
            ON CONFLICT (date) DO UPDATE SET
                taiex_close = EXCLUDED.taiex_close,
                taiex_pct = EXCLUDED.taiex_pct,
                taiex_ma20 = EXCLUDED.taiex_ma20,
                taiex_ma60 = EXCLUDED.taiex_ma60,
                taiex_ret_5d_pct = EXCLUDED.taiex_ret_5d_pct,
                adv_count = EXCLUDED.adv_count,
                dec_count = EXCLUDED.dec_count,
                adv_ratio_5d = EXCLUDED.adv_ratio_5d,
                margin_balance = EXCLUDED.margin_balance,
                margin_chg_5d_pct = EXCLUDED.margin_chg_5d_pct,
                fut_foreign_net_oi = EXCLUDED.fut_foreign_net_oi,
                risk_light = EXCLUDED.risk_light,
                risk_score = EXCLUDED.risk_score,
                reasons = EXCLUDED.reasons,
                computed_at = now()
            """,
            (metrics["date"], metrics["taiex_close"], metrics["taiex_pct"],
             metrics["ma20"], metrics["ma60"], metrics["taiex_ret_5d_pct"],
             metrics["adv_count"], metrics["dec_count"], metrics["adv_ratio_5d"],
             metrics["margin_balance"], metrics["margin_chg_5d_pct"],
             metrics["fut_foreign_net_oi"], light, score,
             json.dumps(reasons, ensure_ascii=False)),
        )


# ── Alerts ──────────────────────────────────────────────────────────────────

def record_alert(kind: str, severity: str, message: str,
                 ticker_id: str | None = None,
                 payload: dict | None = None,
                 date_iso: str | None = None,
                 dedup_key: str | None = None) -> int | None:
    """Persist an alert before sending it. Returns the row id, or None if an
    identical (date, kind, dedup_key) alert already exists.

    Written first, pushed second, so a Telegram outage costs the send and not
    the record — and the unique index makes a pipeline re-run silent instead of
    a second buzz on the operator's phone.

    `dedup_key` defaults to the ticker. Ticker-less alerts must pass their own —
    two settlement shortfalls on different dates are two alerts, not one.
    """
    with cur() as c:
        c.execute(
            "INSERT INTO rg_alerts (date, kind, ticker_id, dedup_key, severity, "
            "                       payload, message) "
            "VALUES (COALESCE(%s::date, (now() AT TIME ZONE 'Asia/Taipei')::date), "
            "        %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (date_iso, kind, ticker_id, dedup_key or ticker_id or "",
             severity, json.dumps(payload or {}, ensure_ascii=False), message),
        )
        row = c.fetchone()
    return row[0] if row else None


def mark_pushed(alert_id: int) -> None:
    with cur() as c:
        c.execute("UPDATE rg_alerts SET pushed = TRUE, pushed_at = now() WHERE id = %s",
                  (alert_id,))


def unpushed_critical(limit: int = 20, days: int = 3) -> list[dict]:
    """Critical alerts recorded but never delivered (PRD §6 補發).

    Bounded to the last few days on purpose: a stop breached two weeks ago is
    stale advice, and re-sending it would be noise dressed as an emergency.
    Anything older stays in the table as a record and is never pushed.
    """
    with cur() as c:
        c.execute(
            "SELECT id, message FROM rg_alerts "
            " WHERE NOT pushed AND severity = 'critical' "
            "   AND ts >= now() - make_interval(days => %s) "
            " ORDER BY id LIMIT %s",
            (int(days), int(limit)),
        )
        return [{"id": r[0], "message": r[1]} for r in c.fetchall()]


# ── Monitored names ─────────────────────────────────────────────────────────

def active_positions() -> list[dict]:
    with cur() as c:
        c.execute(
            "SELECT ticker_id, name, kind, cost, qty_lots, warn_price, exit_price, "
            "       hard_stop_pct, note, active FROM rg_positions WHERE active "
            " ORDER BY kind, ticker_id"
        )
        cols = [d.name for d in c.description]
        rows = [dict(zip(cols, r, strict=True)) for r in c.fetchall()]
    for r in rows:
        for k in ("cost", "qty_lots", "warn_price", "exit_price", "hard_stop_pct"):
            if r[k] is not None:
                r[k] = float(r[k])
    return rows


def closes_for(ticker_ids: list[str], as_of: str) -> dict[str, float]:
    """Official closes on or before `as_of`, one per ticker."""
    if not ticker_ids:
        return {}
    with cur() as c:
        c.execute(
            "SELECT DISTINCT ON (ticker_id) ticker_id, close FROM raw_twse_ohlcv "
            " WHERE ticker_id = ANY(%s) AND date <= %s "
            " ORDER BY ticker_id, date DESC",
            (list(ticker_ids), as_of),
        )
        return {r[0]: float(r[1]) for r in c.fetchall() if r[1] is not None}


# ── M5 groundwork ───────────────────────────────────────────────────────────

def snapshot_held_pct(as_of: str) -> int:
    """Copy today's foreign holding % for monitored names into rg_*.

    Phase 1 does nothing with this. It exists now because the Phase 3 intent
    score needs a 20-day slope, and history cannot be backfilled from a table
    that is only ever overwritten.
    """
    with cur() as c:
        c.execute(
            "INSERT INTO rg_foreign_holdings_daily (date, ticker_id, held_pct) "
            "SELECT h.date, h.ticker_id, h.foreign_held_pct "
            "  FROM raw_twse_holdings h "
            "  JOIN rg_positions p ON p.ticker_id = h.ticker_id AND p.active "
            " WHERE h.date = %s "
            "ON CONFLICT (date, ticker_id) DO UPDATE SET held_pct = EXCLUDED.held_pct",
            (as_of,),
        )
        return c.rowcount


# ── M2b ─────────────────────────────────────────────────────────────────────

def trading_days(start: str, end: str) -> list[str]:
    with cur() as c:
        c.execute(
            "SELECT d::date FROM generate_series(%s::date, %s::date, '1 day') d "
            " WHERE EXTRACT(ISODOW FROM d) < 6 "
            "   AND NOT EXISTS (SELECT 1 FROM market_holidays h "
            "                    WHERE h.cal_date = d::date AND h.is_closed) "
            " ORDER BY d",
            (start, end),
        )
        return [r[0].isoformat() for r in c.fetchall()]


def record_trade(trade_date: str, settle: str, ticker_id: str, side: str,
                 price: float, lots: float, net_amount: float,
                 note: str | None = None) -> None:
    """Log a fill and fold it into that settlement date's net amount."""
    with cur() as c:
        c.execute(
            "INSERT INTO rg_trades (trade_date, settle_date, ticker_id, side, "
            "                       price, lots, net_amount, note) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (trade_date, settle, ticker_id, side, price, lots, net_amount, note),
        )
        c.execute(
            "INSERT INTO rg_settlements (date, net_amount) VALUES (%s, %s) "
            "ON CONFLICT (date) DO UPDATE SET "
            "  net_amount = rg_settlements.net_amount + EXCLUDED.net_amount, "
            "  updated_at = now()",
            (settle, net_amount),
        )


def settlement_schedule(today: str) -> list[dict]:
    with cur() as c:
        c.execute(
            "SELECT date, net_amount FROM rg_settlements WHERE date >= %s "
            " ORDER BY date LIMIT 10",
            (today,),
        )
        return [{"date": r[0].isoformat(), "net_amount": float(r[1])} for r in c.fetchall()]


def record_balance(amount: float, note: str | None = None) -> None:
    with cur() as c:
        c.execute("INSERT INTO rg_balances (amount, note) VALUES (%s, %s)", (amount, note))


def latest_balance() -> float | None:
    with cur() as c:
        c.execute("SELECT amount FROM rg_balances ORDER BY ts DESC LIMIT 1")
        r = c.fetchone()
    return float(r[0]) if r else None


# ── M7 ──────────────────────────────────────────────────────────────────────

def set_no_trade_day(date_iso: str, reason: str) -> None:
    with cur() as c:
        c.execute(
            "INSERT INTO rg_no_trade_days (date, reason) VALUES (%s, %s) "
            "ON CONFLICT (date) DO UPDATE SET reason = EXCLUDED.reason",
            (date_iso, reason),
        )


def no_trade_reason(date_iso: str) -> str | None:
    with cur() as c:
        c.execute("SELECT reason FROM rg_no_trade_days WHERE date = %s", (date_iso,))
        r = c.fetchone()
    return r[0] if r else None


# ── Positions ───────────────────────────────────────────────────────────────

def upsert_position(ticker_id: str, **fields) -> None:
    """Insert or patch one monitored name. Only the fields given are touched,
    so `/setpos 2344 exit=47.8` cannot silently blank a cost set earlier."""
    allowed = {"name", "kind", "cost", "qty_lots", "warn_price",
               "exit_price", "hard_stop_pct", "note", "active"}
    patch = {k: v for k, v in fields.items() if k in allowed and v is not None}

    cols = ["ticker_id"] + list(patch)
    placeholders = ", ".join(["%s"] * len(cols))
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in patch) or "updated_at = now()"
    sql = (f"INSERT INTO rg_positions ({', '.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT (ticker_id) DO UPDATE SET {updates}, updated_at = now()")
    with cur() as c:
        c.execute(sql, [ticker_id] + list(patch.values()))


def last_trading_day(as_of: str | None = None) -> str:
    """Most recent date with TAIEX data, on or before `as_of`.

    Anchoring on data rather than the calendar means a holiday, a typhoon day,
    and a late TWSE publish all resolve the same way instead of each needing
    their own branch.
    """
    as_of = as_of or date.today().isoformat()
    with cur() as c:
        c.execute(
            "SELECT MAX(date) FROM raw_twse_index WHERE index_name = %s AND date <= %s",
            (TAIEX, as_of),
        )
        r = c.fetchone()
    if r and r[0]:
        return r[0].isoformat()
    return (date.fromisoformat(as_of) - timedelta(days=1)).isoformat()
