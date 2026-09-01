"""Macro series — the global tape a high-beta market is priced against.

Taiwan trades as a high-beta expression of the US semiconductor cycle, the
dollar, and its own regional peers. Everything else this repo harvests is
Taiwan-domestic and T+1; these series are the outside world.

WHEN A SERIES IS KNOWABLE IS PART OF ITS MEANING, and it is not uniform.
This module originally carried five US/FX series and its docstring said they
were "already known before the Taipei open" — true of all five. Adding the
Asian peers broke that: **Tokyo, Seoul, Shanghai and Hong Kong trade at the
same time as Taipei.** Their prints are concurrent information, not overnight
news, and a brief that recites a live KOSPI as "overnight macro" is stating
something false about the world. So every series carries `when_known`:

    BEFORE_OPEN   the session had CLOSED before Taipei opened. Genuinely
                  overnight: it can inform the open.
    SAME_SESSION  the market trades alongside Taipei. The stored row is the
                  PREVIOUS close; today's move is happening as you read it.

Consumers must not flatten this. `q_macro` returns it per row and the
pre-market brief shows BEFORE_OPEN series only — at 08:30 Taipei the Asian
peers have not opened, so printing their T-1 close beside a fresh US close
would put two different ages of information on one line.

Two vendors on purpose. Yahoo's chart endpoint carries everything except the
10Y, but FRED is the official publisher for that one and needs no key, so
`us10y` is split off: a Yahoo outage then costs every series but one, and the
split is the cheapest possible hedge against a single free vendor vanishing.

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
import os
import time
from datetime import UTC

import requests

from src.config import HTTP_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# Seconds between Yahoo calls. See fetch_series for why this is not zero.
YAHOO_REQUEST_DELAY = float(os.getenv("MACRO_REQUEST_DELAY", "0.5"))

# When a series is knowable relative to the Taipei open. See the module
# docstring — this is the distinction the Asian peers introduced.
BEFORE_OPEN = "before_open"
SAME_SESSION = "same_session"

# The single source of truth for what this table contains. Insertion order is
# display order everywhere: US cycle first (it is what actually gaps the TAIEX
# open), then FX, then Europe, then the regional peers.
#
# `market` groups them for the `market=` filter; `label` is the short form the
# brief and the console print. One dict rather than four parallel maps, because
# four parallel maps is precisely how `sc_capabilities` drifted to 33 of 48.
SERIES_META: dict[str, dict[str, str]] = {
    # ── United States: closed hours before Taipei opens ───────────────────
    "sox": {"symbol": "^SOX", "vendor": "yahoo", "market": "us",
            "label": "SOX", "when_known": BEFORE_OPEN},
    "nasdaq": {"symbol": "^IXIC", "vendor": "yahoo", "market": "us",
               "label": "Nasdaq", "when_known": BEFORE_OPEN},
    "tsm_adr": {"symbol": "TSM", "vendor": "yahoo", "market": "us",
                "label": "TSM ADR", "when_known": BEFORE_OPEN},
    "us10y": {"symbol": "DGS10", "vendor": "fred", "market": "us",
              "label": "US 10Y", "when_known": BEFORE_OPEN},
    # ── FX: 24-hour, but the level that matters is the overnight one ──────
    "dxy": {"symbol": "DX-Y.NYB", "vendor": "yahoo", "market": "fx",
            "label": "DXY", "when_known": BEFORE_OPEN},
    "usdtwd": {"symbol": "TWD=X", "vendor": "yahoo", "market": "fx",
               "label": "USD/TWD", "when_known": BEFORE_OPEN},
    # ── Europe: closes ~00:30 Taipei, so it IS overnight information ──────
    "estoxx50": {"symbol": "^STOXX50E", "vendor": "yahoo", "market": "europe",
                 "label": "Euro Stoxx 50", "when_known": BEFORE_OPEN},
    # ── Asia-Pacific peers: these trade WITH Taipei, not before it ────────
    # Korea is the one that matters most and the one most often left out:
    # Samsung and SK Hynix make the KOSPI a memory-cycle read on the same
    # customers Taiwan sells into, so KOSPI/TAIEX divergence is a signal
    # rather than noise. Japan carries the semicap complex (Tokyo Electron,
    # Advantest). Shanghai is mainland demand; Hang Seng is where China tech
    # is actually priced — different animals, so both, not one as a proxy.
    "nikkei": {"symbol": "^N225", "vendor": "yahoo", "market": "japan",
               "label": "Nikkei", "when_known": SAME_SESSION},
    "kospi": {"symbol": "^KS11", "vendor": "yahoo", "market": "korea",
              "label": "KOSPI", "when_known": SAME_SESSION},
    "shanghai": {"symbol": "000001.SS", "vendor": "yahoo", "market": "china",
                 "label": "Shanghai", "when_known": SAME_SESSION},
    "hangseng": {"symbol": "^HSI", "vendor": "yahoo", "market": "hong_kong",
                 "label": "Hang Seng", "when_known": SAME_SESSION},
}

ALL_SERIES: tuple[str, ...] = tuple(SERIES_META)

# Derived, never hand-maintained — the vendor field above is the only place a
# series is assigned to a fetcher.
YAHOO_SERIES: dict[str, str] = {
    k: m["symbol"] for k, m in SERIES_META.items() if m["vendor"] == "yahoo"
}
FRED_SERIES: dict[str, str] = {
    k: m["symbol"] for k, m in SERIES_META.items() if m["vendor"] == "fred"
}

MARKETS: tuple[str, ...] = tuple(
    dict.fromkeys(m["market"] for m in SERIES_META.values())
)


def series_in_market(market: str) -> list[str]:
    """Series keys for one market, in display order. Empty for an unknown one."""
    want = (market or "").strip().lower()
    return [k for k, m in SERIES_META.items() if m["market"] == want]


def before_open_series() -> list[str]:
    """Series that had CLOSED before Taipei opened — what a pre-market brief
    may honestly present as overnight information."""
    return [k for k, m in SERIES_META.items() if m["when_known"] == BEFORE_OPEN]


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

    UTC, not Asia/Taipei, and deliberately so: a US close stamped with a Taipei
    date lands a day ahead and silently misaligns every join against a Taiwan
    trading date. The column means "the date of that market's own session".

    THE INVARIANT THIS RELIES ON, and the trap for whoever extends the list:
    Yahoo stamps a daily bar at the session OPEN, so this is only the session's
    own local date while that open falls on the same UTC day. It holds for every
    market here — Tokyo opens 00:00 UTC, Hong Kong 01:30, Frankfurt 08:00, New
    York 14:30 — but it is a property of these exchanges, not of the code. An
    exchange opening before 00:00 UTC would be stamped a day EARLY: the ASX
    (10:00 AEDT = 23:00 UTC the previous day) is the near miss. Adding one means
    converting through the exchange's own timezone, not reusing this.
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

    Partial failure is the expected case, not the exception: eleven series
    across two vendors, and one 429 should not cost the other ten. Errors come
    back as strings for the caller to log rather than raising, so the harvest
    step can record what it got AND what it missed.

    The inter-request pause exists because this list grew from four Yahoo calls
    to ten in one change. Four unspaced calls never drew a 429; ten is a
    different ask of a free endpoint, and a 429 here costs a whole series for
    the day. Five seconds a night is not a cost worth optimising.
    """
    rows: list[dict] = []
    errors: list[str] = []
    span = f"{max(days, 2)}d"

    for i, (series, symbol) in enumerate(YAHOO_SERIES.items()):
        if i:
            time.sleep(YAHOO_REQUEST_DELAY)
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
