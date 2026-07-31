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

Risk Guard (RISK_GUARD_PRD.md §6 介面一):
    /status                    today's risk light + position risk summary
    /pos                       positions and where their stop lines sit
    /setpos <ticker> k=v ...   set cost / warn / exit / lots
    /check <ticker> [amount]   six-question entry checklist
    /trade buy|sell <t> <price> x<lots>   report a fill (feeds the T+2 check)
    /balance <amount>          update the settlement-account balance
    /notrade <date> <reason>   mark a day as non-executable
"""
from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import requests
from fastapi import FastAPI, HTTPException, Request

# Same trick index.py uses: the Vercel function root is mcp_server/api and the
# `rg` package sits beside this file. Explicit rather than relying on the
# runtime's cwd, which differs between Vercel and local pytest.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rg import checklist as rg_checklist  # noqa: E402
from rg import config as rg_config  # noqa: E402
from rg import messages as rg_messages  # noqa: E402
from rg import settlement as rg_settlement  # noqa: E402
from rg import stops as rg_stops  # noqa: E402

_TPE = ZoneInfo("Asia/Taipei")

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


def _validate_ticker(ticker: str) -> str | None:
    """Return the canonical ticker if it parses, else None."""
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        return None
    return t


def cmd_help(arg: str) -> str:
    return (
        "<b>alphatecx-v2 commands</b>\n"
        "/watch &lt;ticker&gt; [reason] — add to watchlist + 自選\n"
        "/unwatch &lt;ticker&gt; — archive from watchlist\n"
        "/watchlist — show active watchlist\n"
        "/q &lt;ticker&gt; — quant indicators snapshot\n"
        "/n &lt;ticker&gt; — recent news (last 7d)\n"
        "/thesis &lt;ticker&gt; — thesis status\n"
        "\n<b>Risk Guard</b>\n"
        "/status — 今日燈號 + 持倉風險總覽\n"
        "/pos — 持倉與線位\n"
        "/setpos &lt;t&gt; cost=51.5 warn=49 exit=47.8 — 設定線位\n"
        "/check &lt;t&gt; [金額] — 進場 checklist(6題)\n"
        "/trade buy|sell &lt;t&gt; &lt;price&gt; x&lt;lots&gt; — 回報成交\n"
        "/balance &lt;金額&gt; — 更新交割戶餘額\n"
        "/notrade YYYY-MM-DD &lt;reason&gt; — 標記不可執行日\n"
        "\n/help — this message"
    )


def cmd_watch(arg: str) -> str:
    if not arg:
        return "用法:/watch &lt;股號&gt; [原因]"
    parts = arg.split(maxsplit=1)
    ticker = _validate_ticker(parts[0])
    if not ticker:
        return f"⚠️ 股號格式不正確:<code>{parts[0]}</code>"
    reason = parts[1] if len(parts) > 1 else ""

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT company_name, ai_pillar, node FROM dim_supply_chain "
            "WHERE ticker_id = %s",
            (ticker,),
        )
        row = cur.fetchone()
        company, pillar, node = row if row else (None, None, None)

        if not company:
            cur.execute("SELECT company_name FROM dim_ticker WHERE ticker_id = %s",
                        (ticker,))
            n = cur.fetchone()
            company = n[0] if n else None

        # Risk Guard's 自選 list is not restricted to the classified universe:
        # PRD §4 seeds it with names like 8299 that have no supply-chain row,
        # and a name you cannot watch is a name whose stop you cannot set.
        cur.execute("""
            INSERT INTO rg_positions (ticker_id, name, kind, note, active)
            VALUES (%s, %s, 'watch', %s, TRUE)
            ON CONFLICT (ticker_id) DO UPDATE SET
                name = COALESCE(rg_positions.name, EXCLUDED.name),
                note = COALESCE(NULLIF(EXCLUDED.note, ''), rg_positions.note),
                active = TRUE,
                updated_at = now()
        """, (ticker, company, reason))

        if row:
            cur.execute("""
                INSERT INTO watchlist (ticker_id, company_name, ai_pillar, node,
                                       reason, added_at, updated_at, status)
                VALUES (%s, %s, %s, %s, %s, now(), now(), 'active')
                ON CONFLICT (ticker_id) DO UPDATE SET
                    reason = COALESCE(NULLIF(EXCLUDED.reason, ''), watchlist.reason),
                    status = 'active',
                    updated_at = now()
            """, (ticker, company, pillar, node, reason))

    suffix = f"\n原因:{reason}" if reason else ""
    if row:
        return (f"✅ 已加入 <b>{ticker}</b> {company} "
                f"({pillar}/{node}) 到監控清單 + Risk Guard 自選。{suffix}")
    return (f"✅ 已加入 <b>{ticker}</b> {company or ''} 到 Risk Guard 自選。\n"
            f"ℹ️ 不在分類供應鏈名單中,故未加入分類監控清單。{suffix}")


def cmd_unwatch(arg: str) -> str:
    if not arg:
        return "用法:/unwatch &lt;股號&gt;"
    ticker = _validate_ticker(arg.strip().split()[0])
    if not ticker:
        return f"⚠️ 股號格式不正確:<code>{arg}</code>"

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE watchlist SET status = 'archived', updated_at = now() "
            "WHERE ticker_id = %s AND status = 'active' RETURNING company_name",
            (ticker,),
        )
        row = cur.fetchone()

    if not row:
        return f"ℹ️ <code>{ticker}</code> 不在目前的監控清單中。"
    return f"🗄️ 已將 <b>{ticker}</b> {row[0]} 移出監控清單。"


def cmd_list(arg: str) -> str:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            -- 中文名優先:watchlist.company_name 是 bot 寫入的英文
            -- (GlobalWafers),dim_ticker.company_name 是 TWSE 發布的中文
            -- (環球晶)。顯示面一律走中文,英文只在中文缺漏時兜底。
            SELECT w.ticker_id,
                   COALESCE(NULLIF(t.company_name, ''), w.company_name),
                   w.ai_pillar, w.node, w.reason, w.added_at::date
            FROM watchlist w
            LEFT JOIN dim_ticker t ON t.ticker_id = w.ticker_id
            WHERE w.status = 'active'
            ORDER BY w.added_at DESC, w.ticker_id
        """)
        rows = cur.fetchall()

    if not rows:
        return "📋 監控清單是空的。"
    lines = [f"<b>📋 監控清單({len(rows)} 檔)</b>"]
    for r in rows:
        ticker, company, pillar, node, reason, added = r
        lines.append(f"• <b>{ticker}</b> {company} <i>({pillar}/{node}, "
                     f"加入於 {added})</i>")
        if reason:
            lines.append(f"   {reason[:140]}")
    return "\n".join(lines)


def cmd_indicators(arg: str) -> str:
    """Quick q_indicators-equivalent reply — bypasses MCP, queries DB directly."""
    if not arg:
        return "用法:/q &lt;股號&gt;"
    ticker = _validate_ticker(arg.strip().split()[0])
    if not ticker:
        return f"⚠️ 股號格式不正確:<code>{arg}</code>"

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
        return f"ℹ️ 查無 <code>{ticker}</code> 的指標資料(可能不在分類名單中)。"

    _, company, as_of, rsi, macd_h, bb, fz, off_high, rs = row

    def fmt(v):
        return f"{v:.2f}" if v is not None else "—"

    # 術語保留原文、後面加一句白話。翻成「相對強弱指標」反而更難懂,
    # 而且看盤軟體和研究報告一律用 RSI —— 要降低的是理解成本,不是英文字。
    def gloss(v, bands):
        """bands: [(上限, 說明), ...],由低到高;最後一項的上限用 None。"""
        if v is None:
            return ""
        for hi, label in bands:
            if hi is None or v < hi:
                return f" ({label})"
        return ""

    return (
        f"<b>{ticker}</b> {company or ''} <i>({as_of} 收盤)</i>\n"
        f"RSI-14: {fmt(rsi)}{gloss(rsi, [(30, '超賣'), (70, '中性'), (None, '超買')])}"
        f"  •  MACD: {fmt(macd_h)}{gloss(macd_h, [(0, '下跌動能'), (None, '上漲動能')])}\n"
        f"BB%B: {fmt(bb)}{gloss(bb, [(0, '跌破下軌'), (1, '通道內'), (None, '突破上軌')])}\n"
        f"外資 z20: {fmt(fz)}"
        f"{gloss(fz, [(-2, '異常賣超'), (-1, '賣超'), (1, '中性'), (2, '買超'), (None, '異常買超')])}\n"
        f"距一年高點: {fmt(off_high)}%\n"
        f"60日相對大盤: {fmt(rs)}{gloss(rs, [(1, '落後'), (None, '領先')])}"
    )


def cmd_news(arg: str) -> str:
    if not arg:
        return "用法:/n &lt;股號&gt;"
    ticker = _validate_ticker(arg.strip().split()[0])
    if not ticker:
        return f"⚠️ 股號格式不正確:<code>{arg}</code>"

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
        return "用法:/thesis &lt;股號&gt;"
    ticker = _validate_ticker(arg.strip().split()[0])
    if not ticker:
        return f"⚠️ 股號格式不正確:<code>{arg}</code>"
    # Theses live as MD files in the repo, not in DB. The bot doesn't
    # have repo access — point the user at the MCP / Claude app instead.
    return (f"ℹ️ 論點檔案存在 repo 的 <code>docs/theses/</code>,不在資料庫裡。"
            f"要看 <code>{ticker}</code> 目前的論點,請用 Claude app 的專案檢視,"
            f"或到 github.com/tecxmate/alphatecx/tree/main/docs/theses")


# ── Risk Guard commands ──────────────────────────────────────────────────
#
# These share the bot's writer connection. They deliberately duplicate no
# decision logic: every judgement comes from the same pure functions in `rg`
# that the cron pipeline and the MCP tools call, so the phone, the dashboard
# and the Claude conversation cannot drift apart.

_KV_RE = re.compile(r"(\w+)\s*=\s*([\d.]+)")
_TRADE_RE = re.compile(
    r"^(buy|sell)\s+([0-9A-Za-z]+)\s+([\d.]+)\s*[xX*]?\s*([\d.]+)$", re.IGNORECASE
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _today() -> str:
    return datetime.now(_TPE).date().isoformat()


def _rg_positions(cur, include_inactive: bool = False) -> list[dict]:
    cur.execute(
        "SELECT ticker_id, name, kind, cost, qty_lots, warn_price, exit_price, "
        "       hard_stop_pct, note, active FROM rg_positions "
        + ("" if include_inactive else " WHERE active ")
        + " ORDER BY kind, ticker_id"
    )
    cols = [d.name for d in cur.description]
    rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    for r in rows:
        for k in ("cost", "qty_lots", "warn_price", "exit_price", "hard_stop_pct"):
            if r[k] is not None:
                r[k] = float(r[k])
    return rows


def _rg_closes(cur, tickers: list[str]) -> tuple[dict[str, float], dict[str, str]]:
    """Latest close per ticker, but ONLY from the market's most recent session.

    Returns (fresh, stale); `stale` maps ticker -> the out-of-date session it
    would otherwise have reported.

    The previous version took each ticker's newest row whatever its date and
    presented it as today's price. `raw_twse_ohlcv` does not cover every
    watchlist name — on 2026-07-31, of 2324/2303/3374/2344 only 2344 had a row
    — so uncovered tickers silently rendered a price from an arbitrarily old
    session. Observed: 2324 showed 29.65 against a real 36.0, and 2303 showed
    91.3 against a real 121.0 (limit up). The stop engine reads this number to
    decide whether a line was breached, so a stale price is a wrong exit or a
    missed one.

    Staleness is measured against the newest date in the table rather than a
    calendar, so weekends and holidays need no special case. Callers must show
    the stale entries as "no quote"; `rg_stops.distances` already degrades
    safely when a close is absent, which is why dropping is the right shape —
    a wrong price can no longer reach a stop decision at all.
    """
    if not tickers:
        return {}, {}
    cur.execute(
        "SELECT DISTINCT ON (ticker_id) ticker_id, close, date FROM raw_twse_ohlcv "
        " WHERE ticker_id = ANY(%s) ORDER BY ticker_id, date DESC",
        (tickers,),
    )
    rows = [(r[0], r[1], r[2]) for r in cur.fetchall() if r[1] is not None]
    if not rows:
        return {}, {}

    cur.execute("SELECT max(date) FROM raw_twse_ohlcv")
    latest_row = cur.fetchone()
    latest = latest_row[0] if latest_row else None

    fresh: dict[str, float] = {}
    stale: dict[str, str] = {}
    for ticker, close, date in rows:
        if latest is not None and date != latest:
            stale[ticker] = date.isoformat()
        else:
            fresh[ticker] = float(close)
    if stale:
        log.warning("stale closes suppressed (market latest %s): %s", latest, stale)
    return fresh, stale


def _rg_trading_days(cur, start: str, days: int = 30) -> list[str]:
    end = (datetime.fromisoformat(start) + timedelta(days=days)).date().isoformat()
    cur.execute(
        "SELECT d::date FROM generate_series(%s::date, %s::date, '1 day') d "
        " WHERE EXTRACT(ISODOW FROM d) < 6 "
        "   AND NOT EXISTS (SELECT 1 FROM market_holidays h "
        "                    WHERE h.cal_date = d::date AND h.is_closed) "
        " ORDER BY d",
        (start, end),
    )
    return [r[0].isoformat() for r in cur.fetchall()]


def cmd_status(arg: str) -> str:
    """Today's light plus where every stop line sits — the one-screen answer."""
    today = _today()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT date, risk_light, risk_score, taiex_close, taiex_pct, reasons "
            "  FROM rg_market_daily ORDER BY date DESC LIMIT 1"
        )
        m = cur.fetchone()
        positions = _rg_positions(cur)
        closes, stale_closes = _rg_closes(cur, [p["ticker_id"] for p in positions])
        cur.execute("SELECT amount FROM rg_balances ORDER BY ts DESC LIMIT 1")
        bal_row = cur.fetchone()
        cur.execute(
            "SELECT date, net_amount FROM rg_settlements WHERE date >= %s "
            " ORDER BY date LIMIT 3", (today,)
        )
        settlements = [{"date": r[0].isoformat(), "net_amount": float(r[1])}
                       for r in cur.fetchall()]
        cur.execute("SELECT reason FROM rg_no_trade_days WHERE date = %s", (today,))
        nt = cur.fetchone()

    if not m:
        return ("ℹ️ 尚未計算風險燈號。請先跑 "
                "<code>python -m riskguard.pipeline --mode post_close</code>")

    date, light, score, close, pct, reasons = m
    emoji = rg_config.LIGHT_EMOJI.get(light, "")
    lines = [f"{emoji} <b>市場燈號 {light}</b> (score {score}) — {date}",
             f"TAIEX {close} ({pct:+.2f}%)" if pct is not None else f"TAIEX {close}"]
    for r in (reasons or []):
        if r.get("points"):
            lines.append(f"  +{r['points']} {r['detail']}")
    missing = [r["name"] for r in (reasons or []) if r.get("data_missing")]
    if missing:
        lines.append(f"  ⚠️ 資料缺漏(未計分):{'、'.join(missing)}")

    rows = rg_stops.distances(positions, closes)
    held = [r for r in rows if r["kind"] == "position"]
    lines.append("")
    if held:
        lines.append("<b>持倉風險</b>")
        for r in held:
            d = f"{r['pct_to_exit']:+.1f}%" if r["pct_to_exit"] is not None else "未設線"
            flag = " 🚨已觸線" if r["triggered"] == "exit" else (
                " ⚠️警戒" if r["triggered"] == "warn" else "")
            px = r["close"] if r["close"] is not None else "無報價"
            lines.append(f"  {r['name'] or ''}({r['ticker_id']}) "
                         f"收 {px} 距出場 {d}{flag}")
    else:
        lines.append("<b>持倉風險</b>:目前空手")

    balance = float(bal_row[0]) if bal_row else None
    lines.append("")
    if settlements:
        lines.append("<b>交割款</b>")
        for s in settlements:
            lines.append(f"  {s['date']}  {s['net_amount']:+,.0f}")
        lines.append(f"  餘額回報:{balance:,.0f}" if balance is not None
                     else "  ⚠️ 尚未回報交割戶餘額(/balance)")
    else:
        lines.append("<b>交割款</b>:無待交割")

    if nt:
        lines.append(f"\n📿 今日節律否決:{nt[0]}")
    return "\n".join(lines)


def cmd_pos(arg: str) -> str:
    with _connect() as conn, conn.cursor() as cur:
        positions = _rg_positions(cur)
        closes, stale_closes = _rg_closes(cur, [p["ticker_id"] for p in positions])

    if not positions:
        return "📋 監控清單是空的。用 /setpos 或 /watch 加入。"
    rows = rg_stops.distances(positions, closes)
    lines = [f"<b>📋 監控清單 ({len(rows)})</b>"]
    for group, title in (("position", "持倉"), ("watch", "自選")):
        subset = [r for r in rows if r["kind"] == group]
        if not subset:
            continue
        lines.append(f"<b>{title}</b>")
        for r in subset:
            bits = [f"收 {r['close']}" if r["close"] is not None else "無報價"]
            if r["cost"]:
                bits.append(f"成本 {r['cost']} ({r['pct_from_cost']:+.1f}%)"
                            if r["pct_from_cost"] is not None else f"成本 {r['cost']}")
            if r["warn_price"]:
                bits.append(f"警戒 {r['warn_price']}")
            if r["exit_price"]:
                tag = "(兜底)" if r["exit_is_fallback"] else ""
                bits.append(f"出場 {r['exit_price']}{tag}")
            lines.append(f"• <b>{r['ticker_id']}</b> {r['name'] or ''} — "
                         + " | ".join(bits))
            if r["note"]:
                lines.append(f"   {r['note'][:140]}")
    if stale_closes:
        names = "、".join(f"{t}({d})" for t, d in sorted(stale_closes.items()))
        lines.append(f"  ⚠️ 報價過期已抑制(不用於停損判斷):{names}")
    return "\n".join(lines)


def cmd_setpos(arg: str) -> str:
    """/setpos 2344 cost=51.5 warn=49 exit=47.8 lots=3"""
    if not arg:
        return ("用法:/setpos &lt;股號&gt; cost=51.5 warn=49 exit=47.8 lots=3\n"
                "只更新有給的欄位,沒給的保持原值。")
    parts = arg.split()
    ticker = _validate_ticker(parts[0])
    if not ticker:
        return f"⚠️ 股號格式不正確:<code>{parts[0]}</code>"

    kv = {k.lower(): float(v) for k, v in _KV_RE.findall(arg)}
    field_map = {"cost": "cost", "warn": "warn_price", "exit": "exit_price",
                 "lots": "qty_lots", "stop": "hard_stop_pct"}
    patch = {field_map[k]: v for k, v in kv.items() if k in field_map}
    if not patch:
        return ("⚠️ 沒有可辨識的欄位。可用:cost / warn / exit / lots / stop")

    # Any priced field means this is a real position, not a watch name.
    patch["kind"] = "position"
    patch["active"] = True
    cols = ["ticker_id"] + list(patch)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in patch)
    sql = (f"INSERT INTO rg_positions ({', '.join(cols)}) "
           f"VALUES ({', '.join(['%s'] * len(cols))}) "
           f"ON CONFLICT (ticker_id) DO UPDATE SET {updates}, updated_at = now()")
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, [ticker] + list(patch.values()))

    shown = ", ".join(f"{k}={v}" for k, v in patch.items() if k not in ("kind", "active"))
    return (f"✅ <b>{ticker}</b> 已更新:{shown}\n"
            f"👉 {rg_config.CONDITIONAL_ORDER_ADVICE}")


def cmd_check(arg: str) -> str:
    """/check 2344 [買進金額]"""
    if not arg:
        return "用法:/check &lt;股號&gt; [買進金額]"
    parts = arg.split()
    ticker = _validate_ticker(parts[0])
    if not ticker:
        return f"⚠️ 股號格式不正確:<code>{parts[0]}</code>"
    buy_amount = float(parts[1].replace(",", "")) if len(parts) > 1 else None

    today = _today()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT risk_light FROM rg_market_daily ORDER BY date DESC LIMIT 1")
        m = cur.fetchone()
        cur.execute("SELECT name, note FROM rg_positions WHERE ticker_id = %s", (ticker,))
        p = cur.fetchone()
        cur.execute("SELECT reason FROM rg_no_trade_days WHERE date = %s", (today,))
        nt = cur.fetchone()
        cur.execute("SELECT amount FROM rg_balances ORDER BY ts DESC LIMIT 1")
        bal = cur.fetchone()
        cur.execute(
            "SELECT close FROM raw_twse_ohlcv WHERE ticker_id = %s "
            " ORDER BY date DESC LIMIT 6", (ticker,)
        )
        closes = [float(r[0]) for r in cur.fetchall() if r[0] is not None]
        name = p[0] if p else None
        if not name:
            cur.execute("SELECT company_name FROM dim_ticker WHERE ticker_id = %s",
                        (ticker,))
            n = cur.fetchone()
            name = n[0] if n else None

    note = (p[1] if p else "") or ""
    gain_5d = (round((closes[0] / closes[5] - 1) * 100, 2)
               if len(closes) >= 6 and closes[5] else None)

    result = rg_checklist.evaluate({
        "ticker_id": ticker,
        "name": name,
        "risk_light": m[0] if m else None,
        "sector_rank": None,        # M3 — Phase 2
        "gain_5d_pct": gain_5d,
        "is_disposition": None,     # M6 — Phase 4
        "no_trade_reason": nt[0] if nt else None,
        "buy_amount": buy_amount,
        "available_cash": float(bal[0]) if bal else None,
        "blacklisted": "拉黑" in note,
        "blacklist_note": note or None,
    })
    return rg_messages.format_checklist(result)


def cmd_trade(arg: str) -> str:
    """/trade buy 2344 51.5 x3 — report a fill so the T+2 check knows about it."""
    m = _TRADE_RE.match(arg.strip())
    if not m:
        return "用法:/trade buy|sell &lt;股號&gt; &lt;價格&gt; x&lt;張數&gt;"
    side, raw_ticker, price, lots = m.group(1).lower(), m.group(2), float(m.group(3)), float(m.group(4))
    ticker = _validate_ticker(raw_ticker)
    if not ticker:
        return f"⚠️ 股號格式不正確:<code>{raw_ticker}</code>"

    trade_date = _today()
    net = rg_settlement.fill_amount(side, price, lots)

    with _connect() as conn, conn.cursor() as cur:
        days = _rg_trading_days(cur, trade_date)
        settle = rg_settlement.settle_date(trade_date, days)
        if settle is None:
            return (f"⚠️ 無法推算交割日({trade_date} 不在交易日曆內,"
                    "或行事曆資料不足)。請確認 market_holidays 已更新。")
        cur.execute(
            "INSERT INTO rg_trades (trade_date, settle_date, ticker_id, side, "
            "                       price, lots, net_amount) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (trade_date, settle, ticker, side, price, lots, net),
        )
        cur.execute(
            "INSERT INTO rg_settlements (date, net_amount) VALUES (%s, %s) "
            "ON CONFLICT (date) DO UPDATE SET "
            "  net_amount = rg_settlements.net_amount + EXCLUDED.net_amount, "
            "  updated_at = now()",
            (settle, net),
        )
        cur.execute("SELECT amount FROM rg_balances ORDER BY ts DESC LIMIT 1")
        bal = cur.fetchone()
        cur.execute("SELECT date, net_amount FROM rg_settlements WHERE date >= %s "
                    " ORDER BY date LIMIT 3", (trade_date,))
        schedule = [{"date": r[0].isoformat(), "net_amount": float(r[1])}
                    for r in cur.fetchall()]

    verb = "買進" if side == "buy" else "賣出"
    lines = [f"✅ 已記錄:{verb} <b>{ticker}</b> {price} × {lots:g} 張",
             f"交割日 {settle},淨額 {net:+,.0f}"]

    gaps = rg_settlement.check_gap(schedule, float(bal[0]) if bal else None,
                                   trade_date, days)
    for g in gaps:
        prefix = "🚨 " if g["severity"] == "critical" else "⚠️ "
        lines.append(prefix + g["action"])
    return "\n".join(lines)


def cmd_balance(arg: str) -> str:
    if not arg:
        return "用法:/balance &lt;金額&gt;"
    try:
        amount = float(arg.strip().replace(",", ""))
    except ValueError:
        return f"⚠️ 無法解析金額:<code>{arg}</code>"

    today = _today()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO rg_balances (amount) VALUES (%s)", (amount,))
        cur.execute("SELECT date, net_amount FROM rg_settlements WHERE date >= %s "
                    " ORDER BY date LIMIT 3", (today,))
        schedule = [{"date": r[0].isoformat(), "net_amount": float(r[1])}
                    for r in cur.fetchall()]
        days = _rg_trading_days(cur, today)

    lines = [f"✅ 交割戶餘額已更新:{amount:,.0f}"]
    for g in rg_settlement.check_gap(schedule, amount, today, days):
        if g["severity"] == "critical":
            lines.append("🚨 " + g["action"])
    if len(lines) == 1 and schedule:
        lines.append("👉 未來 3 個交割日餘額足夠。")
    return "\n".join(lines)


def cmd_notrade(arg: str) -> str:
    """/notrade 2026-08-04 <reason> — M7 veto. Blocks checklist Q5 for that day
    and nothing else: it never touches a score, a light, or an alert trigger."""
    parts = arg.split(maxsplit=1)
    if len(parts) < 2 or not _DATE_RE.match(parts[0]):
        return "用法:/notrade YYYY-MM-DD &lt;原因&gt;"
    date_iso, reason = parts[0], parts[1].strip()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rg_no_trade_days (date, reason) VALUES (%s, %s) "
            "ON CONFLICT (date) DO UPDATE SET reason = EXCLUDED.reason",
            (date_iso, reason),
        )
    return f"📿 已標記 <b>{date_iso}</b> 為不可執行日:{reason}\nchecklist 第5題將為 ❌。"


HANDLERS = {
    "/watch": cmd_watch,
    "/unwatch": cmd_unwatch,
    "/watchlist": cmd_list,
    "/q": cmd_indicators,
    "/n": cmd_news,
    "/thesis": cmd_thesis,
    "/help": cmd_help,
    "/start": cmd_help,
    # Risk Guard
    "/status": cmd_status,
    "/pos": cmd_pos,
    "/setpos": cmd_setpos,
    "/check": cmd_check,
    "/trade": cmd_trade,
    "/balance": cmd_balance,
    "/notrade": cmd_notrade,
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
        _send(chat_id, f"未知指令:<code>{cmd}</code>\n輸入 /help 看可用指令。")
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
