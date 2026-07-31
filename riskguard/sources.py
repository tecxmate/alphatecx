"""New external feeds for M1 (PRD §2 table). Both are free and public.

  breadth   TWSE MI_INDEX type=MS → 漲跌證券數合計
  futures   TAIFEX futContractsDateDown → 臺股期貨 外資及陸資 net open interest

Parsing is split from fetching so the parsers can be unit-tested on captured
payloads without a network call — the shapes here are undocumented and change
without notice, so a test that only exercises "requests works" is worthless.

Every fetch returns None on failure rather than raising. PRD §7 requires a
single dead source not to take down the pipeline; the scorer then marks that
subitem `data_missing` and the light says so out loud.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import time
from typing import Optional

import requests

from src.config import HTTP_TIMEOUT, TWSE_REQUEST_DELAY, USER_AGENT

log = logging.getLogger("riskguard.sources")

TWSE_MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TAIFEX_INST = "https://www.taifex.com.tw/cht/3/futContractsDateDown"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT})

_BREADTH_TABLE_TITLE = "漲跌證券數合計"
# Counts arrive as '224(2)' — total, with the limit-hitting subset in parens.
_COUNT_RE = re.compile(r"^([\d,]+)")


def _rate_limit() -> None:
    time.sleep(TWSE_REQUEST_DELAY)


def _count(cell: str) -> Optional[int]:
    m = _COUNT_RE.match(str(cell).strip())
    return int(m.group(1).replace(",", "")) if m else None


def parse_breadth(payload: dict) -> Optional[dict]:
    """Extract advance/decline counts from an MI_INDEX type=MS response.

    Uses the 股票 column, not 整體市場: the latter counts warrants, ETFs and
    convertibles, which swamp the ~1,000 common stocks and would make the
    breadth ratio measure the warrant market instead of the equity market.
    """
    for table in payload.get("tables") or []:
        if table.get("title") != _BREADTH_TABLE_TITLE:
            continue
        rows = [r for r in table.get("data") or [] if len(r) >= 3]
        adv_row = next((r for r in rows if str(r[0]).startswith("上漲")), None)
        dec_row = next((r for r in rows if str(r[0]).startswith("下跌")), None)
        if not adv_row or not dec_row:
            return None
        adv, dec = _count(adv_row[2]), _count(dec_row[2])
        if adv is None or dec is None:
            return None
        return {"adv_count": adv, "dec_count": dec}
    return None


def fetch_breadth(target_date: str) -> Optional[dict]:
    """Advance/decline counts for one session. `target_date` is YYYYMMDD."""
    try:
        _rate_limit()
        resp = _SESSION.get(
            TWSE_MI_INDEX,
            params={"response": "json", "date": target_date, "type": "MS"},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        log.warning("MI_INDEX MS %s failed: %s", target_date, e)
        return None

    if payload.get("stat") != "OK":
        log.warning("MI_INDEX MS %s: stat=%s", target_date, payload.get("stat"))
        return None
    result = parse_breadth(payload)
    if result is None:
        log.warning("MI_INDEX MS %s: 漲跌證券數合計 table not found", target_date)
    return result


_TAIFEX_PRODUCT = "臺股期貨"
_TAIFEX_INVESTOR = "外資及陸資"
_TAIFEX_NET_OI_COL = "多空未平倉口數淨額"


def parse_taifex_oi(text: str) -> Optional[int]:
    """Foreign net futures open interest from the daily institutional CSV.

    Positive = net long, negative = net short. Only 臺股期貨 (TX) counts; the
    electronics and finance contracts are separate products whose OI would
    double-count the index exposure this subitem is measuring.
    """
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        product = (row.get("商品名稱") or "").strip()
        investor = (row.get("身份別") or "").strip()
        if product != _TAIFEX_PRODUCT or investor != _TAIFEX_INVESTOR:
            continue
        raw = (row.get(_TAIFEX_NET_OI_COL) or "").strip().replace(",", "")
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def fetch_foreign_futures_oi(date_iso: str) -> Optional[int]:
    """Fetch foreign net OI for one session. `date_iso` is YYYY-MM-DD.

    The endpoint answers Big5-encoded CSV and returns a header-only body for
    non-trading days, which parse_taifex_oi reports as None.
    """
    slashed = date_iso.replace("-", "/")
    try:
        resp = _SESSION.post(
            TAIFEX_INST,
            data={
                "firstDate": slashed, "lastDate": slashed,
                "queryStartDate": slashed, "queryEndDate": slashed,
                "commodityId": "",
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.content.decode("big5", errors="replace")
    except Exception as e:
        log.warning("TAIFEX %s failed: %s", date_iso, e)
        return None

    oi = parse_taifex_oi(text)
    if oi is None:
        log.warning("TAIFEX %s: no %s / %s row", date_iso, _TAIFEX_PRODUCT, _TAIFEX_INVESTOR)
    return oi
