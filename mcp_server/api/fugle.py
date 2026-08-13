"""Fugle Market Data — realtime quotes (the upgrade tier over TWSE MIS).

Fugle (https://developer.fugle.tw/docs/data) is a keyed realtime feed with a
developer-friendly REST API. It is the preferred `quote` source when
FUGLE_API_KEY is set: lower latency and a full 5-level book, without MIS's
cookie dance and 3-req/5s throttle.

REST: GET https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}
      header X-API-KEY: <key>

Quote is single-symbol (one call per code), so this stays a **watchlist** tool
like MIS — a market sweep still doesn't belong in the stateless serverless
function. Fugle does not return the price band, but it does return
`referencePrice`, so the limit-up/down prices are computed with the same
tick-rounding table scan_limit_board validated against the exchange
(`limit_board.limit_up/limit_down`) rather than left blank.
"""
from __future__ import annotations

import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import limit_board
import requests

FUGLE_QUOTE = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
_TIMEOUT = 8
_CALL_SLEEP = 0.15         # gentle spacing; Fugle 429s on plan-limit breach
_MAX_SYMBOLS = 40          # per-symbol calls — keep the watchlist bounded


def api_key() -> str | None:
    key = os.getenv("FUGLE_API_KEY")
    return key.strip() if key and key.strip() else None


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _best(levels: Any) -> tuple[float | None, int | None]:
    """Best (price, size) from Fugle's bids/asks list of {price,size}."""
    if not levels:
        return None, None
    top = levels[0] or {}
    return _num(top.get("price")), (int(top["size"]) if top.get("size") is not None else None)


def _limits(reference: float | None) -> tuple[float | None, float | None]:
    """Compute tick-rounded limit-up/down from the reference price, reusing the
    scan_limit_board table. None when the reference is missing/invalid."""
    if reference is None or reference <= 0:
        return None, None
    try:
        ref = Decimal(str(reference))
    except InvalidOperation:
        return None, None
    return float(limit_board.limit_up(ref)), float(limit_board.limit_down(ref))


def parse_quote(j: dict) -> dict:
    """Turn a Fugle intraday-quote payload into the shared quote shape.

    `is_at_limit` compares the last price to the tick-rounded band computed from
    `referencePrice`; a missing last price yields None (never a false hit).
    """
    last = _num(j.get("lastPrice"))
    prev = _num(j.get("previousClose"))
    reference = _num(j.get("referencePrice"))
    lim_up, lim_down = _limits(reference)

    at_up = last is not None and lim_up is not None and last >= lim_up
    at_down = last is not None and lim_down is not None and last <= lim_down

    bid_price, _bid_sz = _best(j.get("bids"))
    ask_price, _ask_sz = _best(j.get("asks"))
    total = j.get("total") or {}
    mkt = j.get("market")

    return {
        "ticker_id": str(j.get("symbol")) if j.get("symbol") is not None else None,
        "name": j.get("name"),
        "market": "TWSE" if mkt == "TSE" else ("TPEX" if mkt == "OTC" else None),
        "last_price": last,
        "prev_close": prev,
        "pct_change": _num(j.get("changePercent")),
        "limit_up_price": lim_up,
        "limit_down_price": lim_down,
        "is_at_limit": (at_up or at_down) if last is not None else None,
        "limit_direction": "up" if at_up else ("down" if at_down else None),
        "open": _num(j.get("openPrice")),
        "high": _num(j.get("highPrice")),
        "low": _num(j.get("lowPrice")),
        "best_bid": bid_price,
        "best_ask": ask_price,
        "volume_shares_lots": _num(total.get("tradeVolume")),
        "last_trade_lots": _num(j.get("lastSize")),
        "quote_time": _epoch_us_to_iso(j.get("lastUpdated")),
        "quote_date": j.get("date"),
    }


def _epoch_us_to_iso(us: Any) -> str | None:
    """Fugle timestamps are epoch microseconds; render as Taipei ISO."""
    if us is None:
        return None
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(int(us) / 1_000_000, ZoneInfo("Asia/Taipei")).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def fetch_quotes(symbols: list[str], key: str) -> tuple[list[dict], list[str]]:
    """Fetch Fugle quotes for `symbols` (one call each). Returns (raw payloads,
    errors). A per-symbol failure is recorded and skipped, not fatal — the
    caller still gets every symbol that answered."""
    out: list[dict] = []
    errors: list[str] = []
    headers = {"X-API-KEY": key}
    for i, sym in enumerate(symbols):
        try:
            r = requests.get(FUGLE_QUOTE.format(symbol=sym), headers=headers, timeout=_TIMEOUT)
            if r.status_code == 429:
                errors.append("Fugle rate limit hit (429); remaining symbols skipped")
                break
            r.raise_for_status()
            out.append(r.json())
        except Exception as exc:  # noqa: BLE001 — recorded per symbol
            errors.append(f"{sym}: {type(exc).__name__}: {exc}")
        if i + 1 < len(symbols):
            time.sleep(_CALL_SLEEP)
    return out, errors
