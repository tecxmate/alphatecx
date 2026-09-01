"""Intraday stop watcher — live quotes against Risk Guard's stop lines.

Runs inside the news poller's loop (`src.news.watch`), not as its own service:
the poller already wakes every ~180s with DB access and Telegram plumbing, so
the stop check rides the same heartbeat instead of costing a fourth Zeabur
service. Everything institutional-flow is structurally end-of-day (T86
publishes once, ~15:00), so *price against a stop line* is the one signal in
this system that genuinely exists intraday — before this, a stop breached at
09:47 was discovered at the 15:00 post-close pass.

Composition, all existing pieces:
  riskguard.store          active_positions / record_alert / find_alert /
                           mark_pushed — same write-first + dedup contract as
                           the post-close pipeline
  mcp_server.api.rg.stops  the PURE breach logic (warn/exit lines, cost-based
                           fallback). Reused, not copied: this repo's mirrored
                           quant files show exactly how duplicated semantics
                           drift. Only the *message* differs intraday.
  src.alerts.telegram      send(category="alerts")

The Fugle client here is deliberately thin — GET one symbol, return lastPrice.
The full client (5-level book, limit-band tick math) stays in
mcp_server/api/fugle.py where its `limit_board` dependency lives; importing it
from the worker would drag the server tree's import graph into this image for
one float.

Honesty constraint, stated in every alert: an intraday last price is NOT the
official close. The post-close pipeline stays the authoritative verdict; this
watcher exists so the operator can look four hours sooner, not so the system
starts judging stops on ticks. Alert kinds are prefixed `intraday_` so the
post-close `stop_exit` / `stop_warn` still fire as their own alerts.

Self-disables cleanly: no FUGLE_API_KEY → one INFO line per process, no work.
QUOTE_WATCH_ENABLED=false switches it off explicitly.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

import requests

from src.alerts.telegram import send

log = logging.getLogger("quote_watch")

_TPE = ZoneInfo("Asia/Taipei")

# TWSE continuous session 09:00–13:30 plus a tail for the closing auction print
# to settle. Outside this window the check is a no-op costing nothing.
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(13, 35)

FUGLE_QUOTE_URL = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
REQUEST_TIMEOUT = 10

# One line per process about why nothing is happening, not one per cycle.
_disabled_reason_logged = False

# Holiday answer cached per date: the market_holidays table changes yearly,
# polling it every 180s would be noise. {date: is_trading_day}
_holiday_cache: dict[date, bool] = {}


def enabled() -> bool:
    global _disabled_reason_logged
    if os.getenv("QUOTE_WATCH_ENABLED", "true").strip().lower() in (
        "false", "0", "no", "off",
    ):
        if not _disabled_reason_logged:
            log.info("quote watch disabled (QUOTE_WATCH_ENABLED=false)")
            _disabled_reason_logged = True
        return False
    if not os.getenv("FUGLE_API_KEY"):
        if not _disabled_reason_logged:
            log.info("quote watch idle — FUGLE_API_KEY is not set")
            _disabled_reason_logged = True
        return False
    return True


def _is_trading_day(today: date) -> bool:
    """market_holidays lookup, cached per date, failing OPEN to weekday-only.

    Mirrors session_state's degraded mode: if the table is unreachable the
    watcher behaves as if every weekday trades. The cost of that failure is a
    few wasted quote calls on a holiday; the cost of failing closed would be a
    silent watcher on every day the DB blinked at 09:00.
    """
    if today in _holiday_cache:
        return _holiday_cache[today]
    trading = today.weekday() < 5
    if trading:
        try:
            from src.harvester.loader import cur
            with cur() as c:
                c.execute(
                    "SELECT 1 FROM market_holidays WHERE holiday_date = %s", (today,)
                )
                trading = c.fetchone() is None
        except Exception:
            log.warning("market_holidays unreachable — assuming weekday trades")
    _holiday_cache.clear()          # never grows past one entry
    _holiday_cache[today] = trading
    return trading


def market_open_now(now: datetime | None = None) -> bool:
    now = now or datetime.now(_TPE)
    if not MARKET_OPEN <= now.time() <= MARKET_CLOSE:
        return False
    return _is_trading_day(now.date())


def fetch_last_price(symbol: str, key: str) -> float | None:
    """Last traded price for one symbol, or None. Never raises.

    None must stay indistinguishable from "no quote" downstream:
    stops.evaluate skips tickers absent from the price map, so a Fugle blip
    degrades to "not checked this cycle", never to a false breach.
    """
    try:
        resp = requests.get(
            FUGLE_QUOTE_URL.format(symbol=symbol),
            headers={"X-API-KEY": key},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            log.warning("fugle %s -> HTTP %s", symbol, resp.status_code)
            return None
        raw = resp.json().get("lastPrice")
        return float(raw) if raw is not None else None
    except Exception as e:
        log.warning("fugle %s failed: %s", symbol, e)
        return None


def _format(alert: dict) -> str:
    """Intraday wording — cannot reuse rg's `action` text, which says 明天開盤
    because the post-close verdict arrives after the session. Intraday the
    point is: the line is broken NOW, while the market is still open."""
    name = f" {alert['name']}" if alert.get("name") else ""
    line_kind = "出場線" if alert["kind"] == "stop_exit" else "警戒線"
    fallback = "（依成本−停損%推算）" if alert.get("line_is_fallback") else ""
    return (
        f"⏱️ <b>盤中警報</b> {alert['ticker_id']}{name}\n"
        f"現價 {alert['close']} 已跌破{line_kind} {alert['line']}{fallback} "
        f"({alert['distance_pct']:+.1f}%)\n"
        f"市場尚未收盤 — 這是盤中價,不是收盤判定。收盤後 Risk Guard 會再確認。"
    )


def check_once(now: datetime | None = None) -> int:
    """One pass: positions → live quotes → breach check → alert. Returns the
    number of alerts *sent* this pass. Never raises past its own boundary."""
    if not enabled() or not market_open_now(now):
        return 0

    # Imported here, not at module top: riskguard/mcp_server come along in the
    # worker image for this feature, but the news poller must keep starting
    # even if a future image change drops them — the same never-kill-the-loop
    # rule the poller itself lives by.
    from mcp_server.api.rg import stops
    from riskguard import store

    key = os.environ["FUGLE_API_KEY"]
    positions = [p for p in store.active_positions() if p.get("kind") == "position"]
    if not positions:
        return 0

    quotes = {}
    for pos in positions:
        price = fetch_last_price(pos["ticker_id"], key)
        if price is not None:
            quotes[pos["ticker_id"]] = price

    sent = 0
    for alert in stops.evaluate(positions, quotes):
        kind = f"intraday_{alert['kind']}"          # distinct from post-close kinds
        message = _format(alert)
        # Same write-first contract as pipeline._emit: record, and if an
        # identical (date, kind, ticker) alert exists, resend ONLY if the
        # earlier attempt never delivered. One buzz per line per day.
        alert_id = store.record_alert(
            kind, alert["severity"], message,
            ticker_id=alert["ticker_id"],
            payload={k: v for k, v in alert.items() if k != "action"},
        )
        if alert_id is None:
            existing = store.find_alert(kind, alert["ticker_id"])
            if existing and not existing["pushed"]:
                if send(existing["message"], category="alerts"):
                    store.mark_pushed(existing["id"])
                    sent += 1
            continue
        if send(message, category="alerts"):
            store.mark_pushed(alert_id)
            sent += 1
    return sent
