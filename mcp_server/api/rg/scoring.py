"""M1 — daily market risk score (PRD §5).

`score_day` is pure and total: it never raises on missing inputs. A subitem
whose data did not arrive scores zero and is stamped `data_missing`, per PRD §7
("單源失敗不炸 pipeline、缺料照算並註記 data_missing"). That matters more than
it looks — a TAIFEX outage must not silently produce a calm-looking green, so
the caller can see which subitems were blind and say so in the push.
"""
from __future__ import annotations

from typing import Any

from . import config as cfg


def _f(metrics: dict, key: str) -> float | None:
    """Read a numeric metric, treating absent/None/non-numeric as missing."""
    v = metrics.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _subitem(n: int, name: str, points: int, detail: str,
             inputs: dict[str, Any], missing: bool = False) -> dict:
    return {
        "id": n,
        "name": name,
        "points": points,
        "detail": detail,
        "inputs": inputs,
        "data_missing": missing,
    }


def _score_trend(m: dict) -> dict:
    """1. TAIEX against its 20- and 60-day moving averages."""
    close, ma20, ma60 = _f(m, "taiex_close"), _f(m, "ma20"), _f(m, "ma60")
    inputs = {"close": close, f"ma{cfg.MA_SHORT}": ma20, f"ma{cfg.MA_LONG}": ma60}
    if close is None or (ma20 is None and ma60 is None):
        return _subitem(1, "trend", 0, "TAIEX 或均線資料缺漏", inputs, missing=True)

    pts, parts = 0, []
    if ma20 is not None and close < ma20:
        pts += cfg.PTS_BELOW_MA_SHORT
        parts.append(f"收盤 < MA{cfg.MA_SHORT}")
    if ma60 is not None and close < ma60:
        pts += cfg.PTS_BELOW_MA_LONG
        parts.append(f"收盤 < MA{cfg.MA_LONG}")
    # A partially-computed trend (only one MA available) is still worth scoring,
    # but the caller should know it was scored on half the evidence.
    missing = ma20 is None or ma60 is None
    return _subitem(1, "trend", pts, "、".join(parts) or "站上均線", inputs, missing)


def _day_ratio(m: dict) -> float | None:
    """Today's advance ratio, adv / (adv + dec)."""
    adv, dec = _f(m, "adv_count"), _f(m, "dec_count")
    if adv is None or dec is None or (adv + dec) <= 0:
        return None
    return adv / (adv + dec)


def _score_breadth(m: dict) -> dict:
    """2. Market breadth — the worse of the 5-day regime and today's shock.

    The mean alone is too slow to see a one-session collapse (2026-07-07's
    0.126 against a 0.517 mean); today's ratio alone would fire on any noisy
    session. Taking the worse of the two catches both without letting the
    subitem exceed the weight of 2 that PRD §5 gives it.
    """
    mean, day = _f(m, "adv_ratio_5d"), _day_ratio(m)
    inputs = {"adv_ratio_5d": mean, "adv_ratio_today": day,
              "window": cfg.BREADTH_WINDOW}
    if mean is None and day is None:
        return _subitem(2, "breadth", 0, "漲跌家數資料缺漏", inputs, missing=True)

    mean_pts, mean_note = 0, None
    if mean is not None:
        if mean < cfg.BREADTH_BAD:
            mean_pts, mean_note = cfg.PTS_BREADTH_BAD, f"5日均上漲比 {mean:.2f}"
        elif mean < cfg.BREADTH_WEAK:
            mean_pts, mean_note = cfg.PTS_BREADTH_WEAK, f"5日均上漲比 {mean:.2f}"

    day_pts, day_note = 0, None
    if day is not None:
        if day < cfg.BREADTH_DAY_BAD:
            day_pts, day_note = cfg.PTS_BREADTH_BAD, f"當日上漲比 {day:.2f} 崩breadth"
        elif day < cfg.BREADTH_DAY_WEAK:
            day_pts, day_note = cfg.PTS_BREADTH_WEAK, f"當日上漲比 {day:.2f} 偏弱"

    if day_pts > mean_pts:
        detail = day_note
    elif mean_pts > 0:
        detail = mean_note
    else:
        parts = [f"5日均 {mean:.2f}" if mean is not None else None,
                 f"當日 {day:.2f}" if day is not None else None]
        detail = "、".join(p for p in parts if p) + " 尚可"

    return _subitem(2, "breadth", max(mean_pts, day_pts), detail, inputs,
                    missing=mean is None or day is None)


def _score_margin(m: dict) -> dict:
    """3. Margin balance still expanding while the index falls.

    Both halves are required: rising leverage in a rising market is ordinary
    participation; rising leverage in a falling market is un-capitulated retail.
    """
    growth, ret5 = _f(m, "margin_chg_5d_pct"), _f(m, "taiex_ret_5d_pct")
    inputs = {"margin_chg_5d_pct": growth, "taiex_ret_5d_pct": ret5,
              # TWSE publishes margin after the harvest window, so this is
              # normally the previous session — see cfg.MARGIN_MAX_LAG_SESSIONS.
              "margin_as_of": m.get("margin_as_of")}
    if growth is None or ret5 is None:
        return _subitem(3, "margin", 0, "融資或指數報酬資料缺漏", inputs, missing=True)
    if growth > cfg.MARGIN_GROWTH_PCT and ret5 < 0:
        return _subitem(3, "margin", cfg.PTS_MARGIN,
                        f"融資5日 +{growth:.1f}% 但指數5日 {ret5:.1f}%", inputs)
    return _subitem(3, "margin", 0,
                    f"融資5日 {growth:+.1f}%、指數5日 {ret5:+.1f}%", inputs)


def _score_futures(m: dict) -> dict:
    """4. Foreign futures positioning — the absolute level, per PRD §5.

    Scores `fut_foreign_net_oi`: net short ≥ FUT_NET_SHORT_HEAVY → +2. The
    5-day change is still reported in `inputs` but no longer scored.

    Restored to the spec 2026-07-31 at [niko]'s direction, after three rounds
    of acceptance flagged the change-based version as a deviation. The
    measurement that argued against it is recorded rather than re-run: over the
    37 sessions on record the level ran -63,168 to -86,189, so the 20,000
    threshold fires on 100% of days and this subitem is a constant +2 rather
    than a signal.

    Concretely that means the floor score is 2 against a green band of ≤2 — a
    calm market stays green but with no margin, and one point from any other
    subitem turns it yellow. That is a risk-model choice, and it is the
    owner's to make; it is written down here so it is not rediscovered as a
    surprise. Making this subitem discriminate again needs a threshold the data
    crosses (rolling percentile, or ~80,000), not a change to this function.
    """
    oi = _f(m, "fut_foreign_net_oi")
    chg = _f(m, "fut_net_oi_chg_5d")
    inputs = {"fut_foreign_net_oi": oi, "fut_net_oi_chg_5d": chg,
              "window": cfg.FUT_CHANGE_WINDOW,
              "threshold": cfg.FUT_NET_SHORT_HEAVY}
    if oi is None:
        return _subitem(4, "futures", 0, "期貨留倉資料缺漏", inputs, missing=True)

    net_short = -oi   # positive = net short
    if net_short >= cfg.FUT_NET_SHORT_HEAVY:
        return _subitem(4, "futures", cfg.PTS_FUT_HEAVY,
                        f"外資期貨淨空 {net_short:,.0f} 口", inputs)
    if net_short >= cfg.FUT_NET_SHORT_MILD:
        return _subitem(4, "futures", cfg.PTS_FUT_MILD,
                        f"外資期貨淨空 {net_short:,.0f} 口", inputs)
    return _subitem(4, "futures", 0,
                    f"外資期貨淨部位 {oi:+,.0f} 口", inputs)


def _score_day_drop(m: dict) -> dict:
    """5. Today's index move. Bands do not stack — the worse one wins."""
    pct = _f(m, "taiex_pct")
    inputs = {"taiex_pct": pct}
    if pct is None:
        return _subitem(5, "day_drop", 0, "當日漲跌幅缺漏", inputs, missing=True)
    if pct <= cfg.DAY_DROP_HEAVY:
        return _subitem(5, "day_drop", cfg.PTS_DAY_HEAVY, f"單日 {pct:.2f}%", inputs)
    if pct <= cfg.DAY_DROP_MILD:
        return _subitem(5, "day_drop", cfg.PTS_DAY_MILD, f"單日 {pct:.2f}%", inputs)
    return _subitem(5, "day_drop", 0, f"單日 {pct:+.2f}%", inputs)


_SUBITEMS = (_score_trend, _score_breadth, _score_margin, _score_futures, _score_day_drop)


def score_day(metrics: dict) -> tuple[int, list[dict]]:
    """Score one session. Returns (score, reasons).

    `metrics` keys (all optional; absent ⇒ that subitem scores 0 + data_missing):
        taiex_close, taiex_pct, ma20, ma60, taiex_ret_5d_pct,
        adv_ratio_5d, margin_chg_5d_pct, fut_foreign_net_oi
    """
    reasons = [fn(metrics) for fn in _SUBITEMS]
    return sum(r["points"] for r in reasons), reasons


def light_from_score(score: int) -> str:
    """Raw band lookup. The light actually published also passes through the
    hysteresis in light.resolve_light — never publish this value directly."""
    if score >= cfg.SCORE_RED:
        return "red"
    if score >= cfg.SCORE_YELLOW:
        return "yellow"
    return "green"


def missing_subitems(reasons: list[dict]) -> list[str]:
    """Names of subitems that scored blind, for the 'data_missing' annotation."""
    return [r["name"] for r in reasons if r.get("data_missing")]
