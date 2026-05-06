#!/usr/bin/env python3
"""Daily harvester — runs after market close to ingest today's data.

This is what GitHub Actions calls daily at 16:00+ CST.
Also usable standalone: python -m src.harvester.daily
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date

from src.harvester import twse, transform, loader
from src.alerts.telegram import send_daily_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-12s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("daily")


def harvest_today() -> dict:
    """Harvest all data sources for today (or most recent trading day)."""
    results = {"t86": 0, "holdings": 0, "margin": 0, "revenue": 0, "errors": []}

    # Find most recent trading day
    candidates = twse.trading_day_candidates(3)
    if not candidates:
        log.error("No trading day candidates found")
        return results

    target = candidates[0]  # most recent weekday
    iso = f"{target[:4]}-{target[4:6]}-{target[6:8]}"
    log.info("Daily harvest for date=%s", target)

    # 1. T86 Institutional Flow (Priority 1)
    try:
        log.info("Fetching T86...")
        rows = twse.fetch_all_t86(target)
        if rows:
            df = transform.t86_to_frame(rows)
            count = loader.upsert_t86(df)
            results["t86"] = count

            # Auto-seed any new tickers into dim_supply_chain
            tickers_df = transform.extract_supply_chain_tickers(df)
            loader.upsert_supply_chain(tickers_df)

            loader.log_ingestion("twse_t86", iso, count)
        else:
            log.warning("No T86 data for %s — might be a holiday", target)
    except Exception as e:
        log.error("T86 failed: %s", e)
        results["errors"].append(f"t86: {e}")
        loader.log_ingestion("twse_t86", iso, 0, "error", str(e))

    twse._rate_limit()

    # 2. Holdings (Priority 2)
    try:
        log.info("Fetching holdings...")
        rows = twse.fetch_all_holdings(target)
        if rows:
            df = transform.holdings_to_frame(rows)
            count = loader.upsert_holdings(df)
            results["holdings"] = count
            loader.log_ingestion("twse_holdings", iso, count)
    except Exception as e:
        log.error("Holdings failed: %s", e)
        results["errors"].append(f"holdings: {e}")

    twse._rate_limit()

    # 3. Margin (Priority 3)
    try:
        log.info("Fetching margin...")
        rows = twse.fetch_all_margin(target)
        if rows:
            df = transform.margin_to_frame(rows)
            count = loader.upsert_margin(df)
            results["margin"] = count
            loader.log_ingestion("twse_margin", iso, count)
    except Exception as e:
        log.error("Margin failed: %s", e)
        results["errors"].append(f"margin: {e}")

    twse._rate_limit()

    # 4. Revenue (Priority 5 — only changes monthly, but cheap to check)
    try:
        log.info("Fetching revenue...")
        for market in ("TWSE", "TPEX"):
            rows = twse.fetch_mops_revenue(market)
            if rows:
                df = transform.revenue_to_frame(rows)
                count = loader.upsert_revenue(df)
                results["revenue"] += count
            twse._rate_limit()
    except Exception as e:
        log.error("Revenue failed: %s", e)
        results["errors"].append(f"revenue: {e}")

    # 5. Refresh materialized views
    try:
        log.info("Refreshing materialized views...")
        loader.refresh_views()
    except Exception as e:
        log.error("View refresh failed: %s", e)
        results["errors"].append(f"views: {e}")

    # 6. Send Telegram alert
    try:
        send_daily_summary(iso, results)
    except Exception as e:
        log.error("Telegram alert failed: %s", e)

    log.info("Daily harvest complete: %s", results)
    return results


def main():
    harvest_today()


if __name__ == "__main__":
    main()
