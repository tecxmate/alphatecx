"""Telegram push notifications.

Ported from alphatecx v1 (core/telegram.py). Sends daily harvest summaries
and sector momentum alerts.
"""

from __future__ import annotations

import logging

import requests

from src.config import (
    TELEGRAM_CHAT_ID,
    TELEGRAM_TOKEN,
    telegram_category_enabled,
    telegram_configured,
    telegram_enabled,
)

log = logging.getLogger("telegram")


def send(message: str, category: str = "alerts") -> bool:
    """Send a Telegram message. Returns whether it was actually delivered.

    `category` is one of config.TELEGRAM_CATEGORIES; the default is "alerts"
    because that is the send whose loss hurts most — an uncategorised new call
    site should be silenceable only by the master flag or the alerts flag,
    never accidentally quieter than that.

    Two non-delivery cases, deliberately logged differently. Switched off is
    routine and logs at INFO; a missing or malformed token is a system that
    believes it is alerting and is not, so it stays a WARNING. Collapsing the
    two is what let a broken token hide for weeks.
    """
    if not telegram_enabled():
        log.info("Telegram disabled (TELEGRAM_ENABLED=false); not sending")
        return False
    if not telegram_category_enabled(category):
        log.info("Telegram %s category switched off; not sending", category)
        return False
    if not telegram_configured():
        log.warning("Telegram not configured, printing instead:\n%s", message)
        print(f"\n[TELEGRAM PREVIEW]\n{message}\n")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return False


def send_daily_summary(date_iso: str, results: dict) -> None:
    """Send the daily harvest summary + sector momentum alert."""
    errors = results.get("errors", [])
    status = "🔴 ERRORS" if errors else "🟢 OK"

    msg = (
        f"📊 <b>alphatecx daily harvest</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Date: {date_iso}  Status: {status}\n\n"
        f"<b>Ingested:</b>\n"
        f"  T86 (inst. flow): {results.get('t86', 0):,} rows\n"
        f"  Holdings: {results.get('holdings', 0):,} rows\n"
        f"  Margin: {results.get('margin', 0):,} rows\n"
        f"  Revenue: {results.get('revenue', 0):,} rows\n"
    )

    if errors:
        msg += "\n<b>Errors:</b>\n"
        for e in errors:
            msg += f"  ⚠️ {e}\n"

    # Try to fetch sector momentum for the alert
    try:
        top_sectors = _fetch_top_sectors()
        if top_sectors:
            msg += "\n<b>Top FINI accumulation (5d):</b>\n"
            for i, s in enumerate(top_sectors[:5], 1):
                pillar = s.get("ai_pillar", "?")
                node = s.get("node", "?")
                flow_5d = s.get("foreign_5d", 0)
                top_ticker = s.get("top_ticker_5d_name", "")
                arrow = "🟢" if flow_5d > 0 else "🔴"
                msg += (
                    f"  {i}. {arrow} {pillar}/{node}: "
                    f"{flow_5d / 1000:+,.0f}K shares"
                )
                if top_ticker:
                    msg += f" (top: {top_ticker})"
                msg += "\n"
    except Exception as e:
        log.warning("Could not fetch sector momentum for alert: %s", e)

    send(msg, category="briefs")


def send_error_alert(source: str, error: str) -> None:
    """Send an error alert for a failed ingestion."""
    send(
        f"🔴 <b>alphatecx harvest error</b>\n"
        f"Source: {source}\n"
        f"Error: {error}",
        category="ops",
    )


def _fetch_top_sectors() -> list[dict]:
    """Query view_sector_momentum for top accumulated sectors."""
    try:
        from src.harvester.loader import cur
        sql = """
            SELECT ai_pillar, node, foreign_5d, top_ticker_5d_name
            FROM view_sector_momentum
            WHERE ai_pillar != 'unclassified'
            ORDER BY foreign_5d DESC
            LIMIT 5
        """
        with cur() as c:
            c.execute(sql)
            cols = [d.name for d in c.description]
            # strict=True: the cursor's column list and each row always have the
            # same length, so a mismatch means something is badly wrong and
            # should raise rather than silently drop columns. The enclosing
            # except turns that into "no sectors in the digest", not a crash.
            return [dict(zip(cols, row, strict=True)) for row in c.fetchall()]
    except Exception:
        log.exception("Failed to fetch top sectors for daily Telegram digest")
        return []
