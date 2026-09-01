"""Macro series — the overnight forces a beta market wakes up to.

Taiwan trades as a high-beta expression of the US semiconductor cycle and the
dollar. Everything else this repo harvests is Taiwan-domestic and T+1; these
five series are the only data that is ALREADY KNOWN before the Taipei open,
which is what makes them worth a table:

    sox      ^SOX      Philadelphia Semiconductor Index — the cycle
    tsm_adr  TSM       TSMC ADR — the standard tell for the TAIEX open gap
    us10y    ^TNX      US 10Y yield — the liquidity regime
    dxy      DX-Y.NYB  dollar index — risk appetite
    usdtwd   TWD=X     USD/TWD — the foreign-flow tell

Two vendors on purpose. Yahoo's chart endpoint carries all five, but FRED is
the official publisher for the 10Y and needs no key, so `us10y` is split off:
a Yahoo outage then costs four series, not five, and the split is the cheapest
possible hedge against a single free vendor disappearing.

STRUCTURE: every parse function here is PURE — bytes in, rows out, no network,
no clock. That is not stylistic. This container's egress is a GitHub/PyPI
allowlist that blocks Yahoo, FRED *and* www.twse.com.tw alike, so the fetch
path CANNOT be exercised where this code is written; only the parsers can. The
tests therefore drive the parsers over captured payloads, and the network layer
is kept thin enough to read.

NOT A TRADING CALENDAR. `raw_twse_index` is the authoritative "did Taiwan
trade" oracle (loader.margin_sessions_missing, riskguard.store.last_trading_day).
Macro rows exist for US sessions on days the TWSE was shut — never join this
table to infer a Taiwan session.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC

import requests

from src.config import HTTP_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# series key → Yahoo symbol. Order is display order in the brief.
YAHOO_SERIES: dict[str, str] = {
    "sox": "^SOX",
    "tsm_adr": "TSM",
    "dxy": "DX-Y.NYB",
    "usdtwd": "TWD=X",
}

# series key → FRED series id.
FRED_SERIES: dict[str, str] = {
    "us10y": "DGS10",
}

ALL_SERIES: tuple[str, ...] = (*YAHOO_SERIES, *FRED_SERIES)


def _pct(close: float | None, prev: float | None) -> float | None:
    if close is None or prev in (None, 0):
        return None
    return round((close / prev - 1) * 100, 4)


def parse_yahoo_chart(payload: dict, series: str) -> list[dict]:
    """Yahoo v8 chart JSON → raw_macro rows, newest last.

    Yahoo returns aligned parallel arrays (timestamps, closes) in which a close
    can be null for a session with no print. Those are dropped rather than
    forward-filled: a null is "no data", and inventing a flat day would show up
    downstream as a real 0.00% move.
    """
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return []
    block = result[0]
    stamps = block.get("timestamp") or []
    quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []

    pairs = [
        (ts, c) for ts, c in zip(stamps, closes, strict=False) if c is not None
    ]
    rows = []
    for i, (ts, close) in enumerate(pairs):
        prev = pairs[i - 1][1] if i else None
        rows.append({
            "date": _utc_date(ts),
            "series": series,
            "close": round(float(close), 6),
            "prev_close": round(float(prev), 6) if prev is not None else None,
            "pct_change": _pct(float(close), float(prev) if prev is not None else None),
            "source": "yahoo_chart_v8",
        })
    return rows


def _utc_date(epoch_seconds: int) -> str:
    """Epoch → YYYY-MM-DD in UTC.

    UTC, not Asia/Taipei, and deliberately so: these are US-session closes, and
    a US close stamped with a Taipei date would land a day ahead and silently
    misalign every join against a Taiwan trading date. The consumer knows this
    column means "the US session that had already closed".
    """
    from datetime import datetime
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).date().isoformat()


def parse_fred_csv(text: str, series: str) -> list[dict]:
    """FRED fredgraph.csv → raw_macro rows, newest last.

    FRED writes '.' for a no-print day (US holidays), which float() would raise
    on — those rows are skipped, same contract as a Yahoo null.
    """
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    if len(fields) < 2:
        return []
    date_col, value_col = fields[0], fields[1]

    clean = []
    for row in reader:
        raw = (row.get(value_col) or "").strip()
        if not raw or raw == ".":
            continue
        try:
            clean.append((row[date_col].strip(), float(raw)))
        except (ValueError, KeyError):
            continue

    rows = []
    for i, (date, close) in enumerate(clean):
        prev = clean[i - 1][1] if i else None
        rows.append({
            "date": date,
            "series": series,
            "close": round(close, 6),
            "prev_close": round(prev, 6) if prev is not None else None,
            "pct_change": _pct(close, prev),
            "source": "fred_csv",
        })
    return rows


def _get(url: str) -> requests.Response:
    resp = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT
    )
    resp.raise_for_status()
    return resp


def fetch_series(days: int = 7) -> tuple[list[dict], list[str]]:
    """Fetch every series. Returns (rows, errors).

    Partial failure is the expected case, not the exception: five series across
    two vendors, and one 429 should not cost the other four. Errors come back
    as strings for the caller to log rather than raising, so the harvest step
    can record what it got AND what it missed.
    """
    rows: list[dict] = []
    errors: list[str] = []
    span = f"{max(days, 2)}d"

    for series, symbol in YAHOO_SERIES.items():
        try:
            url = YAHOO_CHART.format(symbol=requests.utils.quote(symbol, safe=""))
            resp = _get(f"{url}?interval=1d&range={span}")
            got = parse_yahoo_chart(resp.json(), series)
            if not got:
                errors.append(f"{series}: yahoo returned no usable bars")
            rows.extend(got)
        except Exception as e:
            errors.append(f"{series}: {type(e).__name__}: {e}")

    for series, series_id in FRED_SERIES.items():
        try:
            resp = _get(FRED_CSV.format(series_id=series_id))
            got = parse_fred_csv(resp.text, series)[-max(days, 2):]
            if not got:
                errors.append(f"{series}: fred returned no usable rows")
            rows.extend(got)
        except Exception as e:
            errors.append(f"{series}: {type(e).__name__}: {e}")

    return rows, errors
