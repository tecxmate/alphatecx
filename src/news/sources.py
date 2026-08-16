"""News source registry — RSS feeds + Google News query templates.

Tier A: confirmed-working RSS endpoints with high signal for our universe.
Tier B: Google News query feeds — flexible, infinite variations. Both
English and Traditional Chinese versions to capture Taiwan-domestic
coverage that doesn't have native RSS endpoints (Focus Taiwan, Taipei
Times, Taiwan News).

Adding a new source:
1. Test the URL with `python -c "import feedparser; print(len(feedparser.parse('URL').entries))"`
2. Pick a stable short `key` — used as `raw_news.source` in the DB.
3. Set `lang` to 'en' or 'zh-Hant'.
4. Append to RSS_SOURCES or GOOGLE_NEWS_QUERIES.

Removing a source:
- Delete the entry. Existing rows keyed to that source remain — historical
  record. The freshness check in sc_data_status will flag the source as
  stale, which is the right signal.
"""
from __future__ import annotations

import urllib.parse

# ── Tier A — direct RSS endpoints ─────────────────────────────────────────
RSS_SOURCES: list[dict] = [
    {
        "key": "digitimes",
        "feed_name": "DIGITIMES Asia",
        "url": "https://www.digitimes.com/rss/daily.xml",
        "lang": "en",
    },
    {
        "key": "nikkei-asia",
        "feed_name": "Nikkei Asia",
        "url": "https://asia.nikkei.com/rss/feed/nar",
        "lang": "en",
    },
    {
        "key": "bloomberg-tech",
        "feed_name": "Bloomberg Technology",
        "url": "https://feeds.bloomberg.com/technology/news.rss",
        "lang": "en",
    },
    {
        "key": "bloomberg-markets",
        "feed_name": "Bloomberg Markets",
        "url": "https://feeds.bloomberg.com/markets/news.rss",
        "lang": "en",
    },
    {
        "key": "fed-press",
        "feed_name": "Federal Reserve press releases",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "lang": "en",
    },
    {
        "key": "ecb-press",
        "feed_name": "ECB press",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "lang": "en",
    },
]


# ── Tier B — Google News query feeds ──────────────────────────────────────
# Pattern: https://news.google.com/rss/search?q=<query>&hl=<lang>&gl=<geo>&ceid=<geo>:<lang>
# `lang` and `geo` shape what coverage Google surfaces; the most useful
# combination for Taiwan-domestic stories is hl=zh-TW, gl=TW, ceid=TW:zh-Hant
# even when the query is mixed English/Chinese.

def _gnews(query: str, hl: str = "en", gl: str = "US") -> str:
    ceid = f"{gl}:{hl.split('-')[0]}"
    qs = urllib.parse.urlencode({"q": query, "hl": hl, "gl": gl, "ceid": ceid})
    return f"https://news.google.com/rss/search?{qs}"


GOOGLE_NEWS_QUERIES: list[dict] = [
    {
        "key": "gnews-tw-semis-en",
        "feed_name": "Google News — Taiwan semiconductor supply chain (EN)",
        "url": _gnews("Taiwan semiconductor supply chain", "en", "US"),
        "lang": "en",
    },
    {
        "key": "gnews-tw-ai-zh",
        "feed_name": "Google News — TSMC/Foxconn/AI servers (zh-TW)",
        "url": _gnews("台積電 OR 鴻海 OR AI伺服器", "zh-TW", "TW"),
        "lang": "zh-Hant",
    },
    {
        "key": "gnews-tw-stocks-zh",
        "feed_name": "Google News — Taiwan institutional flow (zh-TW)",
        "url": _gnews("台股 法人 外資", "zh-TW", "TW"),
        "lang": "zh-Hant",
    },
    {
        "key": "gnews-geo-tw",
        "feed_name": "Google News — Taiwan Strait geopolitics (EN)",
        "url": _gnews("Taiwan Strait China US tensions", "en", "US"),
        "lang": "en",
    },
    {
        "key": "gnews-fed-rates",
        "feed_name": "Google News — Federal Reserve rates (EN)",
        "url": _gnews("Federal Reserve interest rates inflation", "en", "US"),
        "lang": "en",
    },
    {
        "key": "gnews-supply-chain-en",
        "feed_name": "Google News — semis export controls (EN)",
        "url": _gnews("semiconductor supply chain export controls", "en", "US"),
        "lang": "en",
    },
]


def all_sources() -> list[dict]:
    """Combined feed list. Each entry has at minimum
    {key, feed_name, url, lang}."""
    return RSS_SOURCES + GOOGLE_NEWS_QUERIES
