#!/usr/bin/env python3
"""Daily harvester — runs after market close to ingest today's data.

This is what GitHub Actions calls daily at 16:30 Taipei. Also usable
standalone: ``python -m src.harvester.daily``.

Pipeline (each step failure-isolated; one bad step doesn't kill the rest):
    1. T86 institutional flow (atomic upsert + log)
    2. Foreign holdings (atomic upsert + log)
    3. Margin balance (atomic upsert + log)
    4. Monthly revenue (TWSE + TPEX)
    5. OHLCV — current month, classified tickers + benchmark
    6. News — RSS harvest from configured sources
    7. Refresh sector + ticker momentum matviews
    8. Compute price-derived quant signals (RSI/MACD/BB/ATR/SMA/RS/52w)
    9. Compute T86-derived flow signals (z-scores, 5d sums)
   10. Refresh view_latest_signals matview
   11. Telegram daily-summary alert
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from src.alerts.telegram import send_daily_summary
from src.harvester import finmind, loader, transform, twse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-12s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("daily")

# Benchmark for relative-strength calculation. Same as src/quant/compute_signals.py.
_BENCHMARK = "0050"


def _finmind_nightly_universe(c) -> list[str]:
    """Bounded universe for the nightly FinMind harvest — kept well under the
    free tier's 600 req/hr (3 calls/ticker). Covers the classified names plus any
    name with an upcoming ex-date (where dividend_trap / news matter most now).
    A full-market backfill is scripts/backfill_finmind.py, not this."""
    c.execute(
        """
        SELECT DISTINCT ticker_id FROM (
            SELECT ticker_id FROM dim_supply_chain
            UNION
            SELECT ticker_id FROM raw_twse_dividend WHERE ex_date >= CURRENT_DATE
        ) u ORDER BY ticker_id
        """
    )
    return [r[0] for r in c.fetchall()]


def harvest_finmind(tickers: list[str], news_days: int = 45,
                    as_of: str | None = None) -> dict:
    """Harvest FinMind dividend policy + result + news for `tickers` into Neon.

    Reused by both the nightly step and scripts/backfill_finmind.py. Skips
    cleanly (no error) when no token is configured. Per-ticker: 3 rate-limited
    calls; fill_probability is computed here (pure) and stored.
    """
    if not finmind.token_configured():
        log.info("FinMind token not configured — skipping FinMind harvest")
        return {"skipped": "no_token"}
    as_of = as_of or date.today().isoformat()
    news_start = (date.today() - timedelta(days=news_days)).isoformat()
    div_rows: list = []
    res_rows: list = []
    fill_rows: list = []
    news_rows: list = []
    for t in tickers:
        pol = finmind.fetch_dividend_policy(t)
        finmind._rate_limit()
        res = finmind.fetch_dividend_result(t)
        finmind._rate_limit()
        news = finmind.fetch_news(t, news_start)
        finmind._rate_limit()
        div_rows += pol
        res_rows += res
        fill_rows.append(finmind.fill_stats_record(t, res, as_of))
        news_rows += news
    with loader.atomic() as c:
        loader.upsert_finmind_dividend(div_rows, c=c)
        loader.upsert_finmind_dividend_result(res_rows, c=c)
        loader.upsert_finmind_fill_stats(fill_rows, c=c)
        loader.upsert_finmind_news(news_rows, c=c)
    return {"tickers": len(tickers), "dividend": len(div_rows),
            "result": len(res_rows), "news": len(news_rows)}


def _harvest_ohlcv_current_month(target: str) -> int:
    """Re-fetch the current month for every classified ticker + benchmark.

    Per-month is the smallest TWSE STOCK_DAY granularity; idempotent
    upsert means re-fetching this month every day costs us a few
    rate-limited round trips and adds the new day's bar. Skip-detection
    that backfill_ohlcv uses doesn't fit this pattern (it would skip the
    month entirely if any rows exist).
    """
    year = int(target[:4])
    month = int(target[4:6])
    log.info("OHLCV current-month: %d-%02d", year, month)

    with loader.cur() as c:
        c.execute("SELECT ticker_id, market FROM dim_supply_chain ORDER BY ticker_id")
        targets = [(r[0], r[1]) for r in c.fetchall()]
    targets.append((_BENCHMARK, "TWSE"))

    total_rows = 0
    errors = 0
    for ticker_id, market in targets:
        try:
            if market == "TWSE":
                rows = twse.fetch_twse_ohlcv_month(ticker_id, year, month)
            else:
                rows = twse.fetch_tpex_ohlcv_month(ticker_id, year, month)
            if rows:
                df = transform.ohlcv_to_frame(rows)
                count = loader.upsert_ohlcv(df)
                total_rows += count
        except Exception as e:
            log.warning("  OHLCV %s/%s failed: %s", market, ticker_id, e)
            errors += 1
        twse._rate_limit()

    log.info("OHLCV current-month: %d rows upserted, %d errors", total_rows, errors)
    return total_rows


def _compute_quant_signals() -> None:
    """Recompute price + flow signals; refresh view_latest_signals."""
    # Imports are deferred so a daily run that doesn't reach this stage
    # (e.g. a missing OHLCV table during early bootstrap) doesn't fail
    # earlier steps with an ImportError.
    from src.quant import compute_flow_signals as flow_signals
    from src.quant import compute_signals as price_signals

    log.info("Computing price-derived signals...")
    price_signals.main()  # writes signal_value rows + refreshes matview

    log.info("Computing flow-derived signals...")
    flow_signals.main()


def _harvest_news() -> dict:
    from src.news.harvest import harvest
    log.info("Harvesting news sources...")
    return harvest()


# How many recent sessions the margin catch-up will re-attempt per run. Small
# on purpose: each one costs two rate-limited requests, and a longer outage is
# a job for `python -m src.backfill.run --only margin`, not the nightly path.
_MARGIN_CATCHUP_LIMIT = 3


def _margin_catchup(target: str, limit: int = _MARGIN_CATCHUP_LIMIT) -> list[str]:
    """Recent sessions still missing margin rows, as YYYYMMDD, oldest first.

    `target` is dropped: today's session is fetched by the main path and would
    otherwise be requested twice. Never fatal — a failure here must not cost
    the run its normal margin fetch.
    """
    try:
        missing = loader.margin_sessions_missing(days=10)
    except Exception as e:
        log.warning("Margin catch-up lookup failed: %s", e)
        return []
    return [d.replace("-", "") for d in missing if d.replace("-", "") != target][:limit]


def harvest_today() -> dict:
    """Run the full daily pipeline. Each stage is failure-isolated —
    one stage's exception is logged and recorded but doesn't abort the
    others. The Telegram summary at the end shows what succeeded."""
    results = {
        "t86": 0, "holdings": 0, "margin": 0, "revenue": 0,
        "ohlcv": 0, "valuation": 0, "indices": 0, "news_new": 0, "errors": [],
    }

    # Find most recent trading day from TWSE's calendar logic.
    candidates = twse.trading_day_candidates(3)
    if not candidates:
        log.error("No trading day candidates found")
        return results

    target = candidates[0]  # most recent weekday
    iso = f"{target[:4]}-{target[4:6]}-{target[6:8]}"
    log.info("=== Daily harvest for date=%s ===", target)

    # ── 1. T86 Institutional Flow ─────────────────────────────────────────
    try:
        rows = twse.fetch_all_t86(target)
        if rows:
            df = transform.t86_to_frame(rows)
            tickers_df = transform.extract_supply_chain_tickers(df)
            with loader.atomic() as c:
                count = loader.upsert_t86(df, c=c)
                loader.upsert_supply_chain(tickers_df, c=c)
                loader.log_ingestion("twse_t86", iso, count, c=c)
            results["t86"] = count
        else:
            log.warning("No T86 data for %s — might be a holiday", target)
            loader.log_ingestion("twse_t86", iso, 0, "empty")
    except Exception as e:
        log.error("T86 failed: %s", e)
        results["errors"].append(f"t86: {e}")
        loader.log_ingestion("twse_t86", iso, 0, "error", str(e))
    twse._rate_limit()

    # ── 2. Foreign Holdings ───────────────────────────────────────────────
    try:
        rows = twse.fetch_all_holdings(target)
        if rows:
            df = transform.holdings_to_frame(rows)
            with loader.atomic() as c:
                count = loader.upsert_holdings(df, c=c)
                loader.log_ingestion("twse_holdings", iso, count, c=c)
            results["holdings"] = count
        else:
            loader.log_ingestion("twse_holdings", iso, 0, "empty")
    except Exception as e:
        log.error("Holdings failed: %s", e)
        results["errors"].append(f"holdings: {e}")
    twse._rate_limit()

    # ── 3. Margin Balance ─────────────────────────────────────────────────
    # Today's session first, then a catch-up over recent sessions that still
    # have no rows. TWSE publishes 融資融券彙總 after this job's 16:30 window,
    # so `target` routinely comes back empty and only lands on a later run.
    # Without the sweep that day is simply lost: between ~2026-07-01 and 07-30
    # every session went missing this way while T86 ingested normally, and M1's
    # margin subitem scored blind for a month without anything surfacing it.
    for i, day in enumerate([target] + _margin_catchup(target)):
        day_iso = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
        if i:
            twse._rate_limit()
        try:
            rows = twse.fetch_all_margin(day)
            if rows:
                df = transform.margin_to_frame(rows)
                with loader.atomic() as c:
                    count = loader.upsert_margin(df, c=c)
                    loader.log_ingestion("twse_margin", day_iso, count, c=c)
                if day == target:
                    results["margin"] = count
                else:
                    results["margin_backfilled"] = (
                        results.get("margin_backfilled", 0) + count)
                    log.info("Margin catch-up %s: %d rows", day_iso, count)
            else:
                # Not yet published, or a genuinely closed day. Either way this
                # is retryable — get_ingested_dates decides which, by calendar.
                loader.log_ingestion("twse_margin", day_iso, 0, "empty")
        except Exception as e:
            log.error("Margin %s failed: %s", day_iso, e)
            results["errors"].append(f"margin {day_iso}: {e}")
            loader.log_ingestion("twse_margin", day_iso, 0, "error", str(e))
    twse._rate_limit()

    # ── 4. Monthly Revenue (only changes around month boundaries) ─────────
    try:
        for market in ("TWSE", "TPEX"):
            rows = twse.fetch_mops_revenue(market)
            if rows:
                df = transform.revenue_to_frame(rows)
                ym = rows[0].get("ym", "unknown") if rows else "unknown"
                log_date = f"{ym}-01" if ym != "unknown" else None
                with loader.atomic() as c:
                    count = loader.upsert_revenue(df, c=c)
                    loader.log_ingestion(f"mops_revenue_{market}", log_date, count, c=c)
                results["revenue"] += count
            twse._rate_limit()
    except Exception as e:
        log.error("Revenue failed: %s", e)
        results["errors"].append(f"revenue: {e}")

    # ── 5. OHLCV current month ────────────────────────────────────────────
    try:
        results["ohlcv"] = _harvest_ohlcv_current_month(target)
    except Exception as e:
        log.error("OHLCV failed: %s", e)
        results["errors"].append(f"ohlcv: {e}")

    # ── 5a. Valuation (P/E, P/B, dividend yield) — single TWSE-wide call ──
    try:
        rows = twse.fetch_twse_valuation(target)
        if rows:
            df = transform.valuation_to_frame(rows)
            with loader.atomic() as c:
                count = loader.upsert_valuation(df, c=c)
                loader.log_ingestion("twse_valuation", iso, count, c=c)
            results["valuation"] = count
        else:
            loader.log_ingestion("twse_valuation", iso, 0, "empty")
    except Exception as e:
        log.error("Valuation failed: %s", e)
        results["errors"].append(f"valuation: {e}")
    twse._rate_limit()

    # ── 5b. Sector + cross-market indices ─────────────────────────────────
    try:
        rows = twse.fetch_twse_indices(target)
        if rows:
            df = transform.indices_to_frame(rows)
            with loader.atomic() as c:
                count = loader.upsert_indices(df, c=c)
                loader.log_ingestion("twse_index", iso, count, c=c)
            results["indices"] = count
        else:
            loader.log_ingestion("twse_index", iso, 0, "empty")
    except Exception as e:
        log.error("Indices failed: %s", e)
        results["errors"].append(f"indices: {e}")
    twse._rate_limit()

    # ── 5c. Market calendar (holidays) — cheap; keeps session_state honest ──
    # Current + next Gregorian year so forward dates near year-end resolve, and
    # any typhoon closure TWSE adds to the schedule gets picked up daily.
    try:
        from datetime import date as _date
        yr = _date.today().year
        cal_rows = twse.fetch_twse_holidays(yr) + twse.fetch_twse_holidays(yr + 1)
        if cal_rows:
            with loader.atomic() as c:
                count = loader.upsert_market_holidays(cal_rows, c=c)
                loader.log_ingestion("twse_holidays", iso, count, c=c)
            results["holidays"] = count
        else:
            loader.log_ingestion("twse_holidays", iso, 0, "empty")
    except Exception as e:
        log.error("Holiday calendar failed: %s", e)
        results["errors"].append(f"holidays: {e}")
    twse._rate_limit()

    # ── 5d. Ex-dividend calendar — actual (this + prev month) + forecast ────
    # TWT49U times out on wide ranges during peak ex-dividend season, so query
    # per calendar month rather than one long span.
    try:
        from datetime import date as _d
        from datetime import timedelta as _td
        today = _d.today()
        prev_month_end = today.replace(day=1) - _td(days=1)
        div_rows: list = []
        for anchor in (prev_month_end, today):
            m_start = anchor.replace(day=1).strftime("%Y%m%d")
            m_end = anchor.strftime("%Y%m%d")
            div_rows += twse.fetch_twse_ex_dividend(m_start, m_end)
            twse._rate_limit()
        div_rows += twse.fetch_twse_ex_forecast()
        if div_rows:
            with loader.atomic() as c:
                count = loader.upsert_dividends(div_rows, c=c)
                loader.log_ingestion("twse_dividend", iso, count, c=c)
            results["dividends"] = count
        else:
            loader.log_ingestion("twse_dividend", iso, 0, "empty")
    except Exception as e:
        log.error("Dividend calendar failed: %s", e)
        results["errors"].append(f"dividends: {e}")
    twse._rate_limit()

    # ── 5e. FinMind enrichment — cash/stock split, 填息 prob, governance news ──
    # Bounded universe (classified + upcoming-ex) to stay under the free tier's
    # 600 req/hr. Full-market coverage is scripts/backfill_finmind.py.
    try:
        with loader.cur() as c:
            fm_universe = _finmind_nightly_universe(c)
        fm_res = harvest_finmind(fm_universe, as_of=iso)
        results["finmind"] = fm_res
        loader.log_ingestion("finmind", iso, fm_res.get("dividend", 0))
    except Exception as e:
        log.error("FinMind harvest failed: %s", e)
        results["errors"].append(f"finmind: {e}")

    # ── 6. News ───────────────────────────────────────────────────────────
    try:
        news_summary = _harvest_news()
        results["news_new"] = news_summary.get("new", 0)
    except Exception as e:
        log.error("News harvest failed: %s", e)
        results["errors"].append(f"news: {e}")

    # ── 7. Refresh sector + ticker momentum matviews (sc_* tools) ─────────
    try:
        log.info("Refreshing sector/ticker momentum matviews...")
        loader.refresh_views()
    except Exception as e:
        log.error("Sector/ticker view refresh failed: %s", e)
        results["errors"].append(f"sc_views: {e}")

    # ── 8 + 9 + 10. Quant signals + view_latest_signals refresh ───────────
    try:
        _compute_quant_signals()
    except Exception as e:
        log.error("Quant signal compute failed: %s", e)
        results["errors"].append(f"quant_signals: {e}")

    # ── 11. Telegram alert ────────────────────────────────────────────────
    try:
        send_daily_summary(iso, results)
    except Exception as e:
        log.error("Telegram alert failed: %s", e)

    log.info("=== Daily harvest complete: %s ===", results)
    return results


def main():
    harvest_today()


if __name__ == "__main__":
    main()
