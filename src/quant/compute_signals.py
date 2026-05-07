"""Compute quant indicators for every classified ticker, persist to signal_value.

Run after OHLCV ingest:
    python -m src.quant.compute_signals               # all classified tickers
    python -m src.quant.compute_signals --ticker 2330 # one ticker

Idempotent: ON CONFLICT DO UPDATE. Re-runs overwrite stale values.

Signal naming convention (used in signal_value.signal_name):
  rsi_14, macd_line, macd_signal_line, macd_histogram,
  bb_pct_b, atr_14, sma_50, sma_200, rs_vs_market_60
"""
from __future__ import annotations

import argparse
import logging
from typing import Optional

import polars as pl

from src.harvester.loader import cur, atomic
from src.quant import indicators as ind

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("compute_signals")

# Benchmark ticker for relative-strength calculation.
BENCHMARK = "0050"

# Signal -> (column expression, requires_benchmark)
# Adding a new indicator: implement in indicators.py, then list it here.
# That's the single source of truth — `view_latest_signals` should also
# include the new column if you want it in the wide-form snapshot.
SIGNAL_NAMES = [
    "rsi_14", "macd_line", "macd_signal_line", "macd_histogram",
    "bb_pct_b", "atr_14", "sma_50", "sma_200", "rs_vs_market_60",
]


def _read_ohlcv(ticker_id: str, c) -> pl.DataFrame:
    """Read full OHLCV history for a ticker as a typed Polars frame."""
    c.execute(
        """
        SELECT date, open, high, low, close, volume_shares
        FROM raw_twse_ohlcv WHERE ticker_id = %s ORDER BY date
        """,
        (ticker_id,),
    )
    rows = c.fetchall()
    if not rows:
        return pl.DataFrame()
    cols = [d.name for d in c.description]
    return pl.DataFrame(rows, schema=cols, orient="row")


def _classified_tickers(c) -> list[str]:
    c.execute("SELECT ticker_id FROM dim_supply_chain ORDER BY ticker_id")
    return [r[0] for r in c.fetchall()]


def compute_for_ticker(ticker_id: str, benchmark_close_by_date: dict, c) -> int:
    """Compute all indicators for one ticker; upsert into signal_value.

    `benchmark_close_by_date` is a {date -> close} mapping for the benchmark
    so we can align RS calculation without re-reading the benchmark frame.

    Returns the number of (signal, date) pairs written.
    """
    df = _read_ohlcv(ticker_id, c)
    if df.is_empty() or df.height < 30:
        # Need at least 30 bars for any indicator to stabilize. 200-day SMA
        # will be all-NaN until 200 bars accumulate; we still write what we
        # can compute.
        log.info("  %s: only %d bars, skipping",
                 ticker_id, 0 if df.is_empty() else df.height)
        return 0

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Align benchmark close to this ticker's date index. Missing dates → null.
    aligned_bench = pl.Series(
        "bench_close",
        [benchmark_close_by_date.get(d) for d in df["date"].to_list()],
    )

    # Compute every indicator once.
    rsi14 = ind.rsi(close, 14)
    macd_line, signal_line, hist = ind.macd(close)
    pctb = ind.bollinger_pct_b(close, 20, 2.0)
    atr14 = ind.atr(high, low, close, 14)
    sma50 = ind.sma(close, 50)
    sma200 = ind.sma(close, 200)
    rs60 = ind.relative_strength(close, aligned_bench, 60)

    # Pivot to long form: one row per (signal_name, ticker, date). Skip null
    # values — they're just "indicator hasn't stabilized yet" and would
    # waste a row.
    long_form: list[tuple[str, str, object, float]] = []
    series_by_name = {
        "rsi_14": rsi14,
        "macd_line": macd_line,
        "macd_signal_line": signal_line,
        "macd_histogram": hist,
        "bb_pct_b": pctb,
        "atr_14": atr14,
        "sma_50": sma50,
        "sma_200": sma200,
        "rs_vs_market_60": rs60,
    }
    dates = df["date"].to_list()
    for name, series in series_by_name.items():
        for d, v in zip(dates, series.to_list()):
            if v is None:
                continue
            # NaN check via != self trick (works for numeric NaN)
            if v != v:
                continue
            long_form.append((name, ticker_id, d, float(v)))

    if not long_form:
        return 0

    sql = """
        INSERT INTO signal_value (signal_name, ticker_id, date, value)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (signal_name, ticker_id, date) DO UPDATE SET
            value = EXCLUDED.value,
            computed_at = now()
    """
    c.executemany(sql, long_form)
    return len(long_form)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", help="Compute for one ticker only")
    args = parser.parse_args()

    with atomic() as c:
        c.execute("SET search_path TO public, neon_auth")

        # Pre-load benchmark close series once for RS calculation.
        c.execute(
            "SELECT date, close FROM raw_twse_ohlcv WHERE ticker_id = %s ORDER BY date",
            (BENCHMARK,),
        )
        benchmark_close_by_date = {row[0]: float(row[1]) for row in c.fetchall()}
        log.info("Benchmark %s: %d bars loaded", BENCHMARK, len(benchmark_close_by_date))

        tickers = [args.ticker] if args.ticker else _classified_tickers(c)
        log.info("Computing signals for %d ticker(s)", len(tickers))

        total = 0
        for tid in tickers:
            n = compute_for_ticker(tid, benchmark_close_by_date, c)
            log.info("  %s: %d signal-rows", tid, n)
            total += n

        log.info("Total signal-rows written: %d", total)

    # Refresh the wide-form snapshot view so MCP queries see fresh data.
    with cur() as c:
        c.execute("SET search_path TO public, neon_auth")
        try:
            c.execute("SELECT refresh_quant_views()")
            log.info("view_latest_signals refreshed")
        except Exception as e:
            # First-ever run: matview is empty, CONCURRENTLY refresh fails
            # without a baseline. Fall back to non-concurrent.
            log.warning("CONCURRENT refresh failed (%s); falling back", e)
            c.execute("REFRESH MATERIALIZED VIEW view_latest_signals")
            log.info("view_latest_signals refreshed (non-concurrent)")


if __name__ == "__main__":
    main()
