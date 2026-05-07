"""Flow-derived signals from raw_twse_t86 — institutional flow z-scores
and N-day accumulation sums. Persisted to the same signal_value table
that OHLCV-derived signals use; downstream consumers don't care which
data source produced a given signal_name.

Run:
    python -m src.quant.compute_flow_signals               # all classified
    python -m src.quant.compute_flow_signals --ticker 2330 # one ticker

Data depth note: T86 covers ~45 trading days after Gemini's prune. A
20-day rolling z-score works but the early ~25 days will be NaN. As
T86 history accumulates this becomes more meaningful.

Signal naming:
  foreign_net_z20    rolling 20-day z-score of daily foreign_net
  foreign_net_5d_sum 5-day accumulation of foreign_net (shares)
  total_net_z20      same idea but for total_net (foreign+trust+dealer)
"""
from __future__ import annotations

import argparse
import logging

import polars as pl

from src.harvester.loader import cur, atomic
from src.quant import indicators as ind

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("compute_flow_signals")

FLOW_SIGNALS = ["foreign_net_z20", "foreign_net_5d_sum", "total_net_z20"]


def _read_t86(ticker_id: str, c) -> pl.DataFrame:
    c.execute(
        """
        SELECT date, foreign_net, trust_net, dealer_net, total_net
        FROM raw_twse_t86 WHERE ticker_id = %s ORDER BY date
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


def compute_for_ticker(ticker_id: str, c) -> int:
    df = _read_t86(ticker_id, c)
    # Need at least window+1 bars for the z-score to have anything to say.
    if df.is_empty() or df.height < 21:
        log.info("  %s: only %d T86 bars, skipping",
                 ticker_id, 0 if df.is_empty() else df.height)
        return 0

    # Cast counters to float so rolling stats don't promote/lose precision.
    fnet = df["foreign_net"].cast(pl.Float64)
    tnet = df["total_net"].cast(pl.Float64)

    fz20 = ind.zscore(fnet, period=20)
    f5sum = ind.rolling_sum(fnet, period=5)
    tz20 = ind.zscore(tnet, period=20)

    series_by_name = {
        "foreign_net_z20": fz20,
        "foreign_net_5d_sum": f5sum,
        "total_net_z20": tz20,
    }
    dates = df["date"].to_list()
    rows: list[tuple[str, str, object, float]] = []
    for name, series in series_by_name.items():
        for d, v in zip(dates, series.to_list()):
            if v is None or v != v:  # None / NaN
                continue
            rows.append((name, ticker_id, d, float(v)))

    if not rows:
        return 0

    sql = """
        INSERT INTO signal_value (signal_name, ticker_id, date, value)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (signal_name, ticker_id, date) DO UPDATE SET
            value = EXCLUDED.value,
            computed_at = now()
    """
    c.executemany(sql, rows)
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", help="Compute for one ticker only")
    args = parser.parse_args()

    with atomic() as c:
        c.execute("SET search_path TO public, neon_auth")
        tickers = [args.ticker] if args.ticker else _classified_tickers(c)
        log.info("Computing flow signals for %d ticker(s)", len(tickers))

        total = 0
        for tid in tickers:
            n = compute_for_ticker(tid, c)
            log.info("  %s: %d signal-rows", tid, n)
            total += n

        log.info("Total flow signal-rows written: %d", total)


if __name__ == "__main__":
    main()
