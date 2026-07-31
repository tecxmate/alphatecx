"""M1 replay harness — the Phase 1 acceptance test (PRD §7).

    python -m riskguard.replay --start 2026-06-01 --end 2026-07-31
    python -m riskguard.replay --start 2026-06-01 --end 2026-07-31 --write

Walks the 2026-06/07 correction forward one session at a time, scores each day
with the same pure functions the live pipeline uses, and checks the result
against the expected column of PRD §7. Chronological order is required, not
cosmetic: breadth needs the four prior sessions and the light needs yesterday's
light, so a replay run backwards would silently score a different system.

`--write` persists into rg_market_daily. Without it nothing is stored and the
run is a pure report — which is what you want while calibrating thresholds.

Threshold calibration belongs here. If a row misses, change the numbers in
mcp_server/api/rg/config.py and re-run. Do not special-case a date in scoring.py:
a scorer that recognises 2026-07-24 has learned the answer, not the pattern.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from mcp_server.api.rg import light as light_mod
from mcp_server.api.rg import scoring
from riskguard import sources, store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("riskguard.replay")

# PRD §7 M1 回放驗收 (v1.1). Each entry lists the lights that are acceptable.
EXPECTED: dict[str, set[str]] = {
    "2026-07-07": {"yellow", "red"},     # −2.31%, broke the monthly line
    "2026-07-16": {"yellow", "red"},     # day before the −6.47%
    "2026-07-17": {"red"},               # −6.47%
    "2026-07-24": {"red"},               # −2.67%
    "2026-07-28": {"red"},               # −4.65%
    "2026-07-29": {"red"},               # −3.76%
    "2026-07-30": {"red"},               # −0.26% — must not relax on one calm day
    "2026-07-31": {"red", "yellow"},     # +8.0% — must not jump to green
}

# 6/08 is documented as a known miss: a −3.48% single-session gap-down carries
# no advance warning in any of the five subitems, which is why the stop-loss
# fallback exists and why the README says so out loud.
KNOWN_MISSES = {
    "2026-06-08": "−3.48% 急崩型,五項子指標事前皆無訊號;由 M2 停損兜底",
}


def replay(start: str, end: str, write: bool = False) -> list[dict]:
    """Score every session in [start, end] in order. Returns one row per day."""
    sessions = [r["date"] for r in reversed(store.taiex_series(end, limit=400))
                if start <= r["date"] <= end]
    if not sessions:
        log.error("no TAIEX rows in raw_twse_index between %s and %s — "
                  "run the harvester/backfill first", start, end)
        return []

    log.info("replaying %d sessions %s → %s", len(sessions), sessions[0], sessions[-1])
    # One TAIFEX request for the whole window, reaching far enough back that the
    # first session still has its 5-session lookback.
    fut_series = sources.fetch_foreign_futures_oi_series(
        (date.fromisoformat(sessions[0]) - timedelta(days=30)).isoformat(), sessions[-1])
    log.info("TAIFEX series: %d sessions", len(fut_series))

    results: list[dict] = []
    prev_light: str | None = None
    prev_score: int | None = None
    # Carried in memory so the breadth mean is identical with and without
    # --write; see store.build_metrics for why that matters.
    breadth_seen: list[dict] = []

    for as_of in sessions:
        breadth = sources.fetch_breadth(as_of.replace("-", ""))
        metrics = store.build_metrics(as_of, breadth, fut_series,
                                      breadth_prior=list(reversed(breadth_seen[-8:])))
        if breadth:
            breadth_seen.append({"date": as_of, **breadth})
        score, reasons = scoring.score_day(metrics)

        ctx = light_mod.build_index_context(metrics["_closes"])
        ctx["prev_score"] = prev_score
        ctx["close_above_ma20"] = (
            metrics["taiex_close"] is not None and metrics["ma20"] is not None
            and metrics["taiex_close"] >= metrics["ma20"]
        )
        resolved, why = light_mod.resolve_light(score, prev_light, ctx)

        if write:
            # Persisting as we go is what lets the next iteration read this
            # day's adv/dec counts back for its own 5-day breadth mean.
            store.upsert_market_daily(metrics, resolved, score, reasons)

        results.append({
            "date": as_of,
            "pct": metrics["taiex_pct"],
            "score": score,
            "raw": scoring.light_from_score(score),
            "light": resolved,
            "why": why,
            "missing": scoring.missing_subitems(reasons),
            "points": {r["name"]: r["points"] for r in reasons},
        })
        prev_light, prev_score = resolved, score

    return results


def report(results: list[dict]) -> int:
    """Print the replay table; return the count of failed + unscored rows."""
    print(f"\n{'date':<12}{'chg%':>8}{'score':>7}  {'light':<8}"
          f"{'trend/breadth/margin/fut/day':<30}{'expected':<18}result")
    print("-" * 108)

    failures = 0
    for r in results:
        p = r["points"]
        pts = f"{p['trend']}/{p['breadth']}/{p['margin']}/{p['futures']}/{p['day_drop']}"
        want = EXPECTED.get(r["date"])
        if want:
            ok = r["light"] in want
            verdict = "PASS" if ok else "FAIL"
            failures += 0 if ok else 1
            want_s = "|".join(sorted(want))
        elif r["date"] in KNOWN_MISSES:
            verdict, want_s = "known-miss", "—"
        else:
            verdict, want_s = "", ""
        pct = f"{r['pct']:+.2f}" if r["pct"] is not None else "n/a"
        print(f"{r['date']:<12}{pct:>8}{r['score']:>7}  {r['light']:<8}"
              f"{pts:<30}{want_s:<18}{verdict}")
        if r["missing"]:
            print(f"{'':<12}  ⚠ data_missing: {', '.join(r['missing'])}")

    checked = [r for r in results if r["date"] in EXPECTED]
    unscored = sorted(set(EXPECTED) - {r["date"] for r in results})
    print("-" * 108)
    print(f"acceptance rows scored: {len(checked)}/{len(EXPECTED)}   failures: {failures}")
    if unscored:
        # Not silently treated as a pass — an unscored row is an unverified
        # claim, and PRD §7 asks for coverage, not a green-looking table.
        print(f"NOT SCORED (no data in range): {', '.join(unscored)}")
    for d, why in KNOWN_MISSES.items():
        print(f"known miss {d}: {why}")
    return failures + len(unscored)


def main() -> None:
    ap = argparse.ArgumentParser(description="Risk Guard M1 replay")
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    ap.add_argument("--write", action="store_true",
                    help="persist each scored day into rg_market_daily")
    args = ap.parse_args()

    results = replay(args.start, args.end, write=args.write)
    if not results:
        raise SystemExit(2)
    raise SystemExit(1 if report(results) else 0)


if __name__ == "__main__":
    main()
