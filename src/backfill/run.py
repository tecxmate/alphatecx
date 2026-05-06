#!/usr/bin/env python3
"""Backfill historical TWSE/TPEX data into Supabase.

Run once to load historical data. Safe to re-run — all upserts are idempotent.
Respects TWSE rate limits with configurable delays.

Usage:
    python -m src.backfill.run                    # default: 90 days T86
    python -m src.backfill.run --days 30          # override days
    python -m src.backfill.run --skip-t86         # skip T86, do others
    python -m src.backfill.run --only t86         # T86 only
    python -m src.backfill.run --only holdings    # holdings only
    python -m src.backfill.run --only margin      # margin only
    python -m src.backfill.run --only revenue     # revenue only
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date

from src.config import TWSE_BACKFILL_DAYS, TWSE_REQUEST_DELAY
from src.harvester import twse, transform, loader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-12s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")


def backfill_t86(days: int) -> dict:
    """Backfill T86 institutional flow for `days` trading days."""
    log.info("=== Backfilling T86 (%d trading days) ===", days)
    dates = twse.trading_days_range(days)
    already = loader.get_ingested_dates("twse_t86")
    total_rows = 0
    skipped = 0
    errors = 0

    for i, d in enumerate(dates):
        iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if iso in already:
            skipped += 1
            continue

        log.info("[%d/%d] T86 date=%s", i + 1, len(dates), d)
        try:
            rows = twse.fetch_all_t86(d)
            if rows:
                df = transform.t86_to_frame(rows)
                count = loader.upsert_t86(df)

                # Auto-seed dim_supply_chain from discovered tickers
                tickers_df = transform.extract_supply_chain_tickers(df)
                loader.upsert_supply_chain(tickers_df)

                loader.log_ingestion("twse_t86", iso, count)
                total_rows += count
            else:
                log.info("  No data for %s (holiday?), skipping", d)
        except Exception as e:
            log.error("  Error on %s: %s", d, e)
            loader.log_ingestion("twse_t86", iso, 0, "error", str(e))
            errors += 1

        if i < len(dates) - 1:
            time.sleep(TWSE_REQUEST_DELAY)

    log.info("T86 backfill done: %d rows, %d skipped, %d errors", total_rows, skipped, errors)
    return {"source": "t86", "rows": total_rows, "skipped": skipped, "errors": errors}


def backfill_holdings(days: int = 30) -> dict:
    """Backfill MI_QFIIS foreign holdings."""
    log.info("=== Backfilling Holdings (%d trading days) ===", days)
    dates = twse.trading_days_range(days)
    already = loader.get_ingested_dates("twse_holdings")
    total_rows = 0
    skipped = 0
    errors = 0

    for i, d in enumerate(dates):
        iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if iso in already:
            skipped += 1
            continue

        log.info("[%d/%d] Holdings date=%s", i + 1, len(dates), d)
        try:
            rows = twse.fetch_all_holdings(d)
            if rows:
                df = transform.holdings_to_frame(rows)
                count = loader.upsert_holdings(df)
                loader.log_ingestion("twse_holdings", iso, count)
                total_rows += count
            else:
                log.info("  No data for %s, skipping", d)
        except Exception as e:
            log.error("  Error on %s: %s", d, e)
            loader.log_ingestion("twse_holdings", iso, 0, "error", str(e))
            errors += 1

        if i < len(dates) - 1:
            time.sleep(TWSE_REQUEST_DELAY)

    log.info("Holdings backfill done: %d rows, %d skipped, %d errors", total_rows, skipped, errors)
    return {"source": "holdings", "rows": total_rows, "skipped": skipped, "errors": errors}


def backfill_margin(days: int = 30) -> dict:
    """Backfill margin balance data."""
    log.info("=== Backfilling Margin (%d trading days) ===", days)
    dates = twse.trading_days_range(days)
    already = loader.get_ingested_dates("twse_margin")
    total_rows = 0
    skipped = 0
    errors = 0

    for i, d in enumerate(dates):
        iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if iso in already:
            skipped += 1
            continue

        log.info("[%d/%d] Margin date=%s", i + 1, len(dates), d)
        try:
            rows = twse.fetch_all_margin(d)
            if rows:
                df = transform.margin_to_frame(rows)
                count = loader.upsert_margin(df)
                loader.log_ingestion("twse_margin", iso, count)
                total_rows += count
            else:
                log.info("  No data for %s, skipping", d)
        except Exception as e:
            log.error("  Error on %s: %s", d, e)
            loader.log_ingestion("twse_margin", iso, 0, "error", str(e))
            errors += 1

        if i < len(dates) - 1:
            time.sleep(TWSE_REQUEST_DELAY)

    log.info("Margin backfill done: %d rows, %d skipped, %d errors", total_rows, skipped, errors)
    return {"source": "margin", "rows": total_rows, "skipped": skipped, "errors": errors}


def backfill_revenue() -> dict:
    """Backfill monthly revenue (latest month only — MOPS has no historical API)."""
    log.info("=== Backfilling Monthly Revenue ===")
    total_rows = 0
    errors = 0

    for market in ("TWSE", "TPEX"):
        try:
            rows = twse.fetch_mops_revenue(market)
            if rows:
                df = transform.revenue_to_frame(rows)
                count = loader.upsert_revenue(df)
                ym = rows[0].get("ym", "unknown") if rows else "unknown"
                log_date = f"{ym}-01" if ym != "unknown" else None
                loader.log_ingestion(f"mops_revenue_{market}", log_date, count)
                total_rows += count
        except Exception as e:
            log.error("  Revenue error (%s): %s", market, e)
            loader.log_ingestion(f"mops_revenue_{market}", None, 0, "error", str(e))
            errors += 1
        time.sleep(TWSE_REQUEST_DELAY)

    log.info("Revenue backfill done: %d rows, %d errors", total_rows, errors)
    return {"source": "revenue", "rows": total_rows, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Backfill TWSE/TPEX data into Supabase")
    parser.add_argument("--days", type=int, default=TWSE_BACKFILL_DAYS,
                        help="Number of trading days to backfill (default: %(default)s)")
    parser.add_argument("--only", choices=["t86", "holdings", "margin", "revenue"],
                        help="Only run one specific backfill")
    parser.add_argument("--skip-t86", action="store_true",
                        help="Skip T86 backfill (do holdings/margin/revenue)")
    args = parser.parse_args()

    results = []
    start = time.time()

    if args.only:
        if args.only == "t86":
            results.append(backfill_t86(args.days))
        elif args.only == "holdings":
            results.append(backfill_holdings(min(args.days, 30)))
        elif args.only == "margin":
            results.append(backfill_margin(min(args.days, 30)))
        elif args.only == "revenue":
            results.append(backfill_revenue())
    else:
        if not args.skip_t86:
            results.append(backfill_t86(args.days))
        results.append(backfill_holdings(min(args.days, 30)))
        results.append(backfill_margin(min(args.days, 30)))
        results.append(backfill_revenue())

    # Refresh materialized views after all data is loaded
    try:
        log.info("Refreshing materialized views...")
        loader.refresh_views()
    except Exception as e:
        log.error("View refresh failed: %s", e)

    elapsed = time.time() - start
    log.info("=" * 60)
    log.info("Backfill complete in %.1f seconds", elapsed)
    for r in results:
        log.info("  %s: %d rows%s", r["source"], r["rows"],
                 f", {r.get('errors', 0)} errors" if r.get("errors") else "")


if __name__ == "__main__":
    main()
