"""TWSE + TPEX data fetching.

Ported from alphatecx v1 (mcp_server/api/sources.py), adapted for batch
ingestion with date-parameterized queries. All functions return plain dicts
(not Polars frames) — transformation happens in transform.py.

Endpoints:
  T86 (三大法人):    www.twse.com.tw/rwd/zh/fund/T86
  TPEX dailyTrade:  www.tpex.org.tw/www/zh-tw/insti/dailyTrade
  MI_QFIIS:         www.twse.com.tw/rwd/zh/fund/MI_QFIIS
  TPEX QFII:        www.tpex.org.tw/www/zh-tw/insti/qfii
  MI_MARGN:          www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN
  TPEX margin:       www.tpex.org.tw/www/zh-tw/margin/balance
  STOCK_DAY:         www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY
  TPEX tradingStock: www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock
  MOPS revenue:      openapi.twse.com.tw/v1/opendata/t187ap05_L
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from typing import Any

import requests

from src.config import HTTP_TIMEOUT, TWSE_REQUEST_DELAY, USER_AGENT

log = logging.getLogger("twse")

UA = {"User-Agent": USER_AGENT}
_SESSION = requests.Session()
_SESSION.headers.update(UA)

# ── URLs ────────────────────────────────────────────────────────────────────

TWSE_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_DLY = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"

TWSE_MI_QFIIS = "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS"
TPEX_QFII = "https://www.tpex.org.tw/www/zh-tw/insti/qfii"

TWSE_MI_MARGN = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TPEX_MARGIN = "https://www.tpex.org.tw/www/zh-tw/margin/balance"

TWSE_STOCK_DAY = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
TPEX_TRADING_STOCK = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"

TWSE_BWIBBU = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
TWSE_MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"

MOPS_TWSE_REV = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
MOPS_TPEX_REV = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"

TWSE_HOLIDAYS = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
TWSE_EX_DIVIDEND = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"   # 除權除息計算結果表 (actual)
TWSE_EX_FORECAST = "https://www.twse.com.tw/rwd/zh/exRight/TWT48U"   # 除權除息預告表 (upcoming)

# The published schedule lists both closures and the open reference days that
# bracket a break ('開始交易日' after it, '最後交易日' before it). Only the former
# close the market; these two substrings mark the latter.
_OPEN_REFERENCE_MARKERS = ("開始交易", "最後交易")

# ── Column indices (verified 2026-04) ───────────────────────────────────────

_TWSE_T86 = dict(code=0, name=1, foreign_net=4, trust_net=10, dealer_net=11, total_net=18)
_TPEX_DLY = dict(code=0, name=1, foreign_net=10, trust_net=13, dealer_net=22, total_net=23)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _to_int(v: Any) -> int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0


def _to_float(v: Any) -> float | None:
    if v in (None, "", "--"):
        return None
    try:
        return float(str(v).replace(",", "").replace("X", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def _roc_to_iso(roc: str) -> str:
    """Convert ROC date '115/04/29' -> '2026-04-29'."""
    parts = roc.strip().split("/")
    if len(parts) != 3:
        return roc
    y = int(parts[0]) + 1911
    return f"{y:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def _rate_limit():
    """Sleep to respect TWSE rate limits."""
    time.sleep(TWSE_REQUEST_DELAY)


def _get_json(url: str, params: dict) -> dict | None:
    """HTTP GET with timeout and error handling."""
    try:
        r = _SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("fetch failed %s %s: %s", url, params, e)
        return None


def trading_day_candidates(n: int = 7, from_date: date | None = None) -> list[str]:
    """Return up to n recent weekday dates as YYYYMMDD strings."""
    out: list[str] = []
    d = from_date or date.today()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


def trading_days_range(days: int, from_date: date | None = None) -> list[str]:
    """Return `days` weekday dates going backwards from `from_date`, oldest first."""
    candidates = trading_day_candidates(days, from_date)
    candidates.reverse()  # oldest first
    return candidates


# ── T86: Institutional Flow ─────────────────────────────────────────────────

def fetch_twse_t86(target_date: str) -> list[dict]:
    """Fetch TWSE T86 for a specific date (YYYYMMDD). Returns list of row dicts."""
    j = _get_json(TWSE_T86, {"response": "json", "date": target_date, "selectType": "ALLBUT0999"})
    if not j or j.get("stat") != "OK":
        return []
    rows = []
    for row in j.get("data") or []:
        if len(row) <= _TWSE_T86["total_net"]:
            continue
        rows.append({
            "date": f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}",
            "ticker_id": str(row[_TWSE_T86["code"]]).strip(),
            "company_name": str(row[_TWSE_T86["name"]]).strip(),
            "market": "TWSE",
            "foreign_net": _to_int(row[_TWSE_T86["foreign_net"]]),
            "trust_net": _to_int(row[_TWSE_T86["trust_net"]]),
            "dealer_net": _to_int(row[_TWSE_T86["dealer_net"]]),
            "total_net": _to_int(row[_TWSE_T86["total_net"]]),
        })
    log.info("TWSE T86 %s: %d rows", target_date, len(rows))
    return rows


def fetch_tpex_t86(target_date: str) -> list[dict]:
    """Fetch TPEX dailyTrade for a specific date (YYYYMMDD). Returns list of row dicts."""
    j = _get_json(TPEX_DLY, {"type": "Daily", "sect": "AL", "date": target_date, "response": "json"})
    if not j:
        return []
    tables = j.get("tables") or []
    if not tables:
        return []
    rows = []
    for row in tables[0].get("data") or []:
        if len(row) <= _TPEX_DLY["total_net"]:
            continue
        rows.append({
            "date": f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}",
            "ticker_id": str(row[_TPEX_DLY["code"]]).strip(),
            "company_name": str(row[_TPEX_DLY["name"]]).strip(),
            "market": "TPEX",
            "foreign_net": _to_int(row[_TPEX_DLY["foreign_net"]]),
            "trust_net": _to_int(row[_TPEX_DLY["trust_net"]]),
            "dealer_net": _to_int(row[_TPEX_DLY["dealer_net"]]),
            "total_net": _to_int(row[_TPEX_DLY["total_net"]]),
        })
    log.info("TPEX dailyTrade %s: %d rows", target_date, len(rows))
    return rows


def fetch_all_t86(target_date: str) -> list[dict]:
    """Fetch both TWSE + TPEX institutional flow for one date."""
    rows = fetch_twse_t86(target_date)
    _rate_limit()
    rows.extend(fetch_tpex_t86(target_date))
    return rows


# ── MI_QFIIS: Foreign Holdings ──────────────────────────────────────────────

def fetch_twse_holdings(target_date: str) -> list[dict]:
    """Fetch TWSE MI_QFIIS foreign holdings for a specific date."""
    j = _get_json(TWSE_MI_QFIIS, {"response": "json", "date": target_date, "selectType": "ALLBUT0999"})
    if not j or j.get("stat") != "OK":
        return []
    rows = []
    for row in j.get("data") or []:
        if len(row) < 8:
            continue
        code = str(row[0]).strip()
        if not code or not code[0].isdigit():
            continue
        rows.append({
            "date": f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}",
            "ticker_id": code,
            "company_name": str(row[1]).strip(),
            "market": "TWSE",
            "shares_outstanding": _to_int(row[3]),
            "foreign_held_shares": _to_int(row[5]),
            "foreign_held_pct": _to_float(row[7]),
            "foreign_room_pct": _to_float(row[6]),
        })
    log.info("TWSE MI_QFIIS %s: %d rows", target_date, len(rows))
    return rows


def fetch_tpex_holdings(target_date: str) -> list[dict]:
    """Fetch TPEX QFII foreign holdings for a specific date."""
    ymd = f"{target_date[:4]}/{target_date[4:6]}/{target_date[6:8]}"
    j = _get_json(TPEX_QFII, {"date": ymd, "response": "json"})
    if not j:
        return []
    tables = j.get("tables") or []
    if not tables:
        return []
    rows = []
    for row in tables[0].get("data") or []:
        if len(row) < 9:
            continue
        code = str(row[1]).strip()
        if not code or not code[0].isdigit():
            continue
        rows.append({
            "date": f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}",
            "ticker_id": code,
            "company_name": str(row[2]).strip(),
            "market": "TPEX",
            "shares_outstanding": _to_int(row[3]),
            "foreign_held_shares": _to_int(row[5]),
            "foreign_held_pct": _to_float(row[7]),
            "foreign_room_pct": _to_float(row[6]),
        })
    log.info("TPEX QFII %s: %d rows", target_date, len(rows))
    return rows


def fetch_all_holdings(target_date: str) -> list[dict]:
    """Fetch both TWSE + TPEX foreign holdings for one date."""
    rows = fetch_twse_holdings(target_date)
    _rate_limit()
    rows.extend(fetch_tpex_holdings(target_date))
    return rows


# ── Margin Balance ──────────────────────────────────────────────────────────

def fetch_twse_margin(target_date: str) -> list[dict]:
    """Fetch TWSE MI_MARGN margin/short balance for a specific date."""
    j = _get_json(TWSE_MI_MARGN, {"response": "json", "date": target_date, "selectType": "STOCK"})
    if not j:
        return []
    rows = []
    for t in j.get("tables") or []:
        for row in t.get("data") or []:
            if len(row) < 14:
                continue
            code = str(row[0]).strip()
            if not code.isdigit():
                continue
            margin_bal = _to_int(row[6])
            margin_prev = _to_int(row[5])
            short_bal = _to_int(row[12])
            short_prev = _to_int(row[11])
            rows.append({
                "date": f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}",
                "ticker_id": code,
                "company_name": str(row[1]).strip(),
                "market": "TWSE",
                "margin_balance": margin_bal,
                "margin_change": margin_bal - margin_prev,
                "margin_limit": _to_int(row[7]),
                "short_balance": short_bal,
                "short_change": short_bal - short_prev,
                "short_limit": _to_int(row[13]),
            })
    log.info("TWSE MI_MARGN %s: %d rows", target_date, len(rows))
    return rows


def fetch_tpex_margin(target_date: str) -> list[dict]:
    """Fetch TPEX margin/short balance for a specific date."""
    ymd = f"{target_date[:4]}/{target_date[4:6]}/{target_date[6:8]}"
    j = _get_json(TPEX_MARGIN, {"date": ymd, "response": "json"})
    if not j:
        return []
    tables = j.get("tables") or []
    if not tables:
        return []
    rows = []
    for row in tables[0].get("data") or []:
        if len(row) < 18:
            continue
        code = str(row[0]).strip()
        if not code.isdigit():
            continue
        margin_bal = _to_int(row[6])
        margin_prev = _to_int(row[2])
        short_bal = _to_int(row[14])
        short_prev = _to_int(row[10])
        rows.append({
            "date": f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}",
            "ticker_id": code,
            "company_name": str(row[1]).strip(),
            "market": "TPEX",
            "margin_balance": margin_bal,
            "margin_change": margin_bal - margin_prev,
            "margin_limit": _to_int(row[9]),
            "short_balance": short_bal,
            "short_change": short_bal - short_prev,
            "short_limit": _to_int(row[17]),
        })
    log.info("TPEX margin %s: %d rows", target_date, len(rows))
    return rows


def fetch_all_margin(target_date: str) -> list[dict]:
    """Fetch both TWSE + TPEX margin balance for one date."""
    rows = fetch_twse_margin(target_date)
    _rate_limit()
    rows.extend(fetch_tpex_margin(target_date))
    return rows


# ── OHLCV Daily Bars ────────────────────────────────────────────────────────
# Note: OHLCV is per-stock-per-month, not per-date. Different backfill pattern.

def fetch_twse_ohlcv_month(code: str, year: int, month: int) -> list[dict]:
    """Fetch one month of TWSE STOCK_DAY bars for one stock."""
    d = f"{year:04d}{month:02d}01"
    j = _get_json(TWSE_STOCK_DAY, {"response": "json", "date": d, "stockNo": code})
    if not j or j.get("stat") != "OK":
        return []
    bars = []
    for row in j.get("data") or []:
        if len(row) < 7:
            continue
        bars.append({
            "date": _roc_to_iso(row[0]),
            "ticker_id": code,
            "market": "TWSE",
            "open": _to_float(row[3]),
            "high": _to_float(row[4]),
            "low": _to_float(row[5]),
            "close": _to_float(row[6]),
            "volume_shares": _to_int(row[1]),
            "turnover_twd": _to_int(row[2]),
        })
    return bars


def fetch_tpex_ohlcv_month(code: str, year: int, month: int) -> list[dict]:
    """Fetch one month of TPEX tradingStock bars for one stock."""
    d = f"{year:04d}/{month:02d}/01"
    j = _get_json(TPEX_TRADING_STOCK, {"date": d, "code": code, "response": "json"})
    if not j:
        return []
    tables = j.get("tables") or []
    if not tables:
        return []
    bars = []
    for row in tables[0].get("data") or []:
        if len(row) < 7:
            continue
        bars.append({
            "date": _roc_to_iso(row[0]),
            "ticker_id": code,
            "market": "TPEX",
            "open": _to_float(row[3]),
            "high": _to_float(row[4]),
            "low": _to_float(row[5]),
            "close": _to_float(row[6]),
            "volume_shares": _to_int(row[1]) * 1000,   # TPEX uses lots
            "turnover_twd": _to_int(row[2]) * 1000,     # 仟元 -> TWD
        })
    return bars


# ── Monthly Revenue (MOPS) ──────────────────────────────────────────────────

def fetch_mops_revenue(market: str = "TWSE") -> list[dict]:
    """Fetch latest monthly revenue from MOPS. Returns all companies at once."""
    url = MOPS_TWSE_REV if market == "TWSE" else MOPS_TPEX_REV
    try:
        r = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
        data = r.json()
        if not isinstance(data, list) or not data:
            return []
    except Exception as e:
        log.warning("MOPS revenue fetch failed (%s): %s", market, e)
        return []

    rows = []
    for row in data:
        code = str(row.get("公司代號", "")).strip()
        if not code:
            continue
        ym = str(row.get("資料年月", ""))
        iso_ym = None
        if len(ym) == 5:
            iso_ym = f"{int(ym[:3]) + 1911:04d}-{int(ym[3:]):02d}"

        rows.append({
            "ym": iso_ym,
            "ticker_id": code,
            "company_name": (row.get("公司名稱") or "").strip(),
            "market": market,
            "industry": (row.get("產業別") or "").strip(),
            "revenue_k_twd": _to_int(row.get("營業收入-當月營收")),
            "mom_pct": _to_float(row.get("營業收入-上月比較增減(%)")),
            "yoy_pct": _to_float(row.get("營業收入-去年同月增減(%)")),
            "ytd_revenue": _to_int(row.get("累計營業收入-當月累計營收")),
            "ytd_prev_year": _to_int(row.get("累計營業收入-去年累計營收")),
            "ytd_yoy_pct": _to_float(row.get("累計營業收入-前期比較增減(%)")),
        })
    log.info("MOPS revenue %s: %d rows", market, len(rows))
    return rows


# ── BWIBBU_d: per-ticker valuation (P/E, P/B, dividend yield) ───────────────

def fetch_twse_valuation(target_date: str) -> list[dict]:
    """Fetch TWSE per-ticker valuation metrics for a specific date.

    BWIBBU_d returns one row per listed common stock with that day's close,
    dividend yield (%), dividend ROC year, P/E, P/B, and the fiscal period
    those ratios reference. P/E is '-' when the issuer has no positive
    earnings; we coerce that to NULL.
    """
    j = _get_json(TWSE_BWIBBU, {"response": "json", "date": target_date})
    if not j or j.get("stat") != "OK":
        return []
    rows = []
    for row in j.get("data") or []:
        if len(row) < 8:
            continue
        ticker = str(row[0]).strip()
        if not ticker:
            continue
        rows.append({
            "date": f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}",
            "ticker_id": ticker,
            "company_name": str(row[1]).strip(),
            "market": "TWSE",
            "close": _to_float(row[2]),
            "dividend_yield": _to_float(row[3]),
            "dividend_year": _to_int(row[4]) if str(row[4]).strip() != "-" else None,
            "pe_ratio": _to_float(row[5]),
            "pb_ratio": _to_float(row[6]),
            "fiscal_period": str(row[7]).strip() if row[7] else None,
        })
    log.info("TWSE BWIBBU_d %s: %d rows", target_date, len(rows))
    return rows


# ── Holiday schedule: trading calendar ──────────────────────────────────────

def fetch_twse_holidays(year: int) -> list[dict]:
    """Fetch the TWSE published market-holiday schedule for a Gregorian `year`.

    Returns one dict per schedule entry with `is_closed` classified: a row is a
    closure unless its name marks an open reference day (開始交易/最後交易) — the
    schedule lists those alongside real closures. 市場無交易 (settlement-only)
    days carry neither marker and are correctly kept as closures.

    The endpoint expects a ROC query year (Gregorian − 1911).
    """
    roc = year - 1911
    j = _get_json(TWSE_HOLIDAYS, {"response": "json", "queryYear": str(roc)})
    if not j or str(j.get("stat", "")).lower() != "ok":
        return []
    rows = []
    for row in j.get("data") or []:
        if len(row) < 2:
            continue
        iso = str(row[0]).strip()
        if len(iso) != 10 or iso[4] != "-":  # guard against schema drift
            continue
        name = str(row[1]).strip()
        note = str(row[2]).strip() if len(row) > 2 and row[2] else None
        is_closed = not any(m in name for m in _OPEN_REFERENCE_MARKERS)
        rows.append({
            "cal_date": iso,
            "name": name,
            "is_closed": is_closed,
            "note": note,
            "source": "twse",
        })
    log.info("TWSE holidays %d (ROC %d): %d rows", year, roc, len(rows))
    return rows


# ── Ex-dividend / ex-rights calendar (TWT49U actual, TWT48U forecast) ───────

def _roc_cn_to_iso(s: str) -> str | None:
    """Convert a ROC Chinese date '115年07月01日' -> '2026-07-01'."""
    m = re.match(r"\s*(\d{2,3})年(\d{1,2})月(\d{1,2})日", str(s))
    if not m:
        return None
    y = int(m.group(1)) + 1911
    return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def fetch_twse_ex_dividend(start: str, end: str) -> list[dict]:
    """Actual ex-dividend/ex-rights results (TWT49U) over [start, end] (YYYYMMDD).

    Each row is a stock's ex trading date, the 權/息 type, the combined
    權值+息值 value, and the pre-ex close + reference price. `ex_date` is what
    matters for 'does a buyer today get it?' — on/after it, they do not.
    """
    j = _get_json(TWSE_EX_DIVIDEND, {"response": "json", "startDate": start, "endDate": end})
    if not j or str(j.get("stat", "")).upper() != "OK":
        return []
    rows = []
    for r in j.get("data") or []:
        if len(r) < 7:
            continue
        iso = _roc_cn_to_iso(r[0])
        code = str(r[1]).strip()
        if not iso or not code:
            continue
        rows.append({
            "ex_date": iso,
            "ticker_id": code,
            "name": str(r[2]).strip(),
            "pre_ex_close": _to_float(r[3]),
            "reference_price": _to_float(r[4]),
            "cash_value": _to_float(r[5]),
            "ex_type": str(r[6]).strip() or None,
            "status": "actual",
        })
    log.info("TWSE TWT49U %s-%s: %d ex-dividend rows", start, end, len(rows))
    return rows


def fetch_twse_ex_forecast() -> list[dict]:
    """Upcoming ex-dividend/ex-rights forecast (TWT48U). No date args — TWSE
    returns the current forward schedule."""
    j = _get_json(TWSE_EX_FORECAST, {"response": "json"})
    if not j or str(j.get("stat", "")).upper() != "OK":
        return []
    rows = []
    for r in j.get("data") or []:
        if len(r) < 8:
            continue
        iso = _roc_cn_to_iso(r[0])
        code = str(r[1]).strip()
        if not iso or not code:
            continue
        rows.append({
            "ex_date": iso,
            "ticker_id": code,
            "name": str(r[2]).strip(),
            "ex_type": str(r[3]).strip() or None,
            "cash_value": _to_float(r[7]),   # 現金股利
            "pre_ex_close": None,
            "reference_price": None,
            "status": "forecast",
        })
    log.info("TWSE TWT48U forecast: %d rows", len(rows))
    return rows


# ── MI_INDEX: sector & cross-market indices ─────────────────────────────────

def fetch_twse_indices(target_date: str) -> list[dict]:
    """Fetch TWSE sector / cross-market index closes & changes for a date.

    MI_INDEX with type=IND returns multi-table JSON. The first table is
    'TWSE 價格指數' (TAIEX + per-sector indices, ~56 rows); the second is
    cross-market indices (~48 rows). We flatten both.
    """
    j = _get_json(TWSE_MI_INDEX, {"response": "json", "date": target_date, "type": "IND"})
    if not j:
        return []
    rows = []
    for table in j.get("tables") or []:
        for row in table.get("data") or []:
            if len(row) < 5:
                continue
            name = str(row[0]).strip()
            if not name or "指數" not in name:
                continue
            # TWSE wraps the direction sign in styled HTML for color; strip it.
            raw_dir = str(row[2] or "")
            direction = "+" if "+" in raw_dir else ("-" if "-" in raw_dir else None)
            rows.append({
                "date": f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}",
                "index_name": name,
                "close": _to_float(row[1]),
                "direction": direction,
                "change_pts": _to_float(row[3]),
                "change_pct": _to_float(row[4]),
            })
    log.info("TWSE MI_INDEX %s: %d index rows", target_date, len(rows))
    return rows
