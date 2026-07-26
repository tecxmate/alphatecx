#!/usr/bin/env python3
"""One-off / resumable FinMind backfill (Tool Review v2 Phase 2).

The nightly harvester only covers a bounded universe (classified + upcoming-ex)
to stay under FinMind's free 600 req/hr. This script backfills a wider set —
dividend policy + result (+ fill stats) + news — and is resumable: it skips
tickers that already have fill stats unless --force.

Usage:
    python scripts/backfill_finmind.py 2812 2707 2357        # explicit tickers
    python scripts/backfill_finmind.py --universe dividend   # all names with an ex-date
    python scripts/backfill_finmind.py --universe priced     # the scoreable universe
    python scripts/backfill_finmind.py --universe dividend --pace 6.2   # strict 600/hr

At the free tier's 600 req/hr (3 calls/ticker), a full ~700-name dividend
backfill is ~2100 calls — pass --pace 6.2 to stay strictly under the cap, or run
in chunks across the hour. Progress is logged per ticker.
"""
from __future__ import annotations

import argparse
import logging
import sys

from src.harvester import daily, finmind, loader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
log = logging.getLogger("backfill_finmind")

UNIVERSE_SQL = {
    "dividend": "SELECT DISTINCT ticker_id FROM raw_twse_dividend ORDER BY ticker_id",
    "priced": (
        "SELECT DISTINCT ticker_id FROM ("
        "  SELECT ticker_id FROM raw_twse_valuation "
        "  UNION SELECT ticker_id FROM raw_twse_ohlcv"
        ") u ORDER BY ticker_id"
    ),
    "classified": "SELECT ticker_id FROM dim_supply_chain ORDER BY ticker_id",
}


def _already_loaded() -> set[str]:
    with loader.cur() as c:
        c.execute("SELECT ticker_id FROM finmind_fill_stats")
        return {r[0] for r in c.fetchall()}


def _resolve_universe(name: str) -> list[str]:
    with loader.cur() as c:
        c.execute(UNIVERSE_SQL[name])
        return [r[0] for r in c.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*", help="explicit ticker ids")
    ap.add_argument("--universe", choices=sorted(UNIVERSE_SQL), help="ticker set")
    ap.add_argument("--pace", type=float, default=None,
                    help="seconds/call override (e.g. 6.2 for strict 600/hr)")
    ap.add_argument("--force", action="store_true", help="re-harvest already-loaded names")
    ap.add_argument("--news-days", type=int, default=45)
    args = ap.parse_args()

    if not finmind.token_configured():
        log.error("FINMIND_TOKEN not set — nothing to do")
        return 1
    if args.pace is not None:
        finmind.FINMIND_REQUEST_DELAY = args.pace  # type: ignore[attr-defined]

    tickers = list(args.tickers)
    if args.universe:
        tickers += _resolve_universe(args.universe)
    tickers = sorted(set(tickers))
    if not tickers:
        log.error("no tickers — pass ids or --universe")
        return 1

    if not args.force:
        loaded = _already_loaded()
        before = len(tickers)
        tickers = [t for t in tickers if t not in loaded]
        log.info("resuming: %d/%d remain (%d already loaded)", len(tickers), before, before - len(tickers))

    total = len(tickers)
    for i in range(0, total, 25):
        chunk = tickers[i:i + 25]
        res = daily.harvest_finmind(chunk, news_days=args.news_days)
        log.info("progress %d/%d — %s", min(i + 25, total), total, res)
    log.info("backfill complete: %d tickers", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
