"""Time-of-day-aware brief generator. Writes to daily_digest, optionally
sends Telegram. Driven from cron jobs in .github/workflows/.

Modes:
  pre_market   — overnight news + watchlist for the open. Sends Telegram.
  intraday     — alert-only. Sends Telegram ONLY if a hard threshold trips.
                 No digest row written if zero alerts (no-op is success).
  post_close   — full day's recap + thesis status check. Sends Telegram.

Each mode reads from the DB only (signals + news + thesis files). No
TWSE / RSS calls. The harvester runs on its own schedule and feeds
this script via the database.

Run:
    python -m src.cron.brief --mode pre_market
    python -m src.cron.brief --mode intraday
    python -m src.cron.brief --mode post_close
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.harvester.loader import cur
from src.alerts.telegram import send

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("cron.brief")

_TPE = ZoneInfo("Asia/Taipei")

# ── Alert thresholds ──────────────────────────────────────────────────────
# These define what counts as "actionable" during intraday checks.
# Pre-market and post-close briefs always fire; only intraday is gated.
ALERT_RSI_HIGH = 80.0
ALERT_RSI_LOW = 20.0
ALERT_FOREIGN_Z = 2.0
ALERT_BB_HIGH = 1.0       # close above upper Bollinger band
ALERT_BB_LOW = 0.0        # close below lower Bollinger band


def _today_taipei_iso() -> str:
    return datetime.now(_TPE).date().isoformat()


def _query_news_recent(c, hours: int, limit: int = 20) -> list[dict]:
    c.execute(
        """
        SELECT title, source, lang, COALESCE(published_at, fetched_at) AS ts
        FROM raw_news
        WHERE COALESCE(published_at, fetched_at) >= now() - (%s || ' hours')::interval
        ORDER BY ts DESC LIMIT %s
        """,
        (str(hours), limit),
    )
    return [
        {"title": r[0], "source": r[1], "lang": r[2], "ts": r[3]}
        for r in c.fetchall()
    ]


def _query_news_for_classified(c, hours: int) -> list[dict]:
    """Filter recent news to articles mentioning a classified ticker code or name."""
    # SQL literal '%' must be doubled to '%%' inside a psycopg parameterised
    # query — single '%' confuses the placeholder parser.
    c.execute(
        """
        WITH classified AS (
          SELECT ticker_id, company_name FROM dim_supply_chain
        ),
        recent AS (
          SELECT title, source, lang, COALESCE(published_at, fetched_at) AS ts,
                 raw_summary
          FROM raw_news
          WHERE COALESCE(published_at, fetched_at) >= now() - (%s || ' hours')::interval
        )
        SELECT DISTINCT ON (r.title) r.title, r.source, r.lang, r.ts, c.ticker_id, c.company_name
        FROM recent r CROSS JOIN classified c
        WHERE r.title ~ ('(^|[^0-9])' || c.ticker_id || '([^0-9]|$)')
           OR r.title ILIKE ('%%' || c.company_name || '%%')
        ORDER BY r.title, r.ts DESC
        """,
        (str(hours),),
    )
    return [
        {"title": r[0], "source": r[1], "lang": r[2], "ts": r[3],
         "ticker_id": r[4], "company_name": r[5]}
        for r in c.fetchall()
    ]


def _query_extreme_signals(c) -> list[dict]:
    """Names with extreme indicator readings worth flagging."""
    c.execute(
        """
        SELECT ls.ticker_id, sc.company_name, sc.ai_pillar, sc.node,
               ls.rsi_14, ls.bb_pct_b, ls.foreign_net_z20,
               ls.macd_histogram, ls.pct_below_52w_high
        FROM view_latest_signals ls
        JOIN dim_supply_chain sc ON sc.ticker_id = ls.ticker_id
        WHERE ls.rsi_14 IS NOT NULL
          AND (
            ls.rsi_14 > %s OR ls.rsi_14 < %s
            OR ls.bb_pct_b > %s OR ls.bb_pct_b < %s
            OR ls.foreign_net_z20 > %s OR ls.foreign_net_z20 < (-1 * %s)
          )
        ORDER BY abs(coalesce(ls.foreign_net_z20, 0)) DESC, abs(ls.rsi_14 - 50) DESC
        """,
        (ALERT_RSI_HIGH, ALERT_RSI_LOW, ALERT_BB_HIGH, ALERT_BB_LOW,
         ALERT_FOREIGN_Z, ALERT_FOREIGN_Z),
    )
    return [
        {"ticker_id": r[0], "company_name": r[1], "ai_pillar": r[2], "node": r[3],
         "rsi_14": r[4], "bb_pct_b": r[5], "foreign_net_z20": r[6],
         "macd_histogram": r[7], "pct_below_52w_high": r[8]}
        for r in c.fetchall()
    ]


def _format_signal_alert(s: dict) -> str:
    """One-line description of why a name tripped an alert threshold."""
    parts = []
    rsi = s.get("rsi_14")
    bb = s.get("bb_pct_b")
    fz = s.get("foreign_net_z20")
    if rsi is not None:
        if rsi > ALERT_RSI_HIGH:
            parts.append(f"RSI {rsi:.0f} (overbought)")
        elif rsi < ALERT_RSI_LOW:
            parts.append(f"RSI {rsi:.0f} (oversold)")
    if bb is not None:
        if bb > ALERT_BB_HIGH:
            parts.append(f"BB%B {bb:.2f} (above upper)")
        elif bb < ALERT_BB_LOW:
            parts.append(f"BB%B {bb:.2f} (below lower)")
    if fz is not None:
        if fz > ALERT_FOREIGN_Z:
            parts.append(f"foreign_z {fz:+.2f} (heavy buying)")
        elif fz < -ALERT_FOREIGN_Z:
            parts.append(f"foreign_z {fz:+.2f} (heavy selling)")
    return f"{s['ticker_id']} {s['company_name']} — " + ", ".join(parts)


def _write_digest(c, kind: str, title: str, body: str,
                  inputs: list[str], alerts: list[dict] | None = None) -> None:
    c.execute(
        """
        INSERT INTO daily_digest (digest_date, kind, title, body, source_inputs, alerts)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (digest_date, kind) DO UPDATE SET
            title = EXCLUDED.title,
            body = EXCLUDED.body,
            source_inputs = EXCLUDED.source_inputs,
            alerts = EXCLUDED.alerts,
            generated_at = now()
        """,
        (_today_taipei_iso(), kind, title, body, inputs,
         json.dumps(alerts) if alerts is not None else None),
    )


def _mark_telegram_sent(c, kind: str) -> None:
    c.execute(
        "UPDATE daily_digest SET telegram_sent_at = now() "
        "WHERE digest_date = %s AND kind = %s",
        (_today_taipei_iso(), kind),
    )


# ── Mode: pre_market ──────────────────────────────────────────────────────

def pre_market_brief() -> None:
    """Run at 07:30 Taipei (23:30 UTC). Summarises overnight US news +
    last close's signal extremes. Always sends Telegram."""
    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")

        # Overnight news = last 12h, prioritise classified-ticker mentions
        ticker_news = _query_news_for_classified(c, hours=12)
        general_news = _query_news_recent(c, hours=12, limit=10)
        extremes = _query_extreme_signals(c)

        lines = ["# Pre-market brief — " + _today_taipei_iso() + "\n"]
        lines.append(f"_Generated {datetime.now(_TPE).strftime('%H:%M %Z')} — overnight window 12h._\n")

        if ticker_news:
            lines.append("## Watchlist names in overnight news\n")
            for n in ticker_news[:8]:
                ts = n["ts"].astimezone(_TPE).strftime("%m-%d %H:%M") if n["ts"] else "—"
                lines.append(f"- **{n['ticker_id']} {n['company_name']}** [{n['source']}, {ts}] {n['title'][:120]}")
            lines.append("")
        else:
            lines.append("## Watchlist names in overnight news\n_None._\n")

        if extremes:
            lines.append("## Indicator extremes from yesterday's close\n")
            for s in extremes[:8]:
                lines.append(f"- {_format_signal_alert(s)}")
            lines.append("")
        else:
            lines.append("## Indicator extremes from yesterday's close\n_None tripping thresholds._\n")

        lines.append("## Macro/geo headlines (overnight)\n")
        for n in general_news[:5]:
            ts = n["ts"].astimezone(_TPE).strftime("%m-%d %H:%M") if n["ts"] else "—"
            lines.append(f"- [{n['source']}, {ts}] {n['title'][:120]}")

        body = "\n".join(lines)
        title = f"Pre-market — {_today_taipei_iso()}"
        alerts = [{"ticker": s["ticker_id"],
                   "reason": _format_signal_alert(s)} for s in extremes[:8]]

        _write_digest(c, "pre_market", title, body,
                      inputs=["raw_news", "view_latest_signals", "dim_supply_chain"],
                      alerts=alerts)

    # Telegram: short version
    short = (f"<b>Pre-market {_today_taipei_iso()}</b>\n"
             f"Watchlist news: {len(ticker_news)} • "
             f"Indicator extremes: {len(extremes)}\n")
    if extremes:
        short += "\n<b>Top extremes</b>:\n"
        for s in extremes[:3]:
            short += f"• {_format_signal_alert(s)}\n"
    if ticker_news:
        short += f"\n<b>Top headline</b>: {ticker_news[0]['title'][:120]}"
    send(short)
    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        _mark_telegram_sent(c, "pre_market")
    log.info("pre_market brief written + telegram sent")


# ── Mode: intraday ────────────────────────────────────────────────────────

def intraday_alerts() -> None:
    """Run at 10:00 / 12:00 / 14:30 Taipei. Sends Telegram ONLY if a
    classified ticker's signal stack tripped a hard threshold OR a news
    item explicitly named a classified ticker in the last hour."""
    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        extremes = _query_extreme_signals(c)
        # Only news from the last hour qualifies as "intraday news event"
        ticker_news = _query_news_for_classified(c, hours=1)

    if not extremes and not ticker_news:
        log.info("intraday: no alerts, no Telegram sent")
        return

    lines = [f"<b>Intraday alert {datetime.now(_TPE).strftime('%H:%M Taipei')}</b>\n"]
    if ticker_news:
        lines.append("\n<b>Watchlist mentioned in last 1h</b>:")
        for n in ticker_news[:5]:
            lines.append(f"• <b>{n['ticker_id']}</b> [{n['source']}] {n['title'][:100]}")
    if extremes:
        lines.append("\n<b>Indicator extremes (latest close)</b>:")
        for s in extremes[:5]:
            lines.append(f"• {_format_signal_alert(s)}")
    send("\n".join(lines))

    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        title = f"Intraday alert — {datetime.now(_TPE).strftime('%H:%M')}"
        body = "\n".join(lines).replace("<b>", "**").replace("</b>", "**")
        alerts = [
            *[{"kind": "news", "ticker": n["ticker_id"], "title": n["title"]} for n in ticker_news[:5]],
            *[{"kind": "signal", "ticker": s["ticker_id"], "reason": _format_signal_alert(s)} for s in extremes[:5]],
        ]
        # Append-style: digest_date+kind PK, but kind='intraday_alert' may
        # write multiple times in a day (10:00, 12:00, 14:30). The PK
        # collapses to one row; we keep the latest snapshot. Acceptable
        # since the Telegram log is the per-time record.
        _write_digest(c, "intraday_alert", title, body,
                      inputs=["raw_news", "view_latest_signals", "dim_supply_chain"],
                      alerts=alerts)
        _mark_telegram_sent(c, "intraday_alert")
    log.info("intraday alert sent: %d news + %d extremes", len(ticker_news), len(extremes))


# ── Mode: post_close ──────────────────────────────────────────────────────

def post_close_brief() -> None:
    """Run after the daily harvest at ~16:45 Taipei. Recap of today's
    moves, indicator deltas, and thesis-status pointer. Always sends Telegram."""
    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")

        # Today's flow (sector momentum view, freshly refreshed by the
        # daily pipeline before this brief runs)
        c.execute("""
          SELECT ai_pillar, node, foreign_5d, top_ticker_5d_name
          FROM view_sector_momentum
          WHERE ai_pillar != 'unclassified'
          ORDER BY foreign_5d DESC LIMIT 5
        """)
        sectors = [
            {"pillar": r[0], "node": r[1], "foreign_5d": float(r[2]) if r[2] else 0,
             "top": r[3]}
            for r in c.fetchall()
        ]

        extremes = _query_extreme_signals(c)
        # Today's news mentions of classified tickers
        ticker_news = _query_news_for_classified(c, hours=24)

        # Active theses count (file-based; cron has the repo checked out)
        theses_dir = Path("docs/theses")
        active_theses = 0
        if theses_dir.is_dir():
            for f in theses_dir.glob("*.md"):
                if f.name == "README.md":
                    continue
                # Lightweight: assume any non-README MD is a thesis. The
                # thesis_status job (separate) does the heavy lifting.
                active_theses += 1

    lines = ["# Post-close brief — " + _today_taipei_iso() + "\n"]
    lines.append(f"_Generated {datetime.now(_TPE).strftime('%H:%M %Z')}._\n")

    lines.append("## Top sectors by 5d foreign flow\n")
    for s in sectors:
        sign = "+" if s["foreign_5d"] >= 0 else ""
        lines.append(f"- **{s['pillar']}/{s['node']}** — {sign}{s['foreign_5d']:,.0f} shares 5d, top: {s['top']}")
    lines.append("")

    lines.append("## Names tripping thresholds\n")
    if extremes:
        for s in extremes[:8]:
            lines.append(f"- {_format_signal_alert(s)}")
    else:
        lines.append("_None._")
    lines.append("")

    lines.append(f"## News naming watchlist tickers (last 24h): {len(ticker_news)}\n")
    for n in ticker_news[:5]:
        lines.append(f"- {n['ticker_id']} {n['company_name']} [{n['source']}]: {n['title'][:120]}")

    lines.append(f"\n## Active theses: {active_theses}")
    if active_theses == 0:
        lines.append("\n_No active theses yet. Run `decide-on-ticker` Skill in Claude app to open one._")

    body = "\n".join(lines)
    title = f"Post-close — {_today_taipei_iso()}"

    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        _write_digest(c, "post_close", title, body,
                      inputs=["view_sector_momentum", "view_latest_signals", "raw_news"],
                      alerts=[{"ticker": s["ticker_id"], "reason": _format_signal_alert(s)} for s in extremes[:8]])

    # Telegram: short summary
    short = (f"<b>Post-close {_today_taipei_iso()}</b>\n"
             f"Top sector: <b>{sectors[0]['pillar']}/{sectors[0]['node']}</b> "
             f"(+{sectors[0]['foreign_5d']:,.0f} shares 5d)\n"
             f"Indicator extremes: {len(extremes)} • "
             f"Watchlist news: {len(ticker_news)}\n")
    if extremes:
        short += "\n<b>Notable</b>:\n"
        for s in extremes[:3]:
            short += f"• {_format_signal_alert(s)}\n"
    short += f"\nActive theses: {active_theses}"
    send(short)

    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        _mark_telegram_sent(c, "post_close")
    log.info("post_close brief written + telegram sent")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True,
                        choices=["pre_market", "intraday", "post_close"])
    args = parser.parse_args()
    if args.mode == "pre_market":
        pre_market_brief()
    elif args.mode == "intraday":
        intraday_alerts()
    elif args.mode == "post_close":
        post_close_brief()


if __name__ == "__main__":
    main()
