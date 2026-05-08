"""Telegram bot webhook for alphatecx-v2.

Mounts at /bot/webhook on the same Vercel project as the MCP. Different
DSN: this function uses BOT_DATABASE_URL (writer creds) where the MCP
uses MCP_DATABASE_URL (read-only). The function is gated by Telegram's
secret-token header — only requests with the right
`X-Telegram-Bot-Api-Secret-Token` value are processed; everything else
gets a 403.

Owner-gated: the bot ignores any update whose `chat.id` doesn't match
TELEGRAM_CHAT_ID, so even if someone discovers the webhook URL and
guesses the secret, they can't drive your watchlist.

Commands:
    /watch <ticker> [reason]   add a name to the watchlist
    /unwatch <ticker>          archive a watchlist row
    /watchlist                 list active rows
    /q <ticker>                quant indicators snapshot
    /n <ticker>                recent news mentions (last 7 days)
    /thesis <ticker>           thesis status if active
    /help                      command list
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

import psycopg
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("bot")

DATABASE_URL = os.environ.get("BOT_DATABASE_URL", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

app = FastAPI(title="alphatecx-v2-bot", version="0.1")


# ── Connection + Telegram helpers ─────────────────────────────────────────

def _connect():
    """Open a Neon writer connection. search_path set inline since this
    function isn't pooled (each webhook call is a fresh Vercel invocation;
    pooling would be wrong for serverless)."""
    if not DATABASE_URL:
        raise RuntimeError("BOT_DATABASE_URL not configured")
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    conn.execute("SET search_path TO public, neon_auth")
    return conn


def _send(chat_id: int | str, text: str, parse_mode: str = "HTML") -> None:
    """POST a reply to Telegram. Best-effort — failure here doesn't
    crash the webhook (Telegram would just retry the original update)."""
    if not TELEGRAM_TOKEN:
        log.error("TELEGRAM_TOKEN not configured; can't reply")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                  "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception as e:
        log.error("Telegram send failed: %s", e)


# ── Command handlers ─────────────────────────────────────────────────────
#
# Each cmd_* takes the full argument string and returns the reply text.
# Returning None means "no reply" (silent).

_TICKER_RE = re.compile(r"^[0-9A-Z]+[A-Z]?$")  # e.g. 2330, 6488, 0050, 00400A


def _validate_ticker(ticker: str) -> Optional[str]:
    """Return the canonical ticker if it parses, else None."""
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        return None
    return t


def cmd_help(arg: str) -> str:
    return (
        "<b>alphatecx-v2 commands</b>\n"
        "/watch &lt;ticker&gt; [reason] — add to watchlist\n"
        "/unwatch &lt;ticker&gt; — archive from watchlist\n"
        "/watchlist — show active watchlist\n"
        "/q &lt;ticker&gt; — quant indicators snapshot\n"
        "/n &lt;ticker&gt; — recent news (last 7d)\n"
        "/thesis &lt;ticker&gt; — thesis status\n"
        "/help — this message"
    )


def cmd_watch(arg: str) -> str:
    if not arg:
        return "Usage: /watch &lt;ticker&gt; [reason]"
    parts = arg.split(maxsplit=1)
    ticker = _validate_ticker(parts[0])
    if not ticker:
        return f"⚠️ Invalid ticker format: <code>{parts[0]}</code>"
    reason = parts[1] if len(parts) > 1 else ""

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT company_name, ai_pillar, node FROM dim_supply_chain "
            "WHERE ticker_id = %s",
            (ticker,),
        )
        row = cur.fetchone()
        if not row:
            return (f"⚠️ <code>{ticker}</code> isn't in the classified "
                    "supply chain (the 26-name universe). Watchlist is "
                    "limited to those names.")
        company, pillar, node = row

        cur.execute("""
            INSERT INTO watchlist (ticker_id, company_name, ai_pillar, node,
                                   reason, added_at, updated_at, status)
            VALUES (%s, %s, %s, %s, %s, now(), now(), 'active')
            ON CONFLICT (ticker_id) DO UPDATE SET
                reason = COALESCE(NULLIF(EXCLUDED.reason, ''), watchlist.reason),
                status = 'active',
                updated_at = now()
        """, (ticker, company, pillar, node, reason))

    suffix = f"\nReason: {reason}" if reason else ""
    return (f"✅ Added <b>{ticker}</b> {company} "
            f"({pillar}/{node}) to watchlist.{suffix}")


def cmd_unwatch(arg: str) -> str:
    if not arg:
        return "Usage: /unwatch &lt;ticker&gt;"
    ticker = _validate_ticker(arg.strip().split()[0])
    if not ticker:
        return f"⚠️ Invalid ticker format: <code>{arg}</code>"

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE watchlist SET status = 'archived', updated_at = now() "
            "WHERE ticker_id = %s AND status = 'active' RETURNING company_name",
            (ticker,),
        )
        row = cur.fetchone()

    if not row:
        return f"ℹ️ <code>{ticker}</code> is not on the active watchlist."
    return f"🗄️ Archived <b>{ticker}</b> {row[0]} from watchlist."


def cmd_list(arg: str) -> str:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT ticker_id, company_name, ai_pillar, node, reason,
                   added_at::date
            FROM watchlist WHERE status = 'active'
            ORDER BY added_at DESC, ticker_id
        """)
        rows = cur.fetchall()

    if not rows:
        return "📋 Watchlist is empty."
    lines = [f"<b>📋 Watchlist ({len(rows)} active)</b>"]
    for r in rows:
        ticker, company, pillar, node, reason, added = r
        lines.append(f"• <b>{ticker}</b> {company} <i>({pillar}/{node}, "
                     f"added {added})</i>")
        if reason:
            lines.append(f"   {reason[:140]}")
    return "\n".join(lines)


def cmd_indicators(arg: str) -> str:
    """Quick q_indicators-equivalent reply — bypasses MCP, queries DB directly."""
    if not arg:
        return "Usage: /q &lt;ticker&gt;"
    ticker = _validate_ticker(arg.strip().split()[0])
    if not ticker:
        return f"⚠️ Invalid ticker format: <code>{arg}</code>"

    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT ls.ticker_id, sc.company_name, ls.as_of,
                   ls.rsi_14, ls.macd_histogram, ls.bb_pct_b,
                   ls.foreign_net_z20, ls.pct_below_52w_high,
                   ls.rs_vs_market_60
            FROM view_latest_signals ls
            LEFT JOIN dim_supply_chain sc ON sc.ticker_id = ls.ticker_id
            WHERE ls.ticker_id = %s
        """, (ticker,))
        row = cur.fetchone()
    if not row:
        return f"ℹ️ No signals for <code>{ticker}</code> (not in classified universe?)."

    _, company, as_of, rsi, macd_h, bb, fz, off_high, rs = row
    fmt = lambda v: f"{v:.2f}" if v is not None else "—"
    return (f"<b>{ticker}</b> {company or ''} <i>(as of {as_of})</i>\n"
            f"RSI-14: {fmt(rsi)}  •  MACD hist: {fmt(macd_h)}  •  BB%B: {fmt(bb)}\n"
            f"foreign_z20: {fmt(fz)}  •  off_52w_high: {fmt(off_high)}%\n"
            f"RS vs mkt 60d: {fmt(rs)}")


def cmd_news(arg: str) -> str:
    if not arg:
        return "Usage: /n &lt;ticker&gt;"
    ticker = _validate_ticker(arg.strip().split()[0])
    if not ticker:
        return f"⚠️ Invalid ticker format: <code>{arg}</code>"

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT company_name FROM dim_supply_chain WHERE ticker_id = %s",
            (ticker,),
        )
        cn_row = cur.fetchone()
        company_name = cn_row[0] if cn_row else None

        # Mirror the text-fallback used by query_news_for_ticker, with
        # SQL-literal '%' doubled (psycopg placeholder escape).
        if company_name:
            cur.execute("""
                SELECT title, source, COALESCE(published_at, fetched_at) AS ts
                FROM raw_news
                WHERE COALESCE(published_at, fetched_at) >= now() - INTERVAL '7 days'
                  AND (
                       title ~ ('(^|[^0-9])' || %s || '([^0-9]|$)')
                    OR title ILIKE ('%%' || %s || '%%')
                  )
                ORDER BY ts DESC LIMIT 5
            """, (ticker, company_name))
        else:
            cur.execute("""
                SELECT title, source, COALESCE(published_at, fetched_at) AS ts
                FROM raw_news
                WHERE COALESCE(published_at, fetched_at) >= now() - INTERVAL '7 days'
                  AND title ~ ('(^|[^0-9])' || %s || '([^0-9]|$)')
                ORDER BY ts DESC LIMIT 5
            """, (ticker,))
        rows = cur.fetchall()

    if not rows:
        return f"ℹ️ No news mentions of <code>{ticker}</code> in last 7 days."
    lines = [f"<b>📰 {ticker} — last 7d news ({len(rows)})</b>"]
    for r in rows:
        title, source, ts = r
        date = ts.strftime("%m-%d") if ts else "—"
        lines.append(f"• [{date}, {source}] {title[:120]}")
    return "\n".join(lines)


def cmd_thesis(arg: str) -> str:
    if not arg:
        return "Usage: /thesis &lt;ticker&gt;"
    ticker = _validate_ticker(arg.strip().split()[0])
    if not ticker:
        return f"⚠️ Invalid ticker format: <code>{arg}</code>"
    # Theses live as MD files in the repo, not in DB. The bot doesn't
    # have repo access — point the user at the MCP / Claude app instead.
    return (f"ℹ️ Thesis files live in <code>docs/theses/</code> in the "
            f"repo. To see active thesis on <code>{ticker}</code>, use "
            f"the Claude app project view or check "
            f"github.com/nikolasdoan/alphatecx-v2/tree/main/docs/theses")


HANDLERS = {
    "/watch": cmd_watch,
    "/unwatch": cmd_unwatch,
    "/watchlist": cmd_list,
    "/q": cmd_indicators,
    "/n": cmd_news,
    "/thesis": cmd_thesis,
    "/help": cmd_help,
    "/start": cmd_help,
}


# ── Webhook entry point ──────────────────────────────────────────────────

@app.post("/bot/webhook")
async def webhook(request: Request):
    secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")

    update = await request.json()
    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    chat_id = message.get("chat", {}).get("id")

    if not text or chat_id is None:
        return {"ok": True}
    if str(chat_id) != str(TELEGRAM_CHAT_ID):
        # Owner-gate. Silently ignore — never reveal who the bot is for.
        return {"ok": True}

    if not text.startswith("/"):
        return {"ok": True}
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # /watch@MyBot → /watch
    arg = parts[1] if len(parts) > 1 else ""

    handler = HANDLERS.get(cmd)
    if handler is None:
        _send(chat_id, f"Unknown command: <code>{cmd}</code>\nTry /help.")
        return {"ok": True}

    try:
        reply = handler(arg)
    except Exception as e:
        log.exception("handler %s failed", cmd)
        reply = f"❌ Error executing {cmd}: {type(e).__name__}: {str(e)[:200]}"

    if reply:
        _send(chat_id, reply)
    return {"ok": True}


@app.get("/bot/health")
def health():
    return {"ok": True, "service": "alphatecx-v2-bot"}
