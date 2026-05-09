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


def _active_theses() -> list[dict]:
    """Read frontmatter of any non-README MD in docs/theses/, return
    those with status: active. Idea borrowed from the dashboard schema
    in ZhuLinsen/daily_stock_analysis — surface explicit action items
    derived from open positions."""
    theses_dir = Path("docs/theses")
    if not theses_dir.is_dir():
        return []
    out: list[dict] = []
    for f in sorted(theses_dir.glob("*.md")):
        if f.name == "README.md":
            continue
        text = f.read_text()
        # Lightweight frontmatter parse — avoids pyyaml dep.
        if not text.startswith("---"):
            continue
        try:
            _, fm, _ = text.split("---", 2)
        except ValueError:
            continue
        meta: dict[str, str] = {}
        for line in fm.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        if meta.get("status") != "active":
            continue
        meta["_path"] = str(f.relative_to(Path(".")))
        out.append(meta)
    return out


def _watchlist() -> list[dict]:
    """Read active watchlist rows from the DB. Source of truth changed
    from docs/watchlist/active.md to the watchlist table in 007_watchlist.sql
    so the Telegram bot can mutate it directly."""
    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        c.execute("""
            SELECT ticker_id, company_name, ai_pillar, node, reason,
                   escalation_trigger, added_at::date
            FROM watchlist WHERE status = 'active'
            ORDER BY added_at DESC, ticker_id
        """)
        cols = ["ticker", "company", "ai_pillar", "node", "reason",
                "escalation_trigger", "added"]
        return [dict(zip(cols, row)) for row in c.fetchall()]


def _action_checklist(extremes: list[dict], ticker_news: list[dict],
                      theses: list[dict],
                      watchlist: list[dict]) -> list[str]:
    """Generate a 1-3 item do-list from the day's structured data.

    Priority order:
      1. Open theses (review trigger conditions today)
      2. Watchlist names that ALSO show extreme flow today (escalation candidate)
      3. Plain extreme foreign_z (not yet on watchlist)
      4. Top news event involving a watchlist or thesis ticker
    Capped at 3 items so Telegram messages stay scannable.
    """
    items: list[str] = []

    watchlist_tickers = {w.get("ticker") for w in watchlist}
    thesis_tickers = {t.get("ticker") for t in theses}

    # 1. Active thesis → read-the-thesis action.
    for t in theses[:1]:
        ticker = t.get("ticker", "?")
        company = t.get("company", "?")
        last_review = t.get("last_review", "?")
        items.append(
            f"Review thesis on {ticker} {company.split('/')[0].strip()}: "
            f"check trigger conditions vs today's close (last_review {last_review})"
        )

    # 2. Watchlist names with extreme flow today → escalation candidate.
    for s in extremes:
        if s["ticker_id"] not in watchlist_tickers:
            continue
        if s["ticker_id"] in thesis_tickers:
            continue
        fz = s.get("foreign_net_z20")
        if fz is None:
            continue
        direction = "buying" if fz > 0 else "selling"
        items.append(
            f"Escalation candidate: {s['ticker_id']} {s['company_name']} "
            f"on watchlist + foreign_z {fz:+.2f} ({direction}) — consider `decide-on-ticker`"
        )
        if len(items) >= 3:
            break

    # 3. Plain extremes (not on watchlist, not thesis'd).
    for s in extremes:
        if len(items) >= 3:
            break
        if s["ticker_id"] in watchlist_tickers or s["ticker_id"] in thesis_tickers:
            continue
        fz = s.get("foreign_net_z20")
        if fz is None or abs(fz) < 2.0:
            continue
        direction = "buying" if fz > 0 else "selling"
        items.append(
            f"Watch {s['ticker_id']} {s['company_name']}: foreign_z {fz:+.2f} "
            f"({direction}) — add to watchlist if it sustains"
        )

    # 4. Fall back to top news cross-reference.
    if len(items) < 3 and ticker_news:
        n = ticker_news[0]
        items.append(
            f"Cross-reference {n['ticker_id']} headline against own data: "
            f"{n['title'][:90]}"
        )

    if not items:
        items.append(
            "No actions — system quiet, no extremes or watchlist news in window"
        )

    return items[:3]


def _format_checklist(items: list[str]) -> str:
    return "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))


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

        # Watchlist + active theses are read once and passed into the
        # checklist generator. Both also surface as section snippets.
        theses = _active_theses()
        watchlist = _watchlist()

        if watchlist:
            lines.append("## Watchlist (escalation candidates)\n")
            for w in watchlist:
                lines.append(f"- **{w.get('ticker','?')} {w.get('company','?')}** "
                             f"({w.get('ai_pillar','?')}/{w.get('node','?')}, added {w.get('added','?')}) — "
                             f"{(w.get('reason') or '')[:160]}")
            lines.append("")

        checklist = _action_checklist(extremes, ticker_news, theses, watchlist)
        lines.append("## Action checklist\n")
        lines.append(_format_checklist(checklist) + "\n")

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

    # Telegram: short version + action checklist (the do-this-first lines)
    short = (f"<b>Pre-market {_today_taipei_iso()}</b>\n"
             f"Watchlist names: {len(watchlist)} • "
             f"News mentions: {len(ticker_news)} • "
             f"Extremes: {len(extremes)} • "
             f"Theses: {len(theses)}\n")
    if extremes:
        short += "\n<b>Top extremes</b>:\n"
        for s in extremes[:3]:
            short += f"• {_format_signal_alert(s)}\n"
    if ticker_news:
        short += f"\n<b>Top headline</b>: {ticker_news[0]['title'][:120]}\n"
    short += "\n<b>Actions</b>:\n" + _format_checklist(checklist)
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

def _discovery_candidates_from_snapshot(limit: int = 5) -> list[dict]:
    """Read the latest correlation-graph snapshot and return top discovery
    candidates (unclassified tickers clustering with a pillar). Empty list
    if the snapshot file isn't available — non-fatal."""
    snap_path = (Path(__file__).resolve().parents[2]
                 / "mcp_server" / "api" / "static" / "graph_snapshot.json")
    if not snap_path.exists():
        return []
    try:
        data = json.loads(snap_path.read_text())
    except Exception as e:
        log.warning("could not read snapshot: %s", e)
        return []
    return list(data.get("discovery", []))[:limit]


def _query_top_lead_lag(c, limit: int = 5) -> list[dict]:
    """Top forward-leading pairs from the latest lead_lag snapshot, restricted
    to high-confidence (gain > 0.05). Empty list if table is empty."""
    c.execute("""
        WITH coincident AS (
            SELECT upstream_id, downstream_id, correlation AS rho_0
              FROM lead_lag
             WHERE lag_days = 0
               AND asof = (SELECT MAX(asof) FROM lead_lag)
        ),
        forward AS (
            SELECT ll.upstream_id, ll.downstream_id, ll.lag_days, ll.correlation,
                   c.rho_0
              FROM lead_lag ll JOIN coincident c USING (upstream_id, downstream_id)
             WHERE ll.lag_days BETWEEN 1 AND 5
               AND ll.asof = (SELECT MAX(asof) FROM lead_lag)
        )
        SELECT f.upstream_id, up.company_name, f.downstream_id, dn.company_name,
               f.lag_days,
               ROUND(f.correlation::numeric, 2),
               ROUND((f.correlation - f.rho_0)::numeric, 2)
          FROM forward f
          LEFT JOIN dim_ticker up ON up.ticker_id = f.upstream_id
          LEFT JOIN dim_ticker dn ON dn.ticker_id = f.downstream_id
         WHERE f.correlation >= 0.4
           AND (f.correlation - f.rho_0) >= 0.05
         ORDER BY (f.correlation - f.rho_0) DESC
         LIMIT %s
    """, (limit,))
    return [
        {"up": r[0], "up_name": r[1], "down": r[2], "down_name": r[3],
         "lag": r[4], "rho_lag": float(r[5]), "gain": float(r[6])}
        for r in c.fetchall()
    ]


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

        # Active theses + watchlist — both feed the checklist
        theses = _active_theses()
        active_theses = len(theses)
        watchlist = _watchlist()

        # New: discovery candidates + top lead-lag pairs
        discovery = _discovery_candidates_from_snapshot(limit=5)
        leadlag = _query_top_lead_lag(c, limit=5)

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

    if watchlist:
        lines.append(f"\n## Watchlist ({len(watchlist)} names)")
        for w in watchlist:
            lines.append(f"- **{w.get('ticker','?')} {w.get('company','?')}** "
                         f"— {(w.get('reason') or '')[:140]}")

    lines.append(f"\n## Active theses: {active_theses}")
    if active_theses == 0:
        lines.append("\n_No active theses yet. Run `decide-on-ticker` Skill in Claude app to open one._")
    else:
        for t in theses:
            lines.append(f"- **{t.get('ticker','?')} {t.get('company','?')}** — "
                         f"horizon {t.get('horizon','?')}, last_review {t.get('last_review','?')} "
                         f"[{t['_path']}]")

    # New: discovery candidates from correlation graph
    if discovery:
        lines.append(f"\n## Discovery candidates ({len(discovery)})")
        lines.append("_Unclassified tickers tracking a classified pillar — possible "
                     "supply-chain peers worth investigating._\n")
        for c_ in discovery:
            sn = (c_.get("suggested_node") + " · ") if c_.get("suggested_node") else ""
            lines.append(f"- **{c_['ticker']} {c_['name']}** → "
                         f"{c_['suggested_pillar']} ({sn}ρ≈{c_['conviction']})")

    # New: lead-lag (top forward-leading pairs)
    if leadlag:
        lines.append(f"\n## Lead-lag signals ({len(leadlag)})")
        lines.append("_Upstream → downstream pairs where today's upstream move "
                     "predicts the downstream's move N days later._\n")
        for ll in leadlag:
            lines.append(f"- **{ll['up']} {ll['up_name'] or ''}** → "
                         f"**{ll['down']} {ll['down_name'] or ''}** at lag {ll['lag']}d "
                         f"(ρ={ll['rho_lag']}, gain {ll['gain']:+.2f})")

    # Action checklist last — derived from everything above.
    checklist = _action_checklist(extremes, ticker_news, theses, watchlist)
    lines.append("\n## Action checklist for tomorrow\n")
    lines.append(_format_checklist(checklist))

    body = "\n".join(lines)
    title = f"Post-close — {_today_taipei_iso()}"

    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        _write_digest(c, "post_close", title, body,
                      inputs=["view_sector_momentum", "view_latest_signals", "raw_news",
                              "graph_snapshot.json", "lead_lag"],
                      alerts=[{"ticker": s["ticker_id"], "reason": _format_signal_alert(s)} for s in extremes[:8]])

    # Telegram: short summary + action checklist
    short = (f"<b>Post-close {_today_taipei_iso()}</b>\n"
             f"Top sector: <b>{sectors[0]['pillar']}/{sectors[0]['node']}</b> "
             f"({'+' if sectors[0]['foreign_5d']>=0 else ''}{sectors[0]['foreign_5d']:,.0f} shares 5d)\n"
             f"Watchlist: {len(watchlist)} • "
             f"Theses: {active_theses} • "
             f"Extremes: {len(extremes)} • "
             f"News mentions: {len(ticker_news)}\n")
    if extremes:
        short += "\n<b>Notable</b>:\n"
        for s in extremes[:3]:
            short += f"• {_format_signal_alert(s)}\n"
    if discovery:
        short += "\n🔍 <b>Discovery candidates</b>:\n"
        for c_ in discovery[:3]:
            short += (f"• {c_['ticker']} {c_['name']} → "
                      f"{c_['suggested_pillar']} (ρ≈{c_['conviction']})\n")
    if leadlag:
        short += "\n🔗 <b>Lead-lag</b>:\n"
        for ll in leadlag[:3]:
            short += (f"• {ll['up']}→{ll['down']} lag {ll['lag']}d "
                      f"(ρ={ll['rho_lag']}, +{ll['gain']:.2f})\n")
    short += "\n<b>Actions for tomorrow</b>:\n" + _format_checklist(checklist)
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
