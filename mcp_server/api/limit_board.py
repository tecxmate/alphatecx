"""Taiwan limit-up / limit-down board scanner (漲停/跌停).

EOD only. The full board can't be served from Postgres: raw_twse_ohlcv is
harvested for the classified universe plus a top-500 backfill, not all ~2000
equities. So the board itself is fetched live from the exchanges at call time
(two HTTP requests), and enrichment is joined from our own tables afterwards.

Endpoints:
  TWSE  www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?type=ALLBUT0999
  TPEX  www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?type=AL

Both return every security with close, signed change, and the last disclosed
bid/ask — which is what makes EOD lock detection possible (§4 of the spec
assumed it wasn't).

Reference price is derived as ``close - change``. Verified 2026-07-17 against
TPEX's own 次日參考價 for the 2026-07-16 session: 848/848 exact, so the
derivation already carries the exchange's ex-dividend / ex-rights adjustments
and must not be replaced with a raw previous close.
"""
from __future__ import annotations

import re
import time
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, InvalidOperation
from typing import Any, Optional

import requests

TWSE_MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_DAILY_QUOTES = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"

_UA = {"User-Agent": "Mozilla/5.0 (compatible; alphatecx/2.0)"}
# Both endpoints answer in 1-2.5s (measured 2026-07-17; TPEX ships ~1.5 MB).
# The whole budget has to fit one serverless invocation: worst case here is
# 2 markets x (10 + 1 + 10) = ~42s, which leaves room under a 60s cap.
_TIMEOUT = 10
_RETRIES = 2
_RETRY_SLEEP = 1.0

# TWSE says this, and only this, when a date simply has no session. Any other
# non-OK stat ('查詢日期大於今日...', rate limiting, upstream errors) is a real
# failure and must not be mistaken for a quiet holiday.
_TWSE_NO_DATA = "沒有符合條件的資料"

# TWSE/TPEX equity tick table, keyed by the band of the candidate limit price.
# Validated 2026-07-17 against TPEX's own 次日漲停價/次日跌停價 across the
# 2026-07-16 session: 885/889 equities exact. The 4 misses were securities
# with a corporate action pending the *next* session plus one no-limit new
# listing — none of them contradict the table.
#
# ETFs/ETNs use a different (finer) tick scale and are excluded by
# _is_equity(), so this table is only ever applied to common stock.
TICKS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("10"), Decimal("0.01")),
    (Decimal("50"), Decimal("0.05")),
    (Decimal("100"), Decimal("0.10")),
    (Decimal("500"), Decimal("0.50")),
    (Decimal("1000"), Decimal("1.00")),
)
_TOP_TICK = Decimal("5.00")

_LIMIT_PCT = Decimal("0.10")
# A banded security can never move further than ±10%. Anything beyond this is
# a no-limit or expanded-limit security (new listing, certain reissues), so we
# report it without claiming it hit a limit it doesn't have.
_NO_LIMIT_PCT = Decimal("10.5")


def tick_of(price: Decimal) -> Decimal:
    """Tick size for the band containing `price`.

    Chosen by the band of the *candidate limit price*, not the reference
    price — a name can straddle a boundary (ref 96 → ×1.1 = 105.6 lands in
    the 100–500 band → 0.5 tick → limit-up 105.5).
    """
    for hi, tick in TICKS:
        if price < hi:
            return tick
    return _TOP_TICK


def limit_up(reference_price: Decimal) -> Decimal:
    """Highest tick-valid price at or below reference × 1.10."""
    raw = reference_price * (Decimal("1") + _LIMIT_PCT)
    tick = tick_of(raw)
    return (raw / tick).quantize(Decimal(1), rounding=ROUND_FLOOR) * tick


def limit_down(reference_price: Decimal) -> Decimal:
    """Lowest tick-valid price at or above reference × 0.90."""
    raw = reference_price * (Decimal("1") - _LIMIT_PCT)
    tick = tick_of(raw)
    return (raw / tick).quantize(Decimal(1), rounding=ROUND_CEILING) * tick


# ── Parsing ────────────────────────────────────────────────────────────────

def _dec(v: Any) -> Optional[Decimal]:
    """Parse an exchange numeric cell. '--', '', 'X' and None → None."""
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if not s or s in {"--", "-", "---"}:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _price(v: Any) -> Optional[Decimal]:
    """Parse a quoted bid/ask price, normalising 'no quote' to None.

    The two exchanges spell an exhausted book side differently: TWSE prints
    '--' while TPEX prints '0.00'. A real quote is never zero, so collapsing
    non-positive prices to None makes lock detection uniform across markets.
    """
    d = _dec(v)
    return d if d is not None and d > 0 else None


_TAG = re.compile(r"<[^>]+>")


def _sign(v: Any) -> Optional[int]:
    """Read the 漲跌(+/-) column.

    TWSE wraps the glyph in styled HTML for colour (`<p style= color:red>+</p>`),
    so the tag has to come off before looking for the sign. A flat day is 'X'
    or an empty cell → 0.
    """
    s = _TAG.sub("", str(v or "")).strip()
    if "+" in s:
        return 1
    if "-" in s:
        return -1
    return 0


def _is_equity(code: str) -> bool:
    """4-digit numeric codes are common stock.

    ETFs/ETNs (5–6 digits, e.g. '006203', '00400A') and TPEX warrants are
    excluded: they carry different tick scales and, for some foreign-tracking
    ETFs, no price limit at all.
    """
    return len(code) == 4 and code.isdigit()


def _get_json(url: str, params: dict) -> tuple[Optional[dict], Optional[str]]:
    """GET with retries. TPEX intermittently truncates chunked responses."""
    last = ""
    for attempt in range(_RETRIES):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json(), None
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller
            last = f"{type(exc).__name__}: {exc}"
            if attempt < _RETRIES - 1:
                time.sleep(_RETRY_SLEEP)
    return None, last


# ── Row assembly ───────────────────────────────────────────────────────────

def _build_row(
    *,
    ticker_id: str,
    name: str,
    market: str,
    close: Optional[Decimal],
    change: Optional[Decimal],
    open_: Optional[Decimal],
    high: Optional[Decimal],
    low: Optional[Decimal],
    volume_shares: Optional[Decimal],
    turnover_twd: Optional[Decimal],
    bid_price: Optional[Decimal],
    bid_lots: Optional[Decimal],
    ask_price: Optional[Decimal],
    ask_lots: Optional[Decimal],
) -> Optional[dict]:
    if close is None or change is None:
        return None
    reference = close - change
    if reference <= 0:
        return None

    pct = (change / reference) * Decimal("100")
    has_limit = abs(pct) <= _NO_LIMIT_PCT
    lu = limit_up(reference) if has_limit else None
    ld = limit_down(reference) if has_limit else None

    at_up = bool(has_limit and lu is not None and close >= lu)
    at_down = bool(has_limit and ld is not None and close <= ld)

    # Locked = at the limit with a one-sided book at the close, i.e. the
    # 漲停鎖住 state. `_price` has already collapsed each exchange's
    # "no quote" spelling to None, so the exhausted side reads as absent.
    locked: Optional[bool] = None
    if at_up:
        locked = ask_price is None and bid_price is not None and bid_price >= lu
    elif at_down:
        locked = bid_price is None and ask_price is not None and ask_price <= ld

    return {
        "ticker_id": ticker_id,
        "name": name,
        "market": market,
        "reference_price": float(reference),
        "limit_up_price": float(lu) if lu is not None else None,
        "limit_down_price": float(ld) if ld is not None else None,
        "last_price": float(close),
        "open": float(open_) if open_ is not None else None,
        "high": float(high) if high is not None else None,
        "low": float(low) if low is not None else None,
        "change": float(change),
        "pct_change": float(round(pct, 2)),
        "has_price_limit": has_limit,
        "is_at_limit": at_up or at_down,
        "limit_direction": "up" if at_up else ("down" if at_down else None),
        "is_locked": locked,
        "bid_price_at_close": float(bid_price) if bid_price is not None else None,
        "bid_lots_at_close": int(bid_lots) if bid_lots is not None else None,
        "ask_price_at_close": float(ask_price) if ask_price is not None else None,
        "ask_lots_at_close": int(ask_lots) if ask_lots is not None else None,
        "volume_shares": int(volume_shares) if volume_shares is not None else None,
        "turnover_twd": int(turnover_twd) if turnover_twd is not None else None,
        # Realtime-only fields, per the spec's EOD contract.
        "lock_time": None,
    }


def fetch_twse_board(date_compact: str) -> tuple[list[dict], Optional[str]]:
    """Every TWSE equity for `date_compact` (YYYYMMDD)."""
    j, err = _get_json(
        TWSE_MI_INDEX,
        {"response": "json", "date": date_compact, "type": "ALLBUT0999"},
    )
    if err:
        return [], f"TWSE MI_INDEX fetch failed: {err}"
    if not j:
        return [], "TWSE MI_INDEX returned an empty response"

    stat = str(j.get("stat") or "")
    if stat != "OK":
        if _TWSE_NO_DATA in stat:
            return [], None  # genuine non-trading day — caller walks back
        # Anything else is a refusal, not a holiday. Reporting it as "no data"
        # would let the caller answer with TPEX alone and call it the market.
        return [], f"TWSE MI_INDEX refused the query: {stat}"

    # Locate the all-stocks table by its columns; MI_INDEX ships ~10 tables
    # (indices, market stats, the board) and their order is not contractual.
    table = None
    for t in j.get("tables") or []:
        fields = t.get("fields") or []
        if "證券代號" in fields and "收盤價" in fields:
            table = t
            break
    if table is None:
        return [], "TWSE MI_INDEX: all-stocks table not found in payload"

    rows = []
    for r in table.get("data") or []:
        if len(r) < 15:
            continue
        code = str(r[0]).strip()
        if not _is_equity(code):
            continue
        sign = _sign(r[9])
        diff = _dec(r[10])
        change = None if diff is None else diff * Decimal(sign)
        row = _build_row(
            ticker_id=code,
            name=str(r[1]).strip(),
            market="TWSE",
            close=_dec(r[8]),
            change=change,
            open_=_dec(r[5]),
            high=_dec(r[6]),
            low=_dec(r[7]),
            volume_shares=_dec(r[2]),
            turnover_twd=_dec(r[4]),
            bid_price=_price(r[11]),
            bid_lots=_dec(r[12]),
            ask_price=_price(r[13]),
            ask_lots=_dec(r[14]),
        )
        if row:
            rows.append(row)
    return rows, None


def fetch_tpex_board(date_slashed: str) -> tuple[list[dict], Optional[str]]:
    """Every TPEX mainboard equity for `date_slashed` (YYYY/MM/DD).

    TPEX gives us nothing to check: `stat` is 'ok' for a real session, for a
    weekend, and for a date past the end of time alike, and a *malformed* date
    silently returns today's board rather than an error — which is why callers
    must validate the date before it reaches here. An empty result therefore
    can't be distinguished from a failure at this level; `scan_limit_board`
    catches the dangerous case by comparing per-market coverage instead.
    """
    j, err = _get_json(
        TPEX_DAILY_QUOTES,
        {"response": "json", "date": date_slashed, "type": "AL"},
    )
    if err:
        return [], f"TPEX dailyQuotes fetch failed: {err}"
    if not j:
        return [], "TPEX dailyQuotes returned an empty response"
    tables = j.get("tables") or []
    if not tables:
        return [], None

    rows = []
    for r in tables[0].get("data") or []:
        if len(r) < 15:
            continue
        code = str(r[0]).strip()
        if not _is_equity(code):
            continue
        # TPEX signs 漲跌 inline ('-3.26'); no separate direction column.
        row = _build_row(
            ticker_id=code,
            name=str(r[1]).strip(),
            market="TPEX",
            close=_dec(r[2]),
            change=_dec(r[3]),
            open_=_dec(r[4]),
            high=_dec(r[5]),
            low=_dec(r[6]),
            volume_shares=_dec(r[8]),
            turnover_twd=_dec(r[9]),
            bid_price=_price(r[11]),
            bid_lots=_dec(r[12]),
            ask_price=_price(r[13]),
            ask_lots=_dec(r[14]),
        )
        if row:
            rows.append(row)
    return rows, None


def filter_board(
    rows: list[dict],
    *,
    direction: str,
    min_pct: float,
    locked_only: bool,
    min_turnover_twd: int,
) -> list[dict]:
    """Apply the §1 selection filters.

    `min_pct` admits near-limit names too, not just those that printed the
    limit — a name can close at -9.59% with the limit at -9.9% and still be
    the story of the day. `is_at_limit` distinguishes them.
    """
    out = []
    for r in rows:
        pct = r["pct_change"]
        if direction == "up" and pct < min_pct:
            continue
        if direction == "down" and pct > -min_pct:
            continue
        if direction == "both" and abs(pct) < min_pct:
            continue
        if locked_only and not r["is_locked"]:
            continue
        if min_turnover_twd and (r["turnover_twd"] or 0) < min_turnover_twd:
            continue
        out.append(r)
    out.sort(key=lambda r: -abs(r["pct_change"]))
    return out


# ── Triage (§6 — the tw-equity-alpha rubric) ───────────────────────────────

_SLEEPER_REQUIRED = frozenset({"cheap", "accumulating"})


def apply_triage(hit: dict) -> dict:
    """Attach `sleeper_flags` + `triage` to an enriched hit.

    Answers "base-breakout or chase?" — the half of board triage that the
    at-limit list alone can't. Returns a new dict; does not mutate `hit`.

    A null enrichment field simply fails its test rather than raising, with
    one deliberate exception: a null `pe_ratio` is itself the `no_earnings`
    anti-flag, because TWSE publishes '-' precisely when the issuer has no
    positive earnings. That only holds where valuation data exists at all —
    see `_valuation_known`.
    """
    flags: list[str] = []

    pe = hit.get("pe_ratio")
    div_yield = hit.get("dividend_yield")
    held = hit.get("foreign_held_pct")
    z20 = hit.get("foreign_net_z20")
    below_high = hit.get("pct_below_52w_high")
    margin_pct = hit.get("margin_pct_of_limit")
    net_5d = hit.get("foreign_net_5d")

    if pe is not None and 0 < pe < 20:
        flags.append("cheap")
    if div_yield is not None and div_yield >= 3:
        flags.append("yield")
    if held is not None and held < 20:
        flags.append("under_owned")
    if z20 is not None and z20 > 1:
        flags.append("accumulating")
    if below_high is not None and below_high < -25:
        flags.append("off_highs")
    if margin_pct is not None and margin_pct < 5:
        flags.append("no_froth")

    anti: list[str] = []
    # Distinguish "no earnings" from "we have no valuation row at all".
    # Treating a TPEX coverage gap as a loss-making signal would silently
    # label most of the 上櫃 board a chase — which is where the action is.
    if pe is None and hit.get("_valuation_known"):
        anti.append("no_earnings")
    if pe is not None and pe > 40:
        anti.append("story_premium")
    if net_5d is not None and net_5d < 0 and hit.get("is_at_limit"):
        anti.append("distributing_into_pop")

    flags.extend(anti)

    if _SLEEPER_REQUIRED <= set(flags) and not anti:
        triage = "sleeper"
    elif anti:
        triage = "chase"
    else:
        triage = "watch"

    out = {**hit, "sleeper_flags": flags, "triage": triage}
    out.pop("_valuation_known", None)  # internal marker, not part of the schema
    return out
