#!/usr/bin/env python3
"""Multi-factor alpha decomposition for individual tickers.

For ticker i, fit:

    r_{i,t} = α_i + β_mkt · MKT_t + β_sector · SECTOR_t + β_flow · FLOW_t + ε_{i,t}

Where each factor is a pre-computed daily return series:

    MKT     = 0050 Yuanta Taiwan 50 ETF (broad market proxy)
    SECTOR  = ticker's pillar sector index (e.g. 半導體類指數 for 2330)
    FLOW    = long-short portfolio of classified tickers ranked daily by
              20-day rolling z-score of T86 foreign_net (top quintile -
              bottom quintile, equal-weight)

α is the residual return after factor exposures: "how much did this ticker
out/under-perform what its factor exposures predicted?" The t-statistic
on α tells you whether the residual is statistically distinguishable from
zero.

Run as a module:
    python -m src.quant.factor_alpha 3231 --days 120
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, timedelta

import numpy as np
import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("factor_alpha")

PILLAR_INDEX = {
    "semiconductor":  "半導體類指數",
    "infrastructure": "數位雲端類指數",
    "equipment":      "機電類指數",
    "energy":         "油電燃氣類指數",
}


def _date_aligned_returns(dates_a, vals_a, dates_b, vals_b):
    """Return (common_dates, ra_aligned, rb_aligned) — log returns aligned
    on the intersection of dates."""
    map_a = dict(zip(dates_a, vals_a))
    map_b = dict(zip(dates_b, vals_b))
    common = sorted(set(dates_a) & set(dates_b))
    if len(common) < 3:
        return common, np.array([]), np.array([])
    a = np.array([map_a[d] for d in common], dtype=float)
    b = np.array([map_b[d] for d in common], dtype=float)
    ra = np.diff(np.log(a))
    rb = np.diff(np.log(b))
    return common[1:], ra, rb


def fetch_ticker_meta(conn, ticker_id: str) -> dict:
    with conn.cursor() as c:
        c.execute("""SELECT ticker_id, company_name, ai_pillar, node
                     FROM dim_ticker WHERE ticker_id = %s""", (ticker_id,))
        r = c.fetchone()
    if not r:
        raise ValueError(f"ticker {ticker_id} not in dim_ticker")
    return {"ticker_id": r[0], "company_name": r[1], "ai_pillar": r[2], "node": r[3]}


def fetch_close_series(conn, ticker_id: str, days: int):
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    with conn.cursor() as c:
        c.execute("""SELECT date, close FROM raw_twse_ohlcv
                     WHERE ticker_id = %s AND date >= %s AND close IS NOT NULL
                     ORDER BY date""", (ticker_id, cutoff))
        rows = c.fetchall()
    return [r[0] for r in rows], [float(r[1]) for r in rows]


def fetch_index_series(conn, index_name: str, days: int):
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    with conn.cursor() as c:
        c.execute("""SELECT date, close FROM raw_twse_index
                     WHERE index_name = %s AND date >= %s AND close IS NOT NULL
                     ORDER BY date""", (index_name, cutoff))
        rows = c.fetchall()
    return [r[0] for r in rows], [float(r[1]) for r in rows]


def build_flow_factor(conn, days: int, z_window: int = 20):
    """Daily long-short return: top-quintile foreign_net z-score minus
    bottom-quintile, equal-weight, classified universe.

    Requires 20+ days of T86 history before the factor's first usable date,
    so total trading-day depth = days + 20 (rough).
    """
    cutoff = (date.today() - timedelta(days=days * 2)).isoformat()
    with conn.cursor() as c:
        # All classified tickers' daily T86 + close series
        c.execute("""
            SELECT t86.date, t86.ticker_id, t86.foreign_net, ohlcv.close
              FROM raw_twse_t86 t86
              JOIN dim_supply_chain dt ON dt.ticker_id = t86.ticker_id
              LEFT JOIN raw_twse_ohlcv ohlcv
                ON ohlcv.ticker_id = t86.ticker_id AND ohlcv.date = t86.date
             WHERE t86.date >= %s
             ORDER BY t86.ticker_id, t86.date
        """, (cutoff,))
        rows = c.fetchall()

    # Group by ticker
    series: dict[str, list[tuple]] = {}
    for d, tid, fn, cl in rows:
        if cl is None: continue
        series.setdefault(tid, []).append((d, float(fn), float(cl)))

    # Per ticker: rolling z-score of foreign_net, daily log return
    ticker_data: dict[str, dict] = {}
    for tid, recs in series.items():
        if len(recs) < z_window + 5:
            continue
        recs.sort(key=lambda r: r[0])
        dates  = [r[0] for r in recs]
        flows  = np.array([r[1] for r in recs], dtype=float)
        closes = np.array([r[2] for r in recs], dtype=float)
        # Rolling z-score (look-back z_window days, exclusive of t)
        z = np.full_like(flows, np.nan, dtype=float)
        for i in range(z_window, len(flows)):
            window = flows[i - z_window:i]
            mu, sd = window.mean(), window.std()
            if sd > 1e-9:
                z[i] = (flows[i] - mu) / sd
        # Daily log return (close-to-close)
        rets = np.full_like(closes, np.nan, dtype=float)
        rets[1:] = np.diff(np.log(closes))
        ticker_data[tid] = {"dates": dates, "z": z, "ret": rets}

    if len(ticker_data) < 8:
        log.warning("flow factor: only %d eligible tickers, factor unstable",
                    len(ticker_data))
        return [], np.array([])

    # All distinct dates across the universe
    all_dates = sorted({d for v in ticker_data.values() for d in v["dates"]})
    factor_returns = []
    factor_dates = []
    for d in all_dates:
        # Tickers eligible on this date
        z_today = []
        ret_today_lookup = {}
        for tid, v in ticker_data.items():
            try:
                idx = v["dates"].index(d)
            except ValueError:
                continue
            zi = v["z"][idx]
            # Use NEXT day's return as the factor return realisation
            if idx + 1 >= len(v["dates"]):
                continue
            ri = v["ret"][idx + 1]
            if np.isnan(zi) or np.isnan(ri):
                continue
            z_today.append((tid, zi))
            ret_today_lookup[tid] = ri
        if len(z_today) < 10:
            continue
        # Quintile split
        z_today.sort(key=lambda x: x[1])
        n = len(z_today)
        bot = z_today[: max(1, n // 5)]
        top = z_today[-max(1, n // 5):]
        bot_ret = np.mean([ret_today_lookup[t] for t, _ in bot])
        top_ret = np.mean([ret_today_lookup[t] for t, _ in top])
        factor_returns.append(top_ret - bot_ret)
        # The factor return is realised on the day FOLLOWING d (we used idx+1)
        # Index returns by that next-day date for proper alignment.
        next_date = ticker_data[top[0][0]]["dates"][
            ticker_data[top[0][0]]["dates"].index(d) + 1
        ]
        factor_dates.append(next_date)

    return factor_dates, np.array(factor_returns)


def _regress(target_dates_returns, factor_dicts, factor_names, days):
    """Shared OLS engine. Returns the dict of regression outputs.

    target_dates_returns: (list[date], np.ndarray) — target log returns aligned
                         to dates.
    factor_dicts: list of dict[date -> return] for each factor.
    factor_names: list of factor names corresponding to factor_dicts.
    days: window cap (filters to the last `days` calendar days).
    """
    target_dates, target_returns = target_dates_returns
    by_date_target = dict(zip(target_dates, target_returns))

    common = set(by_date_target)
    for fd in factor_dicts:
        common &= set(fd)
    common = sorted(common)
    cutoff = date.today() - timedelta(days=days)
    common = [d for d in common if d >= cutoff]

    if len(common) < 30:
        return {"error": f"insufficient overlap (n={len(common)})", "n_obs": len(common)}

    y = np.array([by_date_target[d] for d in common])
    X_cols = [np.array([fd[d] for d in common]) for fd in factor_dicts]
    X = np.column_stack([np.ones_like(y), *X_cols])

    beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    eps = y - X @ beta
    n, k = X.shape
    sigma2 = float(np.sum(eps ** 2) / max(1, n - k))
    cov_beta = sigma2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov_beta))

    alpha_daily = float(beta[0])
    alpha_se = float(se[0])
    alpha_tstat = alpha_daily / alpha_se if alpha_se > 1e-12 else float("inf")
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(np.sum(eps ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")

    return {
        "n_obs": n,
        "alpha_daily": round(alpha_daily, 6),
        "alpha_annualized": round(alpha_daily * 252, 4),
        "alpha_tstat": round(alpha_tstat, 2),
        "alpha_significant": bool(abs(alpha_tstat) > 2.0),
        "betas": {factor_names[i]: round(float(beta[i + 1]), 3)
                  for i in range(len(factor_names))},
        "beta_tstats": {factor_names[i]: round(float(beta[i + 1] / se[i + 1]), 2)
                        for i in range(len(factor_names))},
        "r_squared": round(r_squared, 3),
        "factors_used": factor_names,
    }


def compute_factor_alpha(ticker_id: str, days: int = 120) -> dict:
    with psycopg.connect(DATABASE_URL) as conn:
        meta = fetch_ticker_meta(conn, ticker_id)
        pillar = meta["ai_pillar"]

        # Ticker returns
        t_dates, t_close = fetch_close_series(conn, ticker_id, days)
        if len(t_close) < 30:
            return {"error": f"insufficient ohlcv for {ticker_id} ({len(t_close)} rows)"}
        t_dates_r = t_dates[1:]
        t_ret = np.diff(np.log(np.array(t_close, dtype=float)))

        # Market = 0050
        m_dates, m_close = fetch_close_series(conn, "0050", days)
        m_dates_r = m_dates[1:]
        m_ret = np.diff(np.log(np.array(m_close, dtype=float)))

        # Sector
        s_ret = np.array([])
        s_dates_r = []
        sector_name = PILLAR_INDEX.get(pillar) if pillar else None
        if sector_name:
            s_dates, s_close = fetch_index_series(conn, sector_name, days)
            if len(s_close) >= 5:
                s_dates_r = s_dates[1:]
                s_ret = np.diff(np.log(np.array(s_close, dtype=float)))

        # Flow factor
        f_dates, f_ret = build_flow_factor(conn, days)

    # Build factor dicts and run regression via shared engine
    factor_dicts = [dict(zip(m_dates_r, m_ret))]
    factor_names = ["market"]
    if len(s_ret) > 0:
        factor_dicts.append(dict(zip(s_dates_r, s_ret)))
        factor_names.append("sector")
    if len(f_ret) > 0:
        factor_dicts.append(dict(zip(f_dates, f_ret)))
        factor_names.append("flow")

    res = _regress((t_dates_r, t_ret), factor_dicts, factor_names, days)
    if "error" in res:
        return {"ticker_id": ticker_id, **res}

    return {
        "ticker_id": ticker_id,
        "company_name": meta["company_name"],
        "ai_pillar": pillar,
        "node": meta["node"],
        "window_days": days,
        "sector_index": sector_name,
        **res,
        "interpretation": _interpret(
            res["alpha_daily"], res["alpha_tstat"], res["r_squared"],
            res["betas"]),
    }


# ── Cross-sectional version ────────────────────────────────────────────────

def compute_factor_screen(
    pillar: str | None = None,
    node: str | None = None,
    tickers: list[str] | None = None,
    days: int = 90,
    min_obs: int = 30,
    sort_by: str = "alpha_tstat",
    ascending: bool = False,
) -> list[dict]:
    """Run q_factor_alpha across a set of tickers in one DB roundtrip.

    Cross-sectional alpha hunting. Builds factor returns (market, flow)
    once, builds each pillar's sector returns once, then iterates tickers
    and regresses each against its own pillar-appropriate factor stack.

    Args:
        pillar: filter classified set by AI pillar (e.g. 'semiconductor')
        node: filter by node (e.g. 'server-odm'); composes with pillar
        tickers: explicit ticker list — overrides pillar/node if given
        days: regression window
        min_obs: drop tickers whose regression had fewer obs
        sort_by: 'alpha_tstat', 'alpha_annualized', 'r_squared', or 'n_obs'
        ascending: sort direction (default desc — best alpha first)

    Returns: list of dicts (one per ticker), each like compute_factor_alpha
    minus the interpretation string (which is per-ticker expensive to build).
    """
    with psycopg.connect(DATABASE_URL) as conn:
        c = conn.cursor()

        # Resolve target ticker set
        if tickers:
            placeholders = ",".join(["%s"] * len(tickers))
            c.execute(f"""SELECT ticker_id, company_name, ai_pillar, node
                          FROM dim_ticker WHERE ticker_id IN ({placeholders})""",
                      tuple(tickers))
        else:
            wh = ["ai_pillar IS NOT NULL"]
            params: list = []
            if pillar: wh.append("ai_pillar = %s"); params.append(pillar)
            if node:   wh.append("node = %s");      params.append(node)
            c.execute(f"""SELECT ticker_id, company_name, ai_pillar, node
                          FROM dim_ticker WHERE {' AND '.join(wh)}
                          ORDER BY ticker_id""", tuple(params))
        targets = c.fetchall()
        log.info("factor_screen: %d targets", len(targets))

        # Build market factor (0050) once
        m_dates, m_close = fetch_close_series(conn, "0050", days)
        m_dates_r = m_dates[1:]
        m_ret = np.diff(np.log(np.array(m_close, dtype=float)))
        market_dict = dict(zip(m_dates_r, m_ret))

        # Build flow factor once
        f_dates, f_ret = build_flow_factor(conn, days)
        flow_dict = dict(zip(f_dates, f_ret)) if len(f_ret) else {}

        # Per-pillar sector factor (cache to avoid refetching)
        sector_cache: dict[str, dict] = {}
        for pillar_key, idx_name in PILLAR_INDEX.items():
            s_dates, s_close = fetch_index_series(conn, idx_name, days)
            if len(s_close) >= 5:
                s_dates_r = s_dates[1:]
                s_ret = np.diff(np.log(np.array(s_close, dtype=float)))
                sector_cache[pillar_key] = dict(zip(s_dates_r, s_ret))

        # Iterate targets
        results = []
        for tid, name, t_pillar, t_node in targets:
            t_dates, t_close = fetch_close_series(conn, tid, days)
            if len(t_close) < 30:
                continue
            t_dates_r = t_dates[1:]
            t_ret = np.diff(np.log(np.array(t_close, dtype=float)))

            factor_dicts = [market_dict]
            factor_names = ["market"]
            if t_pillar in sector_cache:
                factor_dicts.append(sector_cache[t_pillar])
                factor_names.append("sector")
            if flow_dict:
                factor_dicts.append(flow_dict)
                factor_names.append("flow")

            res = _regress((t_dates_r, t_ret), factor_dicts, factor_names, days)
            if "error" in res or res["n_obs"] < min_obs:
                continue
            results.append({
                "ticker_id": tid,
                "company_name": name,
                "ai_pillar": t_pillar,
                "node": t_node,
                "sector_index": PILLAR_INDEX.get(t_pillar),
                **res,
            })

    # Sort by requested key
    valid_keys = {"alpha_tstat", "alpha_annualized", "alpha_daily",
                  "r_squared", "n_obs"}
    if sort_by not in valid_keys:
        sort_by = "alpha_tstat"
    results.sort(key=lambda r: r.get(sort_by) or 0, reverse=not ascending)
    return results


def _interpret(alpha_d, alpha_t, r2, betas):
    """Plain-English summary suitable for Claude or human reading."""
    parts = []
    annual = alpha_d * 252 * 100
    if abs(alpha_t) > 2:
        sig = "statistically significant"
    elif abs(alpha_t) > 1:
        sig = "marginally significant"
    else:
        sig = "not statistically significant"
    direction = "outperforming" if alpha_d > 0 else "underperforming"
    parts.append(
        f"After accounting for market, sector, and flow factor exposures, "
        f"this ticker is {direction} by {annual:+.1f}% annualised "
        f"(t={alpha_t:+.2f}, {sig})."
    )
    parts.append(
        f"R² = {r2:.0%} — factors explain {r2*100:.0f}% of daily-return variance."
    )
    if betas:
        bdesc = []
        for n, b in betas.items():
            tag = "low" if abs(b) < 0.5 else "moderate" if abs(b) < 1.2 else "high"
            bdesc.append(f"{n} β={b:+.2f} ({tag})")
        parts.append(", ".join(bdesc) + ".")
    if abs(alpha_t) <= 1.5 and r2 > 0.4:
        parts.append("Caveat: most of this ticker's movement is explained by factors. "
                     "Treat alpha as noise, not signal.")
    elif abs(alpha_t) > 2 and alpha_d > 0:
        parts.append("Bullish read: residual return is real — not driven by factor exposures.")
    elif abs(alpha_t) > 2 and alpha_d < 0:
        parts.append("Bearish read: residual underperformance is real — not factor-driven.")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker_id")
    ap.add_argument("--days", type=int, default=120)
    args = ap.parse_args()
    result = compute_factor_alpha(args.ticker_id, args.days)
    import json
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
