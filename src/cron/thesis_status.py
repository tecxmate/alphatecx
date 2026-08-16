#!/usr/bin/env python3
"""Daily thesis-status heartbeat.

For each thesis under docs/theses/ with status:active in frontmatter, pull
current signals from view_latest_signals and the OHLCV close from the most
recent trading day, compute key deltas vs the thesis open date, and post a
single Telegram message + a row in daily_digest (kind='thesis_status').

We deliberately don't try to evaluate the prose `catalyst:` and
`invalidation:` fields programmatically — those are written for humans /
LLMs to read. The cron's job is to present the raw metrics that those
clauses care about (price, RSI, foreign_net_z20, SMA-50, etc.), so the
user can scan in 30 seconds whether anything tripped.

Run:
    python -m src.cron.thesis_status              # send + persist
    python -m src.cron.thesis_status --dry-run    # print only
"""
from __future__ import annotations

import argparse
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from src.alerts.telegram import send

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]
THESES_DIR = Path(__file__).resolve().parents[2] / "docs" / "theses"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("thesis_status")


# ── frontmatter parsing ────────────────────────────────────────────────────
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict:
    m = _FM_RE.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def load_active_theses() -> list[tuple[Path, dict, str]]:
    out = []
    if not THESES_DIR.exists():
        return out
    for p in sorted(THESES_DIR.glob("*.md")):
        if p.name == "README.md":
            continue
        text = p.read_text()
        fm = parse_frontmatter(text)
        if fm.get("status", "").lower() != "active":
            continue
        out.append((p, fm, text))
    return out


# ── DB queries ─────────────────────────────────────────────────────────────
def fetch_current(conn, ticker_id: str) -> dict:
    """Latest signals + most recent close for a ticker."""
    out = {}
    with conn.cursor() as c:
        c.execute("""
            SELECT ls.as_of, ls.rsi_14, ls.macd_histogram, ls.bb_pct_b,
                   ls.sma_50, ls.sma_200, ls.foreign_net_z20,
                   ls.foreign_net_5d_sum, ls.pct_below_52w_high,
                   ls.rs_vs_market_60
              FROM view_latest_signals ls
             WHERE ls.ticker_id = %s
        """, (ticker_id,))
        row = c.fetchone()
        if row:
            out.update({
                "signals_as_of": row[0],
                "rsi_14": row[1], "macd_hist": row[2], "bb_pct_b": row[3],
                "sma_50": row[4], "sma_200": row[5],
                "foreign_net_z20": row[6], "foreign_net_5d_sum": row[7],
                "pct_below_52w_high": row[8], "rs_vs_market_60": row[9],
            })
        c.execute("""
            SELECT date, close FROM raw_twse_ohlcv
             WHERE ticker_id = %s AND close IS NOT NULL
             ORDER BY date DESC LIMIT 1
        """, (ticker_id,))
        row = c.fetchone()
        if row:
            out["price_as_of"] = row[0]
            out["price_close"] = float(row[1])
    return out


def fetch_close_at(conn, ticker_id: str, on: date) -> float | None:
    """Most recent close on or before `on`."""
    with conn.cursor() as c:
        c.execute("""
            SELECT close FROM raw_twse_ohlcv
             WHERE ticker_id = %s AND date <= %s AND close IS NOT NULL
             ORDER BY date DESC LIMIT 1
        """, (ticker_id, on))
        row = c.fetchone()
    return float(row[0]) if row else None


# ── formatting ─────────────────────────────────────────────────────────────
def _pct(x):
    if x is None:
        return "—"
    return f"{x*100:+.1f}%"


def _num(x, prec=2):
    if x is None:
        return "—"
    return f"{x:.{prec}f}"


def _fmt_int_thousands(x):
    if x is None:
        return "—"
    return f"{int(x):,}"


def format_thesis_block(fm: dict, current: dict, opened_close: float | None) -> str:
    ticker = fm.get("ticker", "?")
    company = fm.get("company", "")
    opened = fm.get("opened", "")
    horizon = fm.get("horizon", "")
    naive = fm.get("naive_conviction", "?")
    aware = fm.get("aware_conviction", "?")
    catalyst = fm.get("catalyst", "")
    invalidation = fm.get("invalidation", "")

    days_open = "?"
    try:
        d_open = datetime.strptime(opened, "%Y-%m-%d").date()
        days_open = (date.today() - d_open).days
    except Exception:
        pass

    cur_close = current.get("price_close")
    pct_since = None
    if cur_close is not None and opened_close:
        pct_since = (cur_close / opened_close) - 1.0

    sma_50 = current.get("sma_50")
    above_sma50 = ""
    if cur_close is not None and sma_50 is not None:
        gap = (cur_close - sma_50) / sma_50
        above_sma50 = f" ({_pct(gap)} vs SMA-50)"

    lines = [
        f"<b>{ticker}</b> {company}",
        f"  opened {opened} ({days_open}d) · horizon {horizon} · "
        f"conviction naive={naive}/aware={aware}",
        f"  price {_num(cur_close)} ({_pct(pct_since)} since open){above_sma50}",
        f"  RSI {_num(current.get('rsi_14'),1)}  ·  "
        f"foreign_z {_num(current.get('foreign_net_z20'),2)}  ·  "
        f"foreign_5d {_fmt_int_thousands(current.get('foreign_net_5d_sum'))}",
    ]
    if catalyst:
        lines.append(f"  📈 catalyst: {catalyst[:140]}")
    if invalidation:
        lines.append(f"  🚫 invalidation: {invalidation[:140]}")
    return "\n".join(lines)


def build_message(reports: list[dict]) -> str:
    today = date.today().isoformat()
    if not reports:
        return f"📋 Thesis status — {today}\n\nNo active theses. Nothing to track."
    n = len(reports)
    body = "\n\n".join(r["text"] for r in reports)
    return (f"📋 <b>Thesis status</b> — {today}\n"
            f"<i>{n} active thesis{'es' if n != 1 else ''}</i>\n\n"
            + body
            + "\n\n<i>Catalyst/invalidation are prose — read against current "
              "metrics above and decide if anything tripped.</i>")


# ── persistence ────────────────────────────────────────────────────────────
def persist_digest(conn, message: str, payload: list[dict]) -> None:
    """Insert one row into daily_digest with kind='thesis_status'."""
    with conn.cursor() as c:
        c.execute("""
            INSERT INTO daily_digest (digest_date, kind, body, inputs, telegram_sent_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (digest_date, kind) DO UPDATE SET
                body = EXCLUDED.body,
                inputs = EXCLUDED.inputs,
                telegram_sent_at = now()
        """, (date.today(), "thesis_status", message,
              ["docs/theses", "view_latest_signals", "raw_twse_ohlcv"]))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print to stdout only; do not send Telegram or persist")
    args = ap.parse_args()

    theses = load_active_theses()
    log.info("active theses: %d", len(theses))

    reports = []
    with psycopg.connect(DATABASE_URL) as conn:
        for path, fm, _text in theses:
            ticker = fm.get("ticker")
            if not ticker:
                log.warning("skipping %s — no ticker in frontmatter", path.name)
                continue
            current = fetch_current(conn, ticker)
            opened_str = fm.get("opened", "")
            opened_close = None
            try:
                d_open = datetime.strptime(opened_str, "%Y-%m-%d").date()
                opened_close = fetch_close_at(conn, ticker, d_open)
            except Exception:
                pass
            block = format_thesis_block(fm, current, opened_close)
            reports.append({"ticker": ticker, "fm": fm, "text": block,
                            "current": current})

        message = build_message(reports)

        if args.dry_run:
            print(message)
            return

        persist_digest(conn, message, reports)

    send(message)
    log.info("thesis_status sent — %d theses summarised", len(reports))


if __name__ == "__main__":
    main()
