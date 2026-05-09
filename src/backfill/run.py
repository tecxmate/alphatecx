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
                tickers_df = transform.extract_supply_chain_tickers(df)
                # All three writes commit together — partial-batch failures
                # roll back, so retries see the day as un-ingested.
                with loader.atomic() as c:
                    count = loader.upsert_t86(df, c=c)
                    loader.upsert_supply_chain(tickers_df, c=c)
                    loader.log_ingestion("twse_t86", iso, count, c=c)
                total_rows += count
            else:
                log.info("  No data for %s (holiday?), skipping", d)
                loader.log_ingestion("twse_t86", iso, 0, "empty")
        except Exception as e:
            log.error("  Error on %s: %s", d, e)
            loader.log_ingestion("twse_t86", iso, 0, "error", str(e))
            errors += 1

        if i < len(dates) - 1:
            time.sleep(TWSE_REQUEST_DELAY)

    log.info("T86 backfill done: %d rows, %d skipped, %d errors", total_rows, skipped, errors)
    return {"source": "t86", "rows": total_rows, "skipped": skipped, "errors": errors}


def backfill_holdings(days: int) -> dict:
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
                with loader.atomic() as c:
                    count = loader.upsert_holdings(df, c=c)
                    loader.log_ingestion("twse_holdings", iso, count, c=c)
                total_rows += count
            else:
                log.info("  No data for %s, skipping", d)
                loader.log_ingestion("twse_holdings", iso, 0, "empty")
        except Exception as e:
            log.error("  Error on %s: %s", d, e)
            loader.log_ingestion("twse_holdings", iso, 0, "error", str(e))
            errors += 1

        if i < len(dates) - 1:
            time.sleep(TWSE_REQUEST_DELAY)

    log.info("Holdings backfill done: %d rows, %d skipped, %d errors", total_rows, skipped, errors)
    return {"source": "holdings", "rows": total_rows, "skipped": skipped, "errors": errors}


def backfill_margin(days: int) -> dict:
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
                with loader.atomic() as c:
                    count = loader.upsert_margin(df, c=c)
                    loader.log_ingestion("twse_margin", iso, count, c=c)
                total_rows += count
            else:
                log.info("  No data for %s, skipping", d)
                loader.log_ingestion("twse_margin", iso, 0, "empty")
        except Exception as e:
            log.error("  Error on %s: %s", d, e)
            loader.log_ingestion("twse_margin", iso, 0, "error", str(e))
            errors += 1

        if i < len(dates) - 1:
            time.sleep(TWSE_REQUEST_DELAY)

    log.info("Margin backfill done: %d rows, %d skipped, %d errors", total_rows, skipped, errors)
    return {"source": "margin", "rows": total_rows, "skipped": skipped, "errors": errors}


def _ohlcv_targets(context_count: int = 150) -> list[tuple[str, str]]:
    """Return [(ticker_id, market), ...] for OHLCV backfill.

    Includes:
      1. All classified tickers (dim_supply_chain) — primary signal universe.
      2. 0050 ETF benchmark.
      3. Top `context_count` unclassified tickers by T86 absolute flow,
         excluding ETFs/warrants (ticker_id >= 6 chars or starts '00').
         This populates the 3D correlation graph with a "grey background" so
         the AI cluster contrasts against the broader market.
    """
    benchmarks = [("0050", "TWSE")]
    with loader.cur() as c:
        c.execute("SELECT ticker_id, market FROM dim_supply_chain")
        classified = [(r[0], r[1]) for r in c.fetchall()]

        c.execute(
            """
            WITH active AS (
              SELECT ticker_id, market,
                     SUM(ABS(total_net))::bigint AS abs_flow_sum,
                     COUNT(*) AS days
              FROM raw_twse_t86
              GROUP BY ticker_id, market
              HAVING COUNT(*) >= 25
            )
            SELECT a.ticker_id, a.market
            FROM active a
            LEFT JOIN dim_ticker dt USING (ticker_id)
            WHERE COALESCE(dt.ai_pillar, '') = ''
              AND LENGTH(a.ticker_id) <= 5
              AND a.ticker_id NOT LIKE '00%%'
            ORDER BY a.abs_flow_sum DESC
            LIMIT %s
            """,
            (context_count,),
        )
        context = [(r[0], r[1]) for r in c.fetchall()]

    return sorted(set(classified + benchmarks + context))


def _ohlcv_already_have(ticker_id: str, year: int, month: int) -> bool:
    """True if raw_twse_ohlcv already has any row for this ticker in this month.

    Lighter than logging every (ticker, month) pair to ingestion_log —
    pollutes that table with thousands of rows for a long backfill.
    """
    with loader.cur() as c:
        c.execute(
            """
            SELECT 1 FROM raw_twse_ohlcv
            WHERE ticker_id = %s
              AND date >= make_date(%s, %s, 1)
              AND date <  (make_date(%s, %s, 1) + INTERVAL '1 month')
            LIMIT 1
            """,
            (ticker_id, year, month, year, month),
        )
        return c.fetchone() is not None


def backfill_ohlcv(months: int) -> dict:
    """Backfill daily OHLCV bars for the classified tickers + benchmarks.

    Iterates (ticker, year-month). The TWSE STOCK_DAY endpoint returns
    one stock's full month per call. ~28 tickers × 12 months = 336 calls
    at the rate-limit delay, so a full year takes ~17 minutes.
    """
    log.info("=== Backfilling OHLCV (%d months) ===", months)
    targets = _ohlcv_targets()
    log.info("OHLCV targets: %d tickers (%d classified + benchmarks)",
             len(targets), len(targets) - 1)

    today = date.today()
    month_pairs = []
    y, m = today.year, today.month
    for _ in range(months):
        month_pairs.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1

    total_rows = errors = skipped = 0
    iter_idx = 0
    total_iters = len(targets) * len(month_pairs)

    for ticker_id, market in targets:
        for year, month in month_pairs:
            iter_idx += 1
            if _ohlcv_already_have(ticker_id, year, month):
                skipped += 1
                continue

            log.info("[%d/%d] OHLCV %s %s %d-%02d",
                     iter_idx, total_iters, market, ticker_id, year, month)
            try:
                if market == "TWSE":
                    rows = twse.fetch_twse_ohlcv_month(ticker_id, year, month)
                else:
                    rows = twse.fetch_tpex_ohlcv_month(ticker_id, year, month)
                if rows:
                    df = transform.ohlcv_to_frame(rows)
                    count = loader.upsert_ohlcv(df)
                    total_rows += count
                # No log_ingestion per-month — would explode the log table.
                # Skip detection uses raw_twse_ohlcv directly.
            except Exception as e:
                log.error("  Error %s/%s %d-%02d: %s", market, ticker_id, year, month, e)
                errors += 1

            time.sleep(TWSE_REQUEST_DELAY)

    # Summary log entry — one row per backfill run, not per (ticker, month).
    loader.log_ingestion(
        "twse_ohlcv",
        date.today().isoformat(),
        total_rows,
        "ok" if errors == 0 else "partial",
        f"months={months} targets={len(targets)} skipped={skipped} errors={errors}",
    )

    log.info("OHLCV backfill done: %d rows, %d skipped, %d errors",
             total_rows, skipped, errors)
    return {"source": "ohlcv", "rows": total_rows, "skipped": skipped, "errors": errors}


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
                ym = rows[0].get("ym", "unknown") if rows else "unknown"
                log_date = f"{ym}-01" if ym != "unknown" else None
                with loader.atomic() as c:
                    count = loader.upsert_revenue(df, c=c)
                    loader.log_ingestion(f"mops_revenue_{market}", log_date, count, c=c)
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
    parser.add_argument("--only", choices=["t86", "holdings", "margin", "revenue", "ohlcv"],
                        help="Only run one specific backfill")
    parser.add_argument("--skip-t86", action="store_true",
                        help="Skip T86 backfill (do holdings/margin/revenue)")
    parser.add_argument("--ohlcv-months", type=int, default=12,
                        help="Months of OHLCV history (default: 12, only used with --only ohlcv)")
    args = parser.parse_args()

    results = []
    start = time.time()

    if args.only:
        if args.only == "t86":
            results.append(backfill_t86(args.days))
        elif args.only == "holdings":
            results.append(backfill_holdings(args.days))
        elif args.only == "margin":
            results.append(backfill_margin(args.days))
        elif args.only == "revenue":
            results.append(backfill_revenue())
        elif args.only == "ohlcv":
            results.append(backfill_ohlcv(args.ohlcv_months))
    else:
        if not args.skip_t86:
            results.append(backfill_t86(args.days))
        results.append(backfill_holdings(args.days))
        results.append(backfill_margin(args.days))
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
