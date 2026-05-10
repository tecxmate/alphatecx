#!/usr/bin/env python3
"""One-shot: backfill OHLCV (6 months) for the top-500 TWSE+TPEX tickers
by trailing T86 absolute-flow turnover, skipping tickers we already have.

Designed to be run once via nohup; can be safely re-run (per-ticker-per-
month idempotent upserts).
"""
from __future__ import annotations
import os, time
from datetime import date
from dotenv import load_dotenv
import psycopg
from src.harvester import twse, transform, loader

load_dotenv()

# Resolve top-500 list
with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
    cur.execute("""
        WITH active AS (
          SELECT ticker_id, market,
                 SUM(ABS(total_net))::bigint AS abs_flow_sum,
                 COUNT(*) AS days
          FROM raw_twse_t86 GROUP BY ticker_id, market
          HAVING COUNT(*) >= 50
        )
        SELECT ticker_id, market FROM active
        WHERE LENGTH(ticker_id) <= 5 AND ticker_id NOT LIKE '00%%'
        ORDER BY abs_flow_sum DESC LIMIT 500
    """)
    targets = cur.fetchall()
    cur.execute("SELECT ticker_id FROM raw_twse_ohlcv GROUP BY ticker_id")
    have = {r[0] for r in cur.fetchall()}

needed = [(t, m) for t, m in targets if t not in have]
print(f"fetching {len(needed)} tickers x 6 months", flush=True)

# Last 6 months (inclusive of current)
today = date.today()
months = []
y, m = today.year, today.month
for _ in range(6):
    months.append((y, m))
    m -= 1
    if m == 0:
        m, y = 12, y - 1

total_iters = len(needed) * len(months)
i = errors = total_rows = 0
for tid, market in needed:
    for year, mo in months:
        i += 1
        if i == 1 or i % 25 == 0:
            print(f"[{i}/{total_iters}] {market} {tid} {year}-{mo:02d}", flush=True)
        try:
            if market == "TWSE":
                rows = twse.fetch_twse_ohlcv_month(tid, year, mo)
            else:
                rows = twse.fetch_tpex_ohlcv_month(tid, year, mo)
            if rows:
                df = transform.ohlcv_to_frame(rows)
                count = loader.upsert_ohlcv(df)
                total_rows += count
        except Exception as e:
            errors += 1
            if errors < 20:
                print(f"  err {market}/{tid} {year}-{mo:02d}: {e}", flush=True)
        time.sleep(3.0)

print(f"DONE. rows={total_rows} errors={errors}", flush=True)
