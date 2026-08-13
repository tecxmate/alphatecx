#!/usr/bin/env python3
"""Composite quality score per ticker.

Real "quality" in equity factor literature means high ROE, stable earnings,
low debt — we don't have those. This score is TW-specific, built from data
we DO have, mapped onto a quality-at-a-price interpretation:

  Subscore               Source              What it captures
  ─────────────────────  ──────────────────  ─────────────────────────────
  growth                 monthly revenue     latest YoY %
  growth_acceleration    monthly revenue     latest YoY minus prior-3m avg
  valuation              raw_twse_valuation  P/B percentile vs own 90d
                                             (low = cheap = good)
  flow                   view_latest_signals foreign_net_z20
  trend                  view_latest_signals close vs SMA-200

Each subscore is mapped to [0, 100] via a sensible cap, then averaged
equal-weight. The composite is a single 0-100 number suitable for cross-
sectional ranking. The components dict is preserved so Claude can read
which axis is dragging the score.

Run:
    python -m src.quant.quality_score 3231
    python -m src.quant.quality_score 3231 --pillar infrastructure  # batch
"""
from __future__ import annotations

import argparse
import logging
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("MCP_DATABASE_URL") or os.environ["DATABASE_URL"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("quality")


# Score-mapping caps: a "perfect" subscore is at this absolute value
_GROWTH_CAP    = 50.0     # +50% YoY revenue → 100 score
_ACCEL_CAP     = 30.0     # +30 pt YoY accel → 100 score
_FLOW_Z_CAP    = 3.0      # foreign-z = +3 → 100 score
_TREND_CAP     = 0.30     # +30% above SMA-200 → 100 score


def _to_0_100(raw, cap, low_is_better=False):
    """Map a raw value with cap → [0, 100]. Sign-aware."""
    if raw is None:
        return None
    x = max(-1.0, min(1.0, float(raw) / cap))
    if low_is_better:
        x = -x
    return round((x + 1.0) * 50.0, 1)


def fetch_components(conn, ticker_id: str) -> dict:
    """Pull the raw inputs for ticker. Returns None for any field we can't compute."""
    out: dict = {}
    with conn.cursor() as c:
        # Revenue: latest 4 months of YoY
        c.execute("""SELECT ym, yoy_pct FROM raw_monthly_revenue
                     WHERE ticker_id = %s AND yoy_pct IS NOT NULL
                     ORDER BY ym DESC LIMIT 4""", (ticker_id,))
        rows = c.fetchall()
        if rows:
            out["latest_yoy_month"] = rows[0][0]
            out["latest_yoy_pct"]   = float(rows[0][1])
            if len(rows) >= 4:
                prior3 = sum(float(r[1]) for r in rows[1:4]) / 3
                out["yoy_accel_pct"] = float(rows[0][1]) - prior3
            else:
                out["yoy_accel_pct"] = None
        else:
            out["latest_yoy_pct"]  = None
            out["yoy_accel_pct"]   = None

        # P/B percentile vs own 90d
        c.execute("""SELECT pb_ratio FROM raw_twse_valuation
                     WHERE ticker_id = %s AND pb_ratio IS NOT NULL
                     ORDER BY date DESC LIMIT 90""", (ticker_id,))
        pbs = [float(r[0]) for r in c.fetchall()]
        if len(pbs) >= 5:
            out["pb_now"] = pbs[0]
            sorted_pbs = sorted(pbs)
            pct = sum(1 for p in sorted_pbs if p <= pbs[0]) / len(sorted_pbs) * 100
            out["pb_percentile_90d"] = round(pct, 1)  # 0=cheapest, 100=priciest
        else:
            out["pb_now"] = None
            out["pb_percentile_90d"] = None

        # Latest signals
        c.execute("""SELECT foreign_net_z20, sma_200,
                            (SELECT close FROM raw_twse_ohlcv
                             WHERE ticker_id=%s ORDER BY date DESC LIMIT 1)
                     FROM view_latest_signals WHERE ticker_id = %s""",
                  (ticker_id, ticker_id))
        row = c.fetchone()
        if row:
            out["foreign_net_z20"] = float(row[0]) if row[0] is not None else None
            out["sma_200"] = float(row[1]) if row[1] is not None else None
            close = float(row[2]) if row[2] is not None else None
            if close is not None and out["sma_200"]:
                out["close"] = close
                out["pct_above_sma200"] = (close - out["sma_200"]) / out["sma_200"]
            else:
                out["pct_above_sma200"] = None
        else:
            out["foreign_net_z20"] = None
            out["pct_above_sma200"] = None

        # Meta
        c.execute("""SELECT company_name, ai_pillar, node FROM dim_ticker
                     WHERE ticker_id = %s""", (ticker_id,))
        m = c.fetchone() or ("", None, None)
        out["company_name"] = m[0]
        out["ai_pillar"]    = m[1]
        out["node"]         = m[2]
    return out


def compute_quality_score(ticker_id: str, conn=None) -> dict:
    """Returns composite 0-100 score and components."""
    own_conn = False
    if conn is None:
        conn = psycopg.connect(DATABASE_URL)
        own_conn = True
    try:
        c = fetch_components(conn, ticker_id)
    finally:
        if own_conn:
            conn.close()

    growth_score   = _to_0_100(c.get("latest_yoy_pct"),  _GROWTH_CAP)
    accel_score    = _to_0_100(c.get("yoy_accel_pct"),   _ACCEL_CAP)
    flow_score     = _to_0_100(c.get("foreign_net_z20"), _FLOW_Z_CAP)
    trend_score    = _to_0_100(c.get("pct_above_sma200"), _TREND_CAP)
    # Valuation: low P/B percentile is better (cheap = high score)
    val_score      = (100.0 - c["pb_percentile_90d"]
                      if c.get("pb_percentile_90d") is not None else None)

    subscores = {
        "growth":              growth_score,
        "growth_acceleration": accel_score,
        "valuation":           val_score,
        "flow":                flow_score,
        "trend":               trend_score,
    }
    available = [s for s in subscores.values() if s is not None]
    composite = round(sum(available) / len(available), 1) if available else None

    return {
        "ticker_id":     ticker_id,
        "company_name":  c.get("company_name"),
        "ai_pillar":     c.get("ai_pillar"),
        "node":          c.get("node"),
        "quality_score": composite,
        "subscores":     subscores,
        "raw": {
            "latest_yoy_month":  c.get("latest_yoy_month"),
            "latest_yoy_pct":    c.get("latest_yoy_pct"),
            "yoy_accel_pct":     c.get("yoy_accel_pct"),
            "pb_now":            c.get("pb_now"),
            "pb_percentile_90d": c.get("pb_percentile_90d"),
            "foreign_net_z20":   c.get("foreign_net_z20"),
            "pct_above_sma200":  c.get("pct_above_sma200"),
        },
        "missing": [k for k, v in subscores.items() if v is None],
        "interpretation": _interpret(composite, subscores, c),
    }


def compute_quality_screen(
    pillar: str | None = None,
    node: str | None = None,
    tickers: list[str] | None = None,
    sort_by: str = "quality_score",
    top_n: int = 30,
) -> list[dict]:
    """Cross-sectional ranking by quality score."""
    with psycopg.connect(DATABASE_URL) as conn:
        c = conn.cursor()
        if tickers:
            placeholders = ",".join(["%s"] * len(tickers))
            c.execute(f"""SELECT ticker_id FROM dim_ticker WHERE ticker_id IN ({placeholders})""",
                      tuple(tickers))
        else:
            wh = ["ai_pillar IS NOT NULL"]
            params: list = []
            if pillar: wh.append("ai_pillar = %s"); params.append(pillar)
            if node:   wh.append("node = %s");      params.append(node)
            c.execute(f"""SELECT ticker_id FROM dim_ticker WHERE {' AND '.join(wh)}
                          ORDER BY ticker_id""", tuple(params))
        targets = [r[0] for r in c.fetchall()]

        rows = []
        for tid in targets:
            r = compute_quality_score(tid, conn=conn)
            if r.get("quality_score") is None:
                continue
            rows.append(r)

    rows.sort(key=lambda r: r.get(sort_by) or 0, reverse=True)
    return rows[:top_n]


def _interpret(composite, subscores, raw):
    if composite is None:
        return "Not enough data to score."
    parts = [f"Composite quality score: {composite:.0f}/100."]
    # Highlight extremes
    high = [k for k, v in subscores.items() if v is not None and v >= 75]
    low  = [k for k, v in subscores.items() if v is not None and v <= 25]
    if high: parts.append(f"Strong: {', '.join(high)}.")
    if low:  parts.append(f"Weak: {', '.join(low)}.")
    if raw.get("latest_yoy_pct") and raw["latest_yoy_pct"] > 50:
        parts.append(f"Revenue YoY +{raw['latest_yoy_pct']:.0f}%.")
    if raw.get("pb_percentile_90d") is not None:
        if raw["pb_percentile_90d"] < 30:
            parts.append("Trading near recent P/B lows (cheap).")
        elif raw["pb_percentile_90d"] > 75:
            parts.append("Trading near recent P/B highs (expensive).")
    if raw.get("foreign_net_z20") and raw["foreign_net_z20"] > 1.5:
        parts.append("Foreign accumulation extreme.")
    elif raw.get("foreign_net_z20") and raw["foreign_net_z20"] < -1.5:
        parts.append("Foreign distribution extreme.")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker_id", nargs="?")
    ap.add_argument("--pillar")
    ap.add_argument("--node")
    ap.add_argument("--top-n", type=int, default=30)
    args = ap.parse_args()
    import json
    if args.ticker_id and not (args.pillar or args.node):
        print(json.dumps(compute_quality_score(args.ticker_id),
                         indent=2, default=str))
    else:
        rows = compute_quality_screen(
            pillar=args.pillar, node=args.node, top_n=args.top_n,
        )
        print(json.dumps(rows, indent=2, default=str))


if __name__ == "__main__":
    main()
