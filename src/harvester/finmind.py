"""FinMind enrichment harvester (Tool Review v2 Phase 2).

Fetches three FinMind datasets (free tier, 600 req/hr) and reshapes them for the
loader. The MCP read path never touches FinMind — this runs in the nightly
harvester and lands in Neon (see sql/017_finmind.sql):

  * ``TaiwanStockDividend``        → cash/stock dividend split + per-leg ex-dates
  * ``TaiwanStockDividendResult``  → per-ex before/after/max prices → 填息 history
  * ``TaiwanStockNews``            → material/governance news overlay

Everything that transforms a payload is a pure function (parsers,
``fill_probability``, ``is_governance_title``) so the score-relevant logic —
"does this dividend historically refill?" — is unit-tested directly rather than
only observed live.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date, timedelta
from typing import Any, Optional

import requests

from src.config import FINMIND_REQUEST_DELAY, FINMIND_TOKEN, HTTP_TIMEOUT

log = logging.getLogger(__name__)

FINMIND_API = "https://api.finmindtrade.com/api/v4/data"

# Governance-risk watchlist (v2 #4). A title matching any of these earns
# `is_governance` — surfaced for human judgement, never an auto-downgrade.
GOVERNANCE_KEYWORDS = (
    "洗錢", "掏空", "內線", "財報不實", "下市", "違約交割", "搜索", "起訴",
    "背信", "假帳", "淘空", "收押", "羈押", "弊案",
)


# ── pure helpers ────────────────────────────────────────────────────────────
def _to_float(v: Any) -> Optional[float]:
    if v in (None, "", "--"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _date_or_none(v: Any) -> Optional[str]:
    """FinMind dates are 'YYYY-MM-DD' (news is 'YYYY-MM-DD HH:MM:SS'). Take the
    date part; return None for blanks/zeros."""
    if not v:
        return None
    s = str(v)[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None


def _greg_year(v: Any) -> Optional[int]:
    """Normalize FinMind's dividend `year` ('114年', '114', '2025') to Gregorian.
    ROC years (< 1911) get +1911."""
    if v is None:
        return None
    m = re.search(r"\d+", str(v))
    if not m:
        return None
    y = int(m.group())
    return y + 1911 if y < 1911 else y


def is_governance_title(title: str) -> bool:
    return any(k in (title or "") for k in GOVERNANCE_KEYWORDS)


def parse_dividend_policy(raw: list[dict], ticker_id: str) -> list[dict]:
    """TaiwanStockDividend rows → one record per (ticker, year). cash/stock are
    earnings + statutory-surplus distributions summed (both 元/股)."""
    out: list[dict] = []
    for r in raw:
        yr = _greg_year(r.get("year"))
        if yr is None:
            continue
        cash = (_to_float(r.get("CashEarningsDistribution")) or 0.0) + (
            _to_float(r.get("CashStatutorySurplus")) or 0.0
        )
        stock = (_to_float(r.get("StockEarningsDistribution")) or 0.0) + (
            _to_float(r.get("StockStatutorySurplus")) or 0.0
        )
        out.append({
            "ticker_id": ticker_id,
            "year": yr,
            "cash_dividend": round(cash, 4),
            "stock_dividend": round(stock, 4),
            "cash_ex_date": _date_or_none(r.get("CashExDividendTradingDate")),
            "stock_ex_date": _date_or_none(r.get("StockExDividendTradingDate")),
            "announcement_date": _date_or_none(r.get("AnnouncementDate")),
        })
    return out


def parse_dividend_result(raw: list[dict], ticker_id: str) -> list[dict]:
    """TaiwanStockDividendResult rows → one record per ex event."""
    out: list[dict] = []
    for r in raw:
        ex = _date_or_none(r.get("date"))
        if not ex:
            continue
        out.append({
            "ticker_id": ticker_id,
            "ex_date": ex,
            "before_price": _to_float(r.get("before_price")),
            "after_price": _to_float(r.get("after_price")),
            "reference_price": _to_float(r.get("reference_price")),
            "max_price": _to_float(r.get("max_price")),
            "min_price": _to_float(r.get("min_price")),
        })
    return out


def parse_news(raw: list[dict], ticker_id: str) -> list[dict]:
    """TaiwanStockNews rows → news records with a stable title_hash PK and the
    governance flag precomputed."""
    out: list[dict] = []
    for r in raw:
        d = _date_or_none(r.get("date"))
        title = (r.get("title") or "").strip()
        if not d or not title:
            continue
        out.append({
            "ticker_id": ticker_id,
            "news_date": d,
            "title": title,
            "title_hash": hashlib.md5(title.encode("utf-8")).hexdigest(),
            "news_source": (r.get("source") or "").strip() or None,
            "url": (r.get("link") or r.get("url") or "").strip() or None,
            "is_governance": is_governance_title(title),
        })
    return out


def fill_probability(
    result_rows: list[dict], as_of: str, years: int = 5
) -> tuple[Optional[float], int, Optional[str]]:
    """填息 (dividend gap-refill) probability over the trailing `years`.

    A dividend "fills" when the post-ex price recovers to the pre-ex close, i.e.
    ``max_price >= before_price``. Returns (probability, event_count, last_ex).
    Probability is None when no usable event falls in the window — the caller
    must treat unknown as 'not a trap', never as 0.
    """
    try:
        asof_d = date.fromisoformat(as_of[:10])
    except (TypeError, ValueError):
        return None, 0, None
    cutoff = asof_d - timedelta(days=365 * years)
    filled = 0
    total = 0
    last_ex: Optional[str] = None
    for r in result_rows:
        ex = r.get("ex_date")
        try:
            ex_d = date.fromisoformat(str(ex)[:10])
        except (TypeError, ValueError):
            continue
        if ex_d < cutoff or ex_d > asof_d:
            continue
        before = r.get("before_price")
        mx = r.get("max_price")
        if before is None or mx is None or before <= 0:
            continue
        total += 1
        if mx >= before:
            filled += 1
        if last_ex is None or ex > last_ex:
            last_ex = ex
    if total == 0:
        return None, 0, last_ex
    return round(filled / total, 3), total, last_ex


def fill_stats_record(ticker_id: str, result_rows: list[dict], as_of: str) -> dict:
    prob, events, last_ex = fill_probability(result_rows, as_of)
    return {
        "ticker_id": ticker_id,
        "fill_probability_5y": prob,
        "events_5y": events,
        "last_ex_date": last_ex,
        "computed_as_of": as_of[:10],
    }


# ── IO ──────────────────────────────────────────────────────────────────────
_SESSION = requests.Session()


def token_configured() -> bool:
    return bool(FINMIND_TOKEN)


def _get(dataset: str, data_id: str, start_date: str) -> Optional[list[dict]]:
    """One FinMind v4 data call. Returns the data list, [] on a level/permission
    block (400), or None on a rate-limit (402) or transport error so the caller
    can distinguish 'no data' from 'stop hammering'."""
    if not FINMIND_TOKEN:
        return None
    try:
        r = _SESSION.get(
            FINMIND_API,
            params={"dataset": dataset, "data_id": data_id,
                    "start_date": start_date, "token": FINMIND_TOKEN},
            timeout=HTTP_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — logged, surfaced as None
        log.warning("FinMind %s %s transport error: %s", dataset, data_id, e)
        return None
    if r.status_code == 402:
        log.warning("FinMind rate limit hit (402) on %s %s", dataset, data_id)
        return None
    if r.status_code == 400:
        log.info("FinMind %s not available on this tier: %s", dataset, r.text[:120])
        return []
    try:
        return r.json().get("data") or []
    except Exception:  # noqa: BLE001
        return []


def _rate_limit() -> None:
    time.sleep(FINMIND_REQUEST_DELAY)


def fetch_dividend_policy(ticker_id: str, start: str = "2015-01-01") -> list[dict]:
    raw = _get("TaiwanStockDividend", ticker_id, start)
    return parse_dividend_policy(raw or [], ticker_id) if raw is not None else []


def fetch_dividend_result(ticker_id: str, start: str = "2018-01-01") -> list[dict]:
    raw = _get("TaiwanStockDividendResult", ticker_id, start)
    return parse_dividend_result(raw or [], ticker_id) if raw is not None else []


def fetch_news(ticker_id: str, start: str) -> list[dict]:
    raw = _get("TaiwanStockNews", ticker_id, start)
    return parse_news(raw or [], ticker_id) if raw is not None else []
