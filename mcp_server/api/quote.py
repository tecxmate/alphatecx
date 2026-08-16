"""On-demand realtime-ish quotes from TWSE MIS (watchlist only).

TWSE MIS (`mis.twse.com.tw`) is the authoritative intraday feed, and crucially
the only source that publishes the pre-tick-rounded limit prices (`u`/`w`) live.
It is rate-limited (~3 requests / 5s) and needs a session cookie primed from
`index.jsp`, so this serves a **watchlist** (≤ ~50 symbols per request), never a
market sweep — that would need a persistent poller, which the stateless Vercel
function can't host (same constraint that keeps scan_limit_board EOD-only).

The pre-open auction (08:30–09:00) publishes a 試撮 *simulated* price in `z`.
This module never decides that on its own — the tool layer stamps indicative
using `session_state` — but it does refuse to invent a price: when `z` is `-`
(no trade yet) `last_price` is None rather than a silent fall-through to prev
close.
"""
from __future__ import annotations

import time
from typing import Any

import requests

MIS_INDEX = "https://mis.twse.com.tw/stock/index.jsp"
MIS_API = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"

_UA = {"User-Agent": "Mozilla/5.0 (compatible; alphatecx/2.0)"}
_TIMEOUT = 10
_BATCH = 50            # MIS truncates long ex_ch lists; keep well under the cap
_BATCH_SLEEP = 2.0     # stay under ~3 req / 5s
_MAX_SYMBOLS = 100     # watchlist ceiling — never a market sweep


def _num(v: Any) -> float | None:
    """Parse a MIS numeric string. '-', '', None → None (no false zero)."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _first(pipe: Any) -> float | None:
    """First level of an `_`-delimited MIS depth string (best bid/ask)."""
    if not pipe:
        return None
    return _num(str(pipe).split("_")[0])


def parse_msg(m: dict) -> dict:
    """Turn one MIS `msgArray` entry into a clean quote.

    `is_at_limit` uses the authoritative `u`/`w` (already tick-rounded by TWSE) —
    never recomputed here. A missing last price (`z` = '-') yields
    is_at_limit=None, not a false limit hit off a stale reference.
    """
    last = _num(m.get("z"))
    prev = _num(m.get("y"))
    lim_up = _num(m.get("u"))
    lim_down = _num(m.get("w"))

    at_up = last is not None and lim_up is not None and last >= lim_up
    at_down = last is not None and lim_down is not None and last <= lim_down

    pct = None
    if last is not None and prev:
        pct = round((last / prev - 1) * 100, 2)

    return {
        "ticker_id": m.get("c"),
        "name": m.get("n"),
        "market": "TWSE" if m.get("ex") == "tse" else ("TPEX" if m.get("ex") == "otc" else None),
        "last_price": last,
        "prev_close": prev,
        "pct_change": pct,
        "limit_up_price": lim_up,
        "limit_down_price": lim_down,
        "is_at_limit": (at_up or at_down) if last is not None else None,
        "limit_direction": "up" if at_up else ("down" if at_down else None),
        "open": _num(m.get("o")),
        "high": _num(m.get("h")),
        "low": _num(m.get("l")),
        "best_bid": _first(m.get("b")),
        "best_ask": _first(m.get("a")),
        "volume_shares_lots": _num(m.get("v")),
        "last_trade_lots": _num(m.get("tv")),
        "quote_time": m.get("t") or None,
        "quote_date": m.get("d") or None,
    }


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_UA)
    try:
        s.get(MIS_INDEX, timeout=_TIMEOUT)   # prime the cookie MIS requires
    except requests.RequestException:
        pass  # the API call below will surface a real failure
    return s


def fetch_quotes(ex_ch: list[str]) -> tuple[list[dict], str | None]:
    """Fetch MIS quotes for pre-built `ex_ch` tokens (e.g. 'tse_2330.tw').

    Batches at `_BATCH`, sleeping between batches to respect the rate limit.
    Returns (raw msgArray dicts, error). A non-zero `rtcode` is a real failure
    and is reported rather than returned as empty.
    """
    if not ex_ch:
        return [], None
    s = _session()
    out: list[dict] = []
    for i in range(0, len(ex_ch), _BATCH):
        batch = ex_ch[i:i + _BATCH]
        try:
            r = s.get(MIS_API, params={"ex_ch": "|".join(batch), "json": "1", "delay": "0"},
                      timeout=_TIMEOUT)
            r.raise_for_status()
            j = r.json()
        except Exception as exc:  # noqa: BLE001 — surfaced to caller
            return out, f"MIS fetch failed: {type(exc).__name__}: {exc}"
        if str(j.get("rtcode")) != "0000":
            return out, f"MIS refused the query: rtcode={j.get('rtcode')} {j.get('rtmessage')}"
        out.extend(j.get("msgArray") or [])
        if i + _BATCH < len(ex_ch):
            time.sleep(_BATCH_SLEEP)
    return out, None
