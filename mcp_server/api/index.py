"""alphatecx v2 MCP server — supply chain intelligence.

Tool naming convention:
  sc_*     supply chain views — pre-computed sector & ticker momentum
  raw_*    raw data queries   — drill-down into historical flow/holdings

Every response includes:
  _source     — e.g. "view_sector_momentum", "raw_twse_t86"
  _as_of      — ISO date of the data
  _freshness  — "T+1" (data from previous trading day)

Auth: URL-as-secret. Mount path is /mcp/<MCP_BEARER_TOKEN>/.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

# TWSE publishes data in Asia/Taipei. Using UTC mislabels _as_of for ~8 hours
# every day; provenance has to match the source's wall clock.
_TPE = ZoneInfo("Asia/Taipei")

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE.parent / ".env")
sys.path.insert(0, str(_HERE))

from html import escape as html_escape
from urllib.parse import quote_plus

import db_v2
import flow_leaders
import fugle as fugle_mod
import graph_view
import limit_board
import momentum_leaders
import quote as quote_mod
import session_state as session_state_mod
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from rg import checklist as rg_checklist_mod
from rg import db as rg_db
from rg import stops as rg_stops

try:
    import billing as billing_mod
    import console_pages
    import customers as customers_mod
    import oauth as oauth_mod
    import tiers as tiers_mod
    import usage as usage_mod
    from security import is_authorized_path, token_matches
except ModuleNotFoundError:  # package import path used by local tests
    from . import billing as billing_mod
    from . import console_pages
    from . import customers as customers_mod
    from . import oauth as oauth_mod
    from . import tiers as tiers_mod
    from . import usage as usage_mod
    from .security import is_authorized_path, token_matches

MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "")

# The console's own secret. Optional: unset, it falls back to the MCP token and
# nothing changes. Set, it decouples "can view the dashboard" from "can call the
# API" -- which is the point, because the two were the same string until
# 2026-08-16 and so sharing a dashboard URL also shared write access to all 49
# tools. Behind Cloudflare Access the console URL stops being the only control
# at all; this makes it stop being the API key as well.
CONSOLE_TOKEN = os.getenv("CONSOLE_TOKEN", "") or MCP_BEARER_TOKEN

log = logging.getLogger("mcp")

# Set by the auth gate to the authenticated token subject (a customer id, or
# "owner"), so _stamp() can meter the call without threading identity through
# all ~45 tool signatures. FastMCP runs each tool in the same asyncio task as
# the request, so a value set before call_next is visible inside the tool.
current_customer: ContextVar[str | None] = ContextVar("current_customer", default=None)

# The authenticated customer's plan, stashed by _customer_gate — which has
# already fetched the row, so this costs no extra query. Tier enforcement reads
# it per tool call; looking the customer up again there would double the DB
# reads on the hottest path in the server.
current_plan: ContextVar[str | None] = ContextVar("current_plan", default=None)

# The operator's subject. Both owner paths (the shared OAUTH_PASSWORD login and
# the URL-as-secret mount) resolve to it, and sql/025 reserves a `customers` row
# under this id so the owner can hold a risk profile like any customer. It is
# never metered and never billed — see _stamp.
OWNER_SUBJECT = "owner"

# Compliance line carried on every tool response so the consulting model always
# has it in front of it. Env-overridable so legal can adjust wording (and add a
# localised/bilingual version) without a code deploy. Not a substitute for the
# investment-advice-licensing question — see
# docs/wiki/topics/commercial-productization.md.
DISCLAIMER = os.environ.get(
    "ALPHATECX_DISCLAIMER",
    "Informational market data only — not investment, legal, or tax advice. "
    "Verify independently before acting.",
)


def _stamp(payload: dict, source: str, as_of: str | None, freshness: str,
           glossary: dict | None = None) -> dict:
    """Annotate a response with provenance + freshness + the compliance line.

    Every tool response funnels through here, so this is also the per-call
    metering choke point: count the call against the authenticated customer.
    Owner traffic (URL-secret path, or sub="owner") is not metered. record() is
    best-effort and never raises.

    `glossary` (optional) attaches a `_glossary` defining the jargon in THIS
    response, so the model labels metrics correctly instead of guessing. Use it
    selectively on beginner-facing tools — don't bloat every response."""
    cust = current_customer.get()
    if cust and cust != OWNER_SUBJECT:
        usage_mod.record(cust)
    stamped = {
        "_source": source,
        "_disclaimer": DISCLAIMER,
        "_as_of": as_of,
        "_freshness": freshness,
    }
    if glossary:
        stamped["_glossary"] = glossary
    stamped.update(payload)
    return stamped


# Small, response-scoped glossaries for the beginner-facing tools (passed to
# _stamp). Kept here so the definitions stay consistent with start_here's.
_MACRO_SERIES = ("sox", "tsm_adr", "us10y", "dxy", "usdtwd")

_GLOSS_MACRO = {
    "sox": "SOX — Philadelphia Semiconductor Index; the US chip cycle Taiwan tracks",
    "tsm_adr": "TSM — TSMC's US-listed share; its overnight move usually leads the TAIEX open",
    "us10y": "US 10Y — the 10-year Treasury yield in percent; higher tends to pressure growth equities",
    "dxy": "DXY — US dollar index; a stronger dollar often coincides with foreign selling in Taiwan",
    "usdtwd": "USD/TWD — a rising number means a weaker Taiwan dollar",
    "date": "the US SESSION date (UTC), not a Taiwan trading date",
}

_GLOSS_VALUATION = {
    "pe": "P/E — price per $1 of yearly earnings; lower can mean cheaper, or slower growth",
    "pb": "P/B — price per $1 of net assets (book value)",
    "dividend_yield": "yearly dividend as a % of the share price",
}
_GLOSS_STOCK_CARD = {
    **_GLOSS_VALUATION,
    "flow": "net shares bought minus sold by institutions (foreign / trust / dealer)",
}
_GLOSS_MOMENTUM = {
    "momentum_score": "0-100 on trend QUALITY (strength, structure, volume, "
                      "institutional backing) — not on how much it went up",
    "trailing_stop": "the price at which the trend is considered broken and the "
                     "position closes — momentum without a stop is just a bag of losers",
    "extension_above_ma50_pct": "how far above its 50-day average average price has run; "
                                "far above = late, not strong",
    "triage": "momentum-entry = early in a confirmed trend · watch = not yet · "
              "chase = do not enter (see flags)",
}
_GLOSS_RISK_LIGHT = {
    "risk_light": "green/yellow/red whole-market caution gauge (not about one stock)",
    "risk_score": "higher = more caution; drives the light",
}


def _today_iso() -> str:
    return datetime.now(_TPE).date().isoformat()


# ── MCP server ──────────────────────────────────────────────────────────────

# Connector-wide guidance Claude reads once on connect (MCP `instructions`). This
# is the single place for the persona — do NOT repeat "act like a teacher" in
# every tool description. Keep it tight; it rides in context for the session.
CONSULTANT_INSTRUCTIONS = """\
alphatecx is a Taiwan-equity (TWSE/TPEX) market-data service. You are using it to
consult for a NON-EXPERT retail investor. Be a clear teacher and analyst — not a
quant, and not a broker.

How to work:
- Start from the person's question in plain words. They won't know tool names or
  jargon; you choose the tools and the order.
- For a new user or an open-ended question, call `start_here` first to orient,
  then pick the simplest tool that answers what they actually asked.
- Define every finance term the first time you use it, in one plain sentence
  (e.g. "P/E — the price paid per $1 of the company's yearly earnings").
- Explain what the numbers MEAN and what to watch next — not just the raw figures.
- Chain tools when it helps: e.g. `ticker_lookup` to find the code, then
  `beginner_stock_card` for an overview, then `q_valuation` or
  `sc_ticker_momentum` to go deeper. `sc_capabilities` is the full technical map.
- Ground your reasoning in `investing_principles` — durable, school-neutral rules
  (margin of safety, know what you own, survival first…). Cite the principle and
  apply it; never preach, and never push one strategy (index vs pick) as gospel.

Risk profile (establish this early):
- Call `my_profile` near the start. If it returns a saved profile
  (conservative / balanced / aggressive), tailor EVERYTHING to it and follow the
  `how_to_adapt` it gives back. If it's null, ask the user how much risk they
  want and save it with `set_my_risk_profile`.
- conservative → lead with capital preservation, stable dividend-paying names,
  volatility and downside. aggressive → growth, momentum and higher-risk/
  higher-reward ideas are in scope, but always name the risk. balanced → weigh
  both. The same data means different emphasis for different people.

Boundaries and honesty:
- This is informational market data, NOT investment advice. Never tell the user to
  buy, sell, or hold — help them understand so they decide. Every response also
  carries a `_disclaimer`.
- Data is Taiwan-market and mostly T+1 (previous trading day) on Taipei time. Say
  so when it matters and cite the `_as_of` date. If data is missing or stale, say
  that plainly rather than guessing.
- Coverage is deepest on ~27 AI-supply-chain names; be honest about limits
  elsewhere.
"""

mcp = FastMCP(
    "alphatecx-v2",
    instructions=CONSULTANT_INSTRUCTIONS,
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


# ── Risk profile (personalization) ─────────────────────────────────────────

# How the model should adapt its framing to each tier. Returned by the profile
# tools so the guidance travels with the value.
_RISK_GUIDANCE = {
    "conservative": (
        "Lead with capital preservation. Favour stable, liquid, dividend-paying "
        "names; surface volatility, drawdown and downside first; avoid "
        "speculative or thinly-traded ideas unless explicitly asked."
    ),
    "balanced": (
        "Balance growth and safety. Mix quality compounders with some momentum; "
        "weigh upside against downside evenly."
    ),
    "aggressive": (
        "Optimise for return. Momentum, accumulation and higher-risk/higher-"
        "reward ideas are in scope — but always name the risk and a position-"
        "sizing caveat."
    ),
}
_ASK_RISK = ("Not set — ask whether the user is conservative, balanced, or "
             "aggressive, then call set_my_risk_profile.")


@mcp.tool()
def my_profile() -> dict:
    """The current user's saved risk profile, so you can tailor everything to it.

    Call this early. If `risk_profile` is null, ASK the user whether they are
    conservative, balanced, or aggressive and save it with `set_my_risk_profile`.
    Then follow `how_to_adapt`.
    """
    cust = current_customer.get()
    if not cust:
        return _stamp(
            {"risk_profile": None, "how_to_adapt": _ASK_RISK,
             "options": sorted(customers_mod.VALID_RISK),
             "note": "No per-user account on this session — ask their risk "
                     "tolerance and adapt within the conversation."},
            source="customer_profile", as_of=None, freshness="static")
    risk = customers_mod.get_risk(cust)
    profile = risk.get("risk_profile")
    return _stamp(
        {"risk_profile": profile,
         "risk_note": risk.get("risk_note"),
         "how_to_adapt": _RISK_GUIDANCE.get(profile, _ASK_RISK),
         "options": sorted(customers_mod.VALID_RISK)},
        source="customer_profile", as_of=None, freshness="static")


@mcp.tool()
def set_my_risk_profile(profile: str, note: str | None = None) -> dict:
    """Save the current user's risk profile once they tell you their tolerance.

    profile: 'conservative' | 'balanced' | 'aggressive'.
    note: optional free text (e.g. 'dividends only, no small caps').
    Call this after the user states or confirms how much risk they want.
    """
    cust = current_customer.get()
    if not cust:
        return _stamp(
            {"saved": False,
             "reason": "No per-user account on this session; can't persist. "
                       "Adapt within this conversation instead."},
            source="customer_profile", as_of=None, freshness="static")
    p = (profile or "").strip().lower()
    if p not in customers_mod.VALID_RISK:
        return _stamp(
            {"saved": False,
             "error": f"profile must be one of {sorted(customers_mod.VALID_RISK)}"},
            source="customer_profile", as_of=None, freshness="static")
    ok = customers_mod.set_risk_profile(cust, p, note)
    return _stamp(
        {"saved": ok, "risk_profile": p if ok else None,
         "how_to_adapt": _RISK_GUIDANCE[p] if ok else None},
        source="customer_profile", as_of=None, freshness="static")


# ── Investing principles (school-neutral) ──────────────────────────────────

# Durable principles the major schools AGREE on — value, index, growth and
# trading alike. Deliberately excludes contested doctrine (index-vs-pick,
# technical analysis, any specific strategy). Distilled in our own words and
# attributed to the thinkers who articulated each idea — NOT ingested text.
_PRINCIPLES = [
    {"principle": "Margin of safety",
     "says": "Never pay a price that needs everything to go right. Leave a buffer so a wrong assumption costs little.",
     "from": "Graham; echoed by Housel ('room for error')"},
    {"principle": "Know what you own",
     "says": "Only hold what you can explain in plain terms — the business, the risk, why it should pay off. If you can't, you're guessing.",
     "from": "Lynch, Fisher"},
    {"principle": "Survival first",
     "says": "Risk is what you can't afford to be wrong about. Size positions so no single loss can ruin you; staying in the game beats maximizing any one bet.",
     "from": "Housel; trading-discipline lineage (Douglas)"},
    {"principle": "Master your own psychology",
     "says": "The biggest risk is usually your behaviour — fear, greed, herding. Decide your rules before the moment, not during it.",
     "from": "Douglas, Housel; Graham's 'Mr. Market'"},
    {"principle": "Price is not value",
     "says": "The market's quote is a mood, not a verdict. Treat wild swings as opportunities or warnings, not truth about the business.",
     "from": "Graham"},
    {"principle": "Beware manias and 'this time is different'",
     "says": "Crowds plus leverage plus a great story precede most crashes. Extra skepticism exactly when everyone is euphoric.",
     "from": "Kindleberger; Dalio on cycles"},
    {"principle": "Time and compounding",
     "says": "Give good decisions time to compound; don't churn. Short-term volatility is not the same as permanent loss.",
     "from": "Bogle, Housel"},
    {"principle": "Costs and taxes compound against you",
     "says": "Every fee, spread and tax is a certain drag on an uncertain return. Minimize frictions.",
     "from": "Bogle"},
    {"principle": "Humility — process over outcome",
     "says": "You will be wrong often; a good decision can lose and a bad one can win. Judge the reasoning, not the last result.",
     "from": "Douglas; efficient-market humility"},
]

# Which universals to STRESS per risk tier — the principles don't change, only
# the emphasis does.
_PRINCIPLE_EMPHASIS = {
    "conservative": "Lead with margin of safety, diversification, low cost, and "
                    "capital preservation. Volatility they can't stomach is itself a risk.",
    "balanced": "Weigh margin of safety against opportunity; let quality compound "
                "while keeping position sizes sane.",
    "aggressive": "The universal guardrails matter MOST here — survival-first "
                  "sizing, psychology/discipline, and avoiding manias are what keep "
                  "high-risk bets from turning into ruin.",
}


@mcp.tool()
def investing_principles() -> dict:
    """Durable, school-neutral investing principles to ground your advice.

    Universal principles the major schools agree on (value, index, growth and
    trading alike) — NOT a specific strategy, and NOT stock-picking-vs-indexing
    dogma. Use them to frame HOW you explain and advise: name the principle,
    apply it to the user's situation, and lean hardest on the ones their risk
    profile most needs. If a `profile` is present, follow `emphasis_for_profile`.
    """
    cust = current_customer.get()
    profile = customers_mod.get_risk(cust).get("risk_profile") if cust else None
    return _stamp(
        {"principles": _PRINCIPLES,
         "profile": profile,
         "emphasis_for_profile": _PRINCIPLE_EMPHASIS.get(profile) if profile else None,
         "use": "Ground advice in these. They are universal — apply them within "
                "whatever the user is doing; don't turn them into a sales pitch "
                "for one strategy, and don't preach."},
        source="investing_principles", as_of=None, freshness="static")


# ── Tool: Start Here (onboarding) ──────────────────────────────────────────

@mcp.tool()
def start_here() -> dict:
    """START HERE for a new user or any open-ended / beginner question.

    Returns a plain-language menu — what a non-expert can ask, which tool answers
    each, and a beginner glossary — so you can orient the user and pick the right
    tool without them knowing any jargon. For the full technical tool map (AI
    supply-chain structure, all 44 tools), use `sc_capabilities` instead.
    """
    return _stamp(
        {
            "how_to_talk_to_me": (
                "Describe what you want in plain words — you don't need tool names "
                "or finance jargon. I'll pick the right data and explain it."
            ),
            "what_you_can_ask": [
                {"ask": "Give me a plain overview of a stock",
                 "use": "beginner_stock_card",
                 "note": "price, trend, who's buying, valuation and dividend in one card"},
                {"ask": "Is this stock cheap or expensive?", "use": "q_valuation",
                 "note": "P/E, P/B and dividend yield vs the stock's own history"},
                {"ask": "Who's buying or selling it?", "use": "sc_ticker_momentum",
                 "note": "foreign / trust / dealer net flow and buy streaks"},
                {"ask": "What's the price, and recent prices?", "use": "quote, price_history"},
                {"ask": "Which stocks are institutions accumulating?", "use": "flow_leaders_scan"},
                {"ask": "When are dividends paid, and how much?", "use": "dividend_calendar"},
                {"ask": "Is the market risky right now?", "use": "rg_status",
                 "note": "a market-risk light plus what's driving it"},
                {"ask": "Any recent news on a company?", "use": "n_for_ticker"},
                {"ask": "I don't know the stock code", "use": "ticker_lookup",
                 "note": "find the TWSE code from a company name"},
            ],
            "glossary": {
                "P/E ratio": "Price per $1 of the company's yearly earnings. Lower can mean cheaper — or slower growth.",
                "P/B ratio": "Price per $1 of the company's net assets (book value).",
                "Dividend yield": "The yearly dividend as a percentage of the share price.",
                "Foreign flow": "Net buying/selling by foreign institutional investors (FINI) — a major driver in Taiwan.",
                "Investment trust / dealer": "Local Taiwan institutions; their net flow signals domestic conviction.",
                "Margin balance": "How much investors have borrowed to buy shares; unusually high levels can signal froth.",
                "T+1 data": "Most figures reflect the previous trading day, on Taipei time.",
            },
            "personalize": (
                "Call `my_profile` — if the user's risk tolerance isn't saved, "
                "ask whether they're conservative, balanced, or aggressive and "
                "save it. It tailors how everything below is framed."
            ),
            "remember": "This is data to help you understand — not advice to buy or sell.",
        },
        source="onboarding_guide",
        as_of=None,
        freshness="static",
    )


# ── Tool: Sector Momentum ──────────────────────────────────────────────────

@mcp.tool()
def sc_sector_momentum(
    pillar: str | None = None,
    window: str = "5d",
    top_n: int = 10,
) -> dict:
    """Get sector-level institutional flow momentum across AI supply chain pillars.

    Shows aggregated foreign investor (FINI), investment trust, and dealer
    net flows by AI pillar and supply chain node. Useful for detecting which
    parts of the Taiwan AI supply chain are being accumulated or distributed.

    Args:
        pillar: Filter to a specific AI pillar: 'semiconductor', 'equipment',
                'infrastructure', 'energy', or None for all.
        window: Flow aggregation window: '1d', '3d', '5d', '10d', '20d'.
        top_n: Number of results (default 10).
    """
    col = f"foreign_{window}"
    valid_cols = ["foreign_1d", "foreign_3d", "foreign_5d", "foreign_10d", "foreign_20d"]
    if col not in valid_cols:
        return {"error": f"Invalid window '{window}'. Use: 1d, 3d, 5d, 10d, 20d"}

    rows = db_v2.query_sector_momentum(pillar=pillar, order_col=col, limit=top_n)
    return _stamp(
        {"sectors": rows, "window": window, "count": len(rows)},
        source="view_sector_momentum",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Ticker Momentum ──────────────────────────────────────────────────

@mcp.tool()
def sc_ticker_momentum(
    pillar: str | None = None,
    node: str | None = None,
    ticker_id: str | None = None,
    window: str = "5d",
    top_n: int = 15,
    min_streak: int = 0,
) -> dict:
    """Who is buying or selling a stock? — per-ticker institutional flow.

    When to use: the user asks who's behind a stock's move, or whether "big
    money" is buying. Shows multi-day net flows and the current consecutive
    foreign buy streak, for one ticker or across a pillar/node. Gloss: "flow" =
    net shares bought minus sold by institutions (foreign investors, investment
    trusts, dealers); a long buy streak signals sustained institutional demand.

    Args:
        pillar: Filter by AI pillar: 'semiconductor', 'equipment',
                'infrastructure', 'energy'.
        node: Filter by supply chain node: e.g. 'server-odm', 'thermal-cooling',
              'advanced-foundry', 'asic-custom-ip', etc.
        ticker_id: Look up a specific ticker (e.g. '2330' for TSMC).
        window: Sort by flow window: '1d', '3d', '5d', '10d', '20d'.
        top_n: Number of results (default 15).
        min_streak: Minimum consecutive foreign buy days to filter (default 0).
    """
    col = f"foreign_{window}"
    valid_cols = ["foreign_1d", "foreign_3d", "foreign_5d", "foreign_10d", "foreign_20d"]
    if col not in valid_cols:
        return {"error": f"Invalid window '{window}'. Use: 1d, 3d, 5d, 10d, 20d"}

    rows = db_v2.query_ticker_momentum(
        pillar=pillar, node=node, ticker_id=ticker_id,
        order_col=col, limit=top_n, min_streak=min_streak,
    )
    return _stamp(
        {"tickers": rows, "window": window, "count": len(rows)},
        source="view_ticker_momentum",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Supply Chain Map ─────────────────────────────────────────────────

@mcp.tool()
def sc_supply_chain_map(
    pillar: str | None = None,
    node: str | None = None,
    search: str | None = None,
) -> dict:
    """Look up the Taiwan AI supply chain classification for tickers.

    Returns which AI pillar, node, and US partners each company maps to.
    Use this to understand the strategic position of a ticker before
    analyzing its flow data.

    Args:
        pillar: Filter by pillar: 'semiconductor', 'equipment',
                'infrastructure', 'energy'.
        node: Filter by node: 'server-odm', 'thermal-cooling', etc.
        search: Search by ticker_id or company name (partial match).
    """
    rows = db_v2.query_supply_chain(pillar=pillar, node=node, search=search)
    return _stamp(
        {"companies": rows, "count": len(rows)},
        source="dim_supply_chain",
        as_of=_today_iso(),
        freshness="static",
    )


# ── Tool: Ticker Lookup ────────────────────────────────────────────────────

@mcp.tool()
def ticker_lookup(query: str, limit: int = 8) -> dict:
    """Find a stock's code from its name (or confirm a code).

    When to use: the user names a company ("台積電", "TSMC", "that server maker")
    or you're unsure of the code — resolve it to the canonical TWSE/TPEX ticker
    id BEFORE calling ticker-specific tools. Often the first call in a chain.

    Args:
        query: Ticker code or company name, e.g. '2330' or '台積電'.
        limit: Maximum matches to return.
    """
    rows = db_v2.query_ticker_lookup(query=query, limit=limit)
    return _stamp(
        {"matches": rows, "query": query, "count": len(rows)},
        source="dim_ticker",
        as_of=_today_iso(),
        freshness="static",
    )


# ── Tool: Flow History (time series) ───────────────────────────────────────

@mcp.tool()
def raw_flow_history(
    ticker_id: str,
    days: int = 20,
) -> dict:
    """Get daily institutional flow history for a specific ticker.

    Returns a time series of daily foreign/trust/dealer net flows.
    Useful for charting accumulation patterns and identifying entry points.

    Args:
        ticker_id: TWSE/TPEX ticker code (e.g. '2330', '3324').
        days: Number of trading days to return (default 20, max 90).
    """
    days = min(days, 90)
    rows = db_v2.query_flow_history(ticker_id=ticker_id, days=days)
    return _stamp(
        {"ticker_id": ticker_id, "history": rows, "count": len(rows)},
        source="raw_twse_t86",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Compare Nodes ───────────────────────────────────────────────────

@mcp.tool()
def sc_compare_nodes(
    nodes: list[str],
    window: str = "5d",
) -> dict:
    """Compare institutional flow between supply chain nodes.

    Side-by-side comparison of foreign capital flow across different parts
    of the AI supply chain. Useful for detecting "trickle down" rotation
    patterns (e.g., money flowing from foundry → server ODM → cooling).

    Args:
        nodes: List of node names to compare (e.g. ['server-odm',
               'thermal-cooling', 'advanced-foundry']).
        window: Flow window: '1d', '3d', '5d', '10d', '20d'.
    """
    col = f"foreign_{window}"
    total_col = f"total_{window}"
    valid_cols = ["foreign_1d", "foreign_3d", "foreign_5d", "foreign_10d", "foreign_20d"]
    if col not in valid_cols:
        return {"error": f"Invalid window '{window}'. Use: 1d, 3d, 5d, 10d, 20d"}

    results = db_v2.query_compare_nodes(nodes=nodes, foreign_col=col, total_col=total_col)
    return _stamp(
        {"comparison": results, "window": window, "nodes_requested": nodes},
        source="view_sector_momentum",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Accumulation Screener ────────────────────────────────────────────

@mcp.tool()
def sc_accumulation_screen(
    min_streak: int = 3,
    min_foreign_5d: int = 0,
    pillar: str | None = None,
    top_n: int = 20,
) -> dict:
    """Which AI-supply-chain names are foreigners steadily buying? (simple streak screen)

    When to use: a quick list within the curated AI universe, ranked by
    consecutive foreign buy days + flow volume. Which screener? For the *whole*
    market (incl. non-AI names) use `market_flow_screener`; for pre-move,
    still-cheap "sleepers" use `flow_leaders_scan`.

    Args:
        min_streak: Minimum consecutive days of foreign net buying (default 3).
        min_foreign_5d: Minimum 5-day foreign net flow (shares, default 0).
        pillar: Optional pillar filter.
        top_n: Max results (default 20).
    """
    rows = db_v2.query_ticker_momentum(
        pillar=pillar, order_col="consecutive_foreign_buy_days",
        limit=top_n, min_streak=min_streak,
    )
    # Filter by min_foreign_5d
    if min_foreign_5d > 0:
        rows = [r for r in rows if (r.get("foreign_5d") or 0) >= min_foreign_5d]

    return _stamp(
        {"accumulated_tickers": rows, "min_streak": min_streak, "count": len(rows)},
        source="view_ticker_momentum",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Full-Market Flow Screener ────────────────────────────────────────

@mcp.tool()
def market_flow_screener(
    market: str | None = None,
    classification: str = "all",
    search: str | None = None,
    min_streak: int = 0,
    foreign_1d_above: int | None = None,
    foreign_5d_above: int | None = None,
    foreign_20d_above: int | None = None,
    total_5d_above: int | None = None,
    sort_by: str = "foreign_5d",
    sort_direction: str = "desc",
    top_n: int = 50,
) -> dict:
    """Rank/filter the WHOLE Taiwan market by institutional flow momentum.

    When to use: "who is getting bought across the market", by net-flow size,
    including non-AI names (labelled `unclassified`). Unlike the `sc_*` supply-
    chain tools this searches every ticker in the TWSE/TPEX T86 feed. Which
    screener? For pre-move, still-cheap sleepers use `flow_leaders_scan`; for
    technical setups (RSI/MACD/near-highs) use `q_screener`.

    Args:
        market: Optional exchange filter: 'TWSE' or 'TPEX'.
        classification: 'all', 'classified', or 'unclassified'.
        search: Optional ticker/company-name substring.
        min_streak: Minimum consecutive foreign net-buy days.
        foreign_1d_above: Minimum latest-day foreign net flow in shares.
        foreign_5d_above: Minimum 5-day foreign net flow in shares.
        foreign_20d_above: Minimum 20-day foreign net flow in shares.
        total_5d_above: Minimum 5-day total institutional net flow in shares.
        sort_by: One of foreign_1d/3d/5d/10d/20d, total_1d/3d/5d/10d/20d,
            or consecutive_foreign_buy_days.
        sort_direction: 'desc' for accumulation leaders, 'asc' for selling.
        top_n: Max results, capped at 200.
    """
    rows = db_v2.query_market_flow_screener(
        market=market,
        classification=classification,
        search=search,
        min_streak=min_streak,
        foreign_1d_above=foreign_1d_above,
        foreign_5d_above=foreign_5d_above,
        foreign_20d_above=foreign_20d_above,
        total_5d_above=total_5d_above,
        sort_by=sort_by,
        sort_direction=sort_direction,
        limit=top_n,
    )
    return _stamp(
        {
            "matches": rows,
            "count": len(rows),
            "classification": classification,
            "market": market,
        },
        source="view_ticker_momentum",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Limit Board Scanner ─────────────────────────────────────────────

def _resolve_board_date(date: str | None) -> tuple[list[str], bool]:
    """Return (candidate dates newest-first, caller_pinned).

    A caller-supplied date is honoured exactly — a post-mortem of a specific
    session must not silently answer about a different one. With no date we
    walk back from today, because "today" is a holiday, a weekend, or a
    pre-close intraday moment more often than not.
    """
    if date:
        # Strict, because TPEX answers a malformed date with *today's* board
        # instead of an error — an unvalidated typo would silently return the
        # wrong session under the right label.
        try:
            parsed = datetime.strptime(date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise ValueError(f"date must be 'YYYY-MM-DD'; got {date!r}") from None
        if parsed > datetime.now(_TPE).date():
            raise ValueError(f"date {date} is in the future")
        return [parsed.isoformat()], True
    today = datetime.now(_TPE).date()
    days = [today - timedelta(days=i) for i in range(9)]
    # Skip weekends: each candidate costs a round trip per market, and the
    # exchange has never traded one. Holidays and typhoon closures still fall
    # through to an empty board, which the walk-back handles.
    return [d.isoformat() for d in days if d.weekday() < 5][:5], False


@mcp.tool()
def scan_limit_board(
    direction: str = "up",
    markets: list[str] | None = None,
    min_pct: float = 9.5,
    locked_only: bool = False,
    min_turnover_twd: int = 0,
    enrich: bool = True,
    date: str | None = None,
    limit: int = 200,
    mode: str = "eod",
) -> dict:
    """Scan the Taiwan limit-up / limit-down board (漲停/跌停) and triage it.

    Answers both halves of board triage: *who* is at the limit, and *which of
    them is a base-breakout vs. a chase*. The board is fetched live from TWSE
    and TPEX for the session in question, then joined to our own flow,
    valuation, ownership and margin history to produce `sleeper_flags` and a
    `triage` verdict per hit.

    Coverage is common stock only (4-digit codes). ETFs, ETNs and warrants are
    excluded: they carry different tick scales, and some foreign-tracking ETFs
    have no price limit at all.

    `min_pct` admits near-limit names, not only those that printed the limit —
    read `is_at_limit` to tell them apart. `is_locked` means the name closed at
    the limit with a one-sided book (漲停鎖住).

    Examples:
      - live-ish board, real liquidity: locked_only=true, min_turnover_twd=20000000
      - post-mortem of a past session: mode="eod", date="2026-07-16"
      - limit-down washout, TWSE only: direction="down", markets=["TWSE"], min_pct=9.0

    Args:
        direction: 'up', 'down', or 'both'.
        markets: Subset of ['TWSE','TPEX']. Default both.
        min_pct: Absolute % move required to be listed (default 9.5).
        locked_only: Keep only one-sided-book locks.
        min_turnover_twd: Liquidity floor on the session's turnover, in TWD.
        enrich: Join flow/valuation/ownership and compute triage. Set false
            for a fast, board-only answer.
        date: 'YYYY-MM-DD' session to scan. Defaults to the most recent
            session with published data.
        limit: Max hits returned (capped at 200).
        mode: 'eod' only. Realtime intraday scanning is not implemented —
            see the tool's docs for why.
    """
    if mode != "eod":
        return {
            "error": (
                "mode='realtime' is not implemented. This server runs as a "
                "stateless serverless function; a full-market MIS sweep needs "
                "~40-60 batched calls (~3-4 min) and lock_time needs "
                "cross-poll state, neither of which fits. Use mode='eod'."
            )
        }
    if direction not in ("up", "down", "both"):
        return {"error": "direction must be 'up', 'down', or 'both'"}

    wanted = [m.upper() for m in (markets or ["TWSE", "TPEX"])]
    bad = [m for m in wanted if m not in ("TWSE", "TPEX")]
    if bad:
        return {"error": f"markets must be 'TWSE' and/or 'TPEX'; got {bad}"}

    try:
        candidates, pinned = _resolve_board_date(date)
    except ValueError as exc:
        return {"error": str(exc)}

    errors: list[str] = []
    rows: list[dict] = []
    as_of: str | None = None
    per_market: dict[str, int] = {}

    for iso in candidates:
        compact = iso.replace("-", "")
        slashed = iso.replace("-", "/")
        attempt: list[dict] = []
        counts: dict[str, int] = {}
        fatal = False
        for market in wanted:
            if market == "TWSE":
                got, err = limit_board.fetch_twse_board(compact)
            else:
                got, err = limit_board.fetch_tpex_board(slashed)
            if err:
                errors.append(err)
                fatal = True
            counts[market] = len(got)
            attempt.extend(got)
        # An empty board means a non-trading day, not an error — unless a
        # fetch actually failed, in which case walking back would silently
        # answer about the wrong session.
        if attempt or fatal:
            rows, as_of, per_market = attempt, iso, counts
            break

    # A session where one exchange has a board and the other doesn't is not a
    # thing. If it happens, the quiet market failed in a way it declined to
    # report (TPEX never reports), and the answer covers half the market.
    # Say so rather than presenting it as the board.
    if rows and any(n == 0 for n in per_market.values()):
        silent = [m for m, n in per_market.items() if n == 0]
        live = [m for m, n in per_market.items() if n > 0]
        errors.append(
            f"partial coverage: {'/'.join(silent)} returned no rows for {as_of} "
            f"while {'/'.join(live)} returned data. Results cover {'/'.join(live)} only."
        )

    if not rows:
        if errors:
            return {"error": "; ".join(errors)}
        if pinned:
            return {
                "error": (
                    f"No board data published for {date}. Likely a weekend, "
                    "a holiday, a typhoon closure, or a session that has not "
                    "closed yet."
                )
            }
        return {"error": "No board data found in the last 7 days."}

    hits = limit_board.filter_board(
        rows,
        direction=direction,
        min_pct=min_pct,
        locked_only=locked_only,
        min_turnover_twd=min_turnover_twd,
    )
    truncated = len(hits) > limit
    hits = hits[: max(1, min(int(limit), 200))]

    if enrich and hits:
        try:
            ctx = db_v2.query_limit_board_enrichment(
                [h["ticker_id"] for h in hits], as_of
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"enrichment unavailable: {type(exc).__name__}: {exc}")
            ctx = {}
        hits = [limit_board.apply_triage(_merge(h, ctx.get(h["ticker_id"], {})))
                for h in hits]

    return _stamp(
        {
            "direction": direction,
            "mode": "eod",
            "markets": wanted,
            "count": len(hits),
            "at_limit_count": sum(1 for h in hits if h["is_at_limit"]),
            "locked_count": sum(1 for h in hits if h["is_locked"]),
            "universe_scanned": len(rows),
            "universe_by_market": per_market,
            "truncated": truncated,
            "hits": hits,
            "errors": errors,
        },
        source="twse_mi_index+tpex_daily_quotes",
        as_of=as_of,
        freshness="EOD",
    )


def _merge(hit: dict, ctx: dict) -> dict:
    """Fold an enrichment row into a board hit.

    Board fields win on conflict: `name`/`market` come from the exchange feed
    for the session actually scanned, which is authoritative over dim_ticker.
    """
    if not ctx:
        return hit
    margin_balance = ctx.get("margin_balance")
    margin_limit = ctx.get("margin_limit")
    margin_pct = None
    if margin_balance is not None and margin_limit:
        margin_pct = round(margin_balance / margin_limit * 100, 2)

    merged = {
        **hit,
        "industry": ctx.get("industry"),
        "ai_pillar": ctx.get("ai_pillar"),
        "node": ctx.get("node"),
        "pe_ratio": ctx.get("pe_ratio"),
        "pb_ratio": ctx.get("pb_ratio"),
        "dividend_yield": ctx.get("dividend_yield"),
        "foreign_net_5d": ctx.get("foreign_net_5d"),
        "trust_net_5d": ctx.get("trust_net_5d"),
        "dealer_net_5d": ctx.get("dealer_net_5d"),
        "foreign_net_z20": ctx.get("foreign_net_z20"),
        "flow_days": ctx.get("flow_days"),
        "foreign_held_pct": ctx.get("foreign_held_pct"),
        "foreign_room_pct": ctx.get("foreign_room_pct"),
        "margin_pct_of_limit": margin_pct,
        "short_balance": ctx.get("short_balance"),
        "rsi_14": ctx.get("rsi_14"),
        "sma_50": ctx.get("sma_50"),
        "sma_200": ctx.get("sma_200"),
        "rs_vs_market_60": ctx.get("rs_vs_market_60"),
        "pct_below_52w_high": ctx.get("pct_below_52w_high"),
        "signals_as_of": ctx.get("signals_as_of"),
        "revenue_yoy_pct": ctx.get("revenue_yoy_pct"),
        "revenue_mom_pct": ctx.get("revenue_mom_pct"),
        "revenue_ym": ctx.get("revenue_ym"),
        "_valuation_known": ctx.get("valuation_known", False),
    }
    if ctx.get("company_name"):
        merged["name"] = hit.get("name") or ctx["company_name"]
    return merged


# ── Tool: Flow-Leaders Scanner (generative sleeper screen) ─────────────────

_FLOW_SORT_KEYS = {
    "sleeper_score", "foreign_net_sum", "buy_day_ratio",
    "price_move_pct", "foreign_net_z20",
}


@mcp.tool()
def momentum_leaders_scan(
    rs_window: int = 60,
    min_rs_percentile: float = 80.0,
    require_inst_confirm: bool = True,
    max_extension_pct: float = 40.0,
    min_base_days: int = 5,
    min_turnover_twd: int = 30_000_000,
    markets: list[str] | None = None,
    mode: str = "entry",
    date: str | None = None,
    limit: int = 40,
) -> dict:
    """Which stocks are in a strong trend EARLY — and which held ones have broken?

    When to use: the user wants growth/momentum ideas, asks "what's working", or
    holds a momentum name and needs to know whether to still be in it. This is
    NOT a "what's up a lot today" scanner — that finds blow-off tops, and the
    guards below exist specifically to reject them.

    Each candidate gets a `momentum_score` (0-100), a `triage`
    (momentum-entry / watch / chase), and — for any entry — a concrete
    `trailing_stop`. Gloss: momentum only pays if you enter trends early,
    institutions are buying with you, and you exit on a mechanical stop. A name
    already far above its 50-day average is `chase`, not `entry`, however strong
    it looks.

    Which screener? This one = strong-and-early trends. Cheap, quietly-bought,
    not-yet-moved → `flow_leaders_scan` (the value/sleeper sibling — opposite
    logic, don't mix the two books). Today's limit-up extremes →
    `scan_limit_board`. Technical setups → `q_screener`.

    `mode="monitor"` re-computes the stop for names the user already holds and
    reports `stop_hit` — that is the exit signal, and it carries no discretion.
    Pass the held tickers via `markets`-filtered results or read the watchlist
    first; a name whose stop is hit is closed, never reclassified as a "sleeper"
    to justify holding it.

    Scoreable universe is NARROWER than the sleeper scan's. ATR, the breakout
    test and the climax guard need high/low/volume, which only the OHLCV harvest
    carries (~top 500 names), and 200 sessions of history are required for the
    200-day mean. Small caps outside that set are not scored at all rather than
    scored badly — `universe_scanned` reports how many were measurable.

    Examples:
      - today's early trends: momentum_leaders_scan()
      - check held names' stops: momentum_leaders_scan(mode="monitor")
      - looser parabola guard: max_extension_pct=55

    Args:
        rs_window: Relative-strength and flow lookback in sessions (default 60).
        min_rs_percentile: Percentile vs the measurable market required for an
            entry (default 80).
        require_inst_confirm: Require foreign and/or trust net-buying with the
            trend (default true). This is the retail-pump filter — turning it
            off makes the tool a meme chaser.
        max_extension_pct: Reject as `parabolic` above this % over the 50-day
            mean (default 40). The single most important guard.
        min_base_days: Sessions of consolidation required before the current
            leg; fewer trips `no_base` (default 5).
        min_turnover_twd: Liquidity floor (default 30M).
        markets: Subset of ['TWSE','TPEX']. Default both.
        mode: 'entry' for fresh setups, 'monitor' for held names' stops.
        date: 'YYYY-MM-DD' as-of for a historical scan or post-mortem.
        limit: Max candidates returned (capped at 200).
    """
    wanted = [m.upper() for m in (markets or ["TWSE", "TPEX"])]
    bad = [m for m in wanted if m not in ("TWSE", "TPEX")]
    if bad:
        return {"error": f"markets must be 'TWSE' and/or 'TPEX'; got {bad}"}
    if mode not in ("entry", "monitor"):
        return {"error": f"mode must be 'entry' or 'monitor'; got {mode!r}"}
    if not 5 <= int(rs_window) <= 250:
        return {"error": f"rs_window must be 5-250 sessions; got {rs_window}"}

    if date:
        try:
            parsed = datetime.strptime(date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return {"error": f"date must be 'YYYY-MM-DD'; got {date!r}"}
        if parsed > datetime.now(_TPE).date():
            return {"error": f"date {date} is in the future"}
        as_of = parsed.isoformat()
    else:
        as_of = db_v2.latest_flow_date()
        if not as_of:
            return {"error": "no institutional-flow data has been harvested yet"}

    try:
        rows = db_v2.query_momentum_leaders(
            as_of, rs_window=int(rs_window), markets=wanted,
            min_turnover_twd=int(min_turnover_twd))
    except Exception as exc:  # noqa: BLE001 — surfaced, not swallowed
        return {"error": f"momentum query failed: {type(exc).__name__}: {exc}"}

    if mode == "monitor":
        watched = {w.get("ticker_id") for w in db_v2.query_watchlist(status="active")}
        held = [r for r in rows if r.get("ticker_id") in watched]
        checked = [momentum_leaders.monitor_row(r) for r in held]
        checked.sort(key=lambda c: (not c["stop_hit"], c["ticker_id"] or ""))
        return _stamp(
            {
                "as_of": as_of, "mode": "monitor",
                "universe_scanned": len(rows),
                "count": len(checked),
                "stops_hit": sum(1 for c in checked if c["stop_hit"]),
                "note": "A hit stop is an exit, not a re-evaluation. Momentum "
                        "positions are not reclassified as value holds.",
                "positions": checked,
            },
            source="raw_twse_ohlcv+raw_twse_t86+watchlist",
            as_of=as_of, freshness="EOD",
        )

    scored = [
        momentum_leaders.score_row(
            r,
            min_rs_percentile=min_rs_percentile,
            require_inst_confirm=require_inst_confirm,
            max_extension_pct=max_extension_pct,
            min_base_days=int(min_base_days),
        )
        for r in rows
    ]
    scored.sort(key=lambda c: -(c.get("momentum_score") or 0))
    truncated = len(scored) > limit
    candidates = scored[: max(1, min(int(limit), 200))]

    counts: dict[str, int] = {}
    for c in candidates:
        counts[c["triage"]] = counts.get(c["triage"], 0) + 1

    return _stamp(
        {
            "as_of": as_of,
            "mode": "entry",
            "price_as_of": as_of,
            # Same rule as the sleeper scan: EOD prices, so any level must be
            # re-quoted before acting if the as-of is not today.
            "stale_price_warning": as_of != datetime.now(_TPE).date().isoformat(),
            "rs_window": int(rs_window),
            "markets": wanted,
            "universe_scanned": len(rows),
            "universe_note": "Names with >=200 sessions of OHLCV history. ATR, "
                             "the breakout test and the climax guard need "
                             "high/low/volume, which only the OHLCV harvest "
                             "carries — so this is narrower than the sleeper "
                             "scan's priced universe.",
            "count": len(candidates),
            "triage_counts": counts,
            "truncated": truncated,
            "candidates": candidates,
        },
        source="raw_twse_ohlcv+raw_twse_t86+raw_twse_index+raw_twse_valuation",
        as_of=as_of,
        freshness="EOD",
        glossary=_GLOSS_MOMENTUM,
    )


@mcp.tool()
def flow_leaders_scan(
    window_days: int = 20,
    min_buy_day_ratio: float = 0.65,
    max_price_move_pct: float = 8.0,
    max_pe: float = 20.0,
    max_foreign_held: float = 25.0,
    min_turnover_twd: int = 10_000_000,
    markets: list[str] | None = None,
    include_loss: bool = False,
    min_foreign_z: float | None = None,
    sort_by: str = "sleeper_score",
    date: str | None = None,
    limit: int = 50,
) -> dict:
    """Which stocks are institutions quietly accumulating before a move?

    When to use: the user asks for ideas / "what looks interesting" / where smart
    money is building a position early. Screens the whole market for the pattern
    that *precedes* a move — sustained institutional net buying (a high buy-day
    ratio over the window) into a price that has not yet run, in a name that is
    still cheap (low P/E) and under-owned by foreigners. Each hit gets a
    `sleeper_score` (0-100), `sleeper_flags`, and a `triage` verdict
    (sleeper / watch / chase). Gloss: a "sleeper" is a quietly-bought, not-yet-
    moved name — higher risk than a proven leader; say so when you present one.

    Which screener? This one = pre-move, still-cheap sleepers. Whole-market flow
    ranking → `market_flow_screener`; simple foreign buy-streak in the AI names →
    `sc_accumulation_screen`; technical setups → `q_screener`; statistical alpha
    → `q_factor_screen`.

    Scoreable universe = names with both institutional-flow history (T86,
    all-market) and a harvested price (TWSE BWIBBU close + the OHLCV top-500).
    Most TPEX names have no price row and cannot be measured for flatness, so
    they are not returned; TWSE coverage is ~1.1k names.

    Flatness is median-anchored (latest vs the window-median close), which is
    immune to the occasional corrupt exchange print. Note `min_foreign_z` is
    OFF by default and should stay off for finding multi-week accumulators: a
    slow grind has no closing-day z-spike (see the tool's module docstring).

    Examples:
      - default sleeper board: flow_leaders_scan()
      - post-mortem / backtest a past day: date="2026-06-30"
      - TWSE only, looser flatness: markets=["TWSE"], max_price_move_pct=12

    Args:
        window_days: Flow/price lookback in trading sessions (2-60, default 20).
        min_buy_day_ratio: Fraction of window sessions with foreign net buying
            required for the `accumulating` flag / sleeper verdict (default 0.65).
        max_price_move_pct: |latest vs median| under which a name counts as
            'flat' / not-yet-run (default 8.0).
        max_pe: PE ceiling for full valuation credit (default 20.0).
        max_foreign_held: Foreign-held % ceiling for under-owned credit (25.0).
        min_turnover_twd: Liquidity floor (default 10M). Applied only where
            turnover is known — a name with no OHLCV row is never dropped for it.
        markets: Subset of ['TWSE','TPEX']. Default both (TPEX largely unpriced).
        include_loss: Keep names with no positive earnings (PE null). Default
            false — they are chases, not sleepers.
        min_foreign_z: Optional hard floor on the single-day 20d z-score. Leave
            null (default) to find grinders; a positive value finds fresh spikes.
        sort_by: One of sleeper_score / foreign_net_sum / buy_day_ratio /
            price_move_pct / foreign_net_z20 (default sleeper_score).
        date: 'YYYY-MM-DD' as-of for a historical scan. Defaults to the latest
            harvested session.
        limit: Max hits returned (capped at 200).
    """
    wanted = [m.upper() for m in (markets or ["TWSE", "TPEX"])]
    bad = [m for m in wanted if m not in ("TWSE", "TPEX")]
    if bad:
        return {"error": f"markets must be 'TWSE' and/or 'TPEX'; got {bad}"}
    if sort_by not in _FLOW_SORT_KEYS:
        return {"error": f"sort_by must be one of {sorted(_FLOW_SORT_KEYS)}"}

    if date:
        try:
            parsed = datetime.strptime(date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return {"error": f"date must be 'YYYY-MM-DD'; got {date!r}"}
        if parsed > datetime.now(_TPE).date():
            return {"error": f"date {date} is in the future"}
        as_of = parsed.isoformat()
    else:
        as_of = db_v2.latest_flow_date()
        if not as_of:
            return {"error": "no institutional-flow data has been harvested yet"}

    try:
        rows = db_v2.query_flow_leaders(as_of, window_days=window_days, markets=wanted)
    except Exception as exc:  # noqa: BLE001 — surfaced, not swallowed
        return {"error": f"flow-leaders query failed: {type(exc).__name__}: {exc}"}

    scored = [
        flow_leaders.score_row(
            r,
            window_days=window_days,
            max_price_move_pct=max_price_move_pct,
            max_pe=max_pe,
            max_foreign_held=max_foreign_held,
            min_buy_day_ratio=min_buy_day_ratio,
            as_of=as_of,
        )
        for r in rows
    ]

    def keep(h: dict) -> bool:
        # Liquidity floor: only excludes a name whose turnover is known-and-below
        # (cross-cutting rule — never silently drop a name for an enrichment miss).
        turn = h.get("turnover_twd")
        if min_turnover_twd and turn is not None and turn < min_turnover_twd:
            return False
        # No-earnings names are chases; drop unless explicitly included.
        if not include_loss and h.get("pe_ratio") is None and h.get("valuation_known"):
            return False
        if min_foreign_z is not None:
            z = h.get("foreign_net_z20")
            if z is None or z < min_foreign_z:
                return False
        return True

    hits = [h for h in scored if keep(h)]
    hits.sort(key=lambda h: (h.get(sort_by) is None, -(h.get(sort_by) or 0)))
    truncated = len(hits) > limit
    hits = hits[: max(1, min(int(limit), 200))]

    counts = {"sleeper": 0, "watch": 0, "chase": 0}
    for h in hits:
        counts[h["triage"]] = counts.get(h["triage"], 0) + 1

    # Scan prices are EOD; if the as-of is not today the caller must re-quote
    # before acting on any level (Tool Review v2 #6 — 晶華 close 179 in a scan
    # while the live quote was 192).
    stale_price = as_of != datetime.now(_TPE).date().isoformat()

    return _stamp(
        {
            "as_of": as_of,
            "price_as_of": as_of,
            "stale_price_warning": stale_price,
            "window_days": window_days,
            "markets": wanted,
            "sort_by": sort_by,
            "universe_scanned": len(scored),
            "count": len(hits),
            "triage_counts": counts,
            "truncated": truncated,
            "hits": hits,
            "errors": [],
        },
        source="raw_twse_t86+raw_twse_valuation+raw_twse_holdings+raw_twse_dividend+raw_finmind_*",
        as_of=as_of,
        freshness="EOD",
    )


# ── Tool: Session State (Taipei market phase + trading calendar) ───────────

@mcp.tool()
def session_state(date: str | None = None) -> dict:
    """Report the Taipei market phase and whether the market is open.

    Call this before quoting a price, or whenever the question is "is this
    price real, or pre-open noise?". During 08:30–09:00 the market runs a 試撮
    (pre-open simulated auction): the displayed price is *indicative* and can
    swing violently on a thin book — `price_is_indicative` is true and a
    `warning` is set. Regular continuous trading is 09:00–13:30.

    `is_trading_day` combines the weekend check with the TWSE holiday calendar
    (`market_holidays`, refreshed nightly, plus any manual typhoon inserts). If
    the calendar can't be read, it degrades to a weekend-only answer and says so
    via `calendar_source: "weekend_only"`.

    Args:
        date: 'YYYY-MM-DD' to ask about a specific day's trading status. Omit
            for the live 'now' (the only case where `phase` is a live phase; for
            another day only the calendar status is meaningful).
    """
    now = datetime.now(_TPE)
    today_iso = now.date().isoformat()

    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return {"error": f"date must be 'YYYY-MM-DD'; got {date!r}"}
        target_iso = target.isoformat()
    else:
        target = now.date()
        target_iso = today_iso

    is_weekend = target.weekday() >= 5
    calendar_source = "calendar"
    closure = None
    if is_weekend:
        is_trading_day = False
    else:
        try:
            closure = db_v2.market_closure(target_iso)
            is_trading_day = closure is None
        except Exception:  # noqa: BLE001 — degrade, don't fail the whole call
            calendar_source = "weekend_only"
            is_trading_day = True   # best effort: a weekday we can't disprove

    if target_iso == today_iso:
        state = session_state_mod.build_state(now, is_trading_day, calendar_source)
    else:
        # Not the live day — phase is not a live phase; report calendar status.
        state = {
            "taipei_time": now.isoformat(),
            "date": target_iso,
            "weekday": target.strftime("%A"),
            "is_trading_day": is_trading_day,
            "phase": "closed" if not is_trading_day else "not_live",
            "price_is_indicative": False,
            "phases_today": session_state_mod.PHASES_TODAY,
            "calendar_source": calendar_source,
            "warning": None,
            "note": "phase is only a live phase for today; this is the calendar status for another day",
        }

    if closure:
        state["closed_reason"] = closure.get("name")
        state["closed_source"] = closure.get("source")

    return _stamp(state, source="market_holidays+clock",
                  as_of=today_iso, freshness="real_time")


# ── Tool: Realtime Quote (watchlist, TWSE MIS) ─────────────────────────────

def _current_phase() -> tuple[str, bool]:
    """(phase, price_is_indicative) for the live Taipei moment, calendar-aware.
    Falls back to a weekend check if the calendar can't be read."""
    now = datetime.now(_TPE)
    if now.weekday() >= 5:
        is_trading = False
    else:
        try:
            is_trading = db_v2.market_closure(now.date().isoformat()) is None
        except Exception:  # noqa: BLE001
            is_trading = True
    phase, indicative, _ = session_state_mod.phase_for(now, is_trading)
    return phase, indicative


def _quote_via_mis(codes: list[str]) -> tuple[list[dict], list[str]]:
    """MIS path: resolve tse_/otc_ prefixes and batch-fetch."""
    try:
        markets = db_v2.ticker_markets(codes)
    except Exception:  # noqa: BLE001 — market lookup is best-effort
        markets = {}
    ex_ch: list[str] = []
    for c in codes:
        mk = markets.get(c)
        if mk == "TWSE":
            ex_ch.append(f"tse_{c}.tw")
        elif mk == "TPEX":
            ex_ch.append(f"otc_{c}.tw")
        else:  # unknown → probe both; MIS returns only the one that exists
            ex_ch.extend([f"tse_{c}.tw", f"otc_{c}.tw"])
    raw, err = quote_mod.fetch_quotes(ex_ch)
    # MIS returns an empty-code row for an unknown symbol — drop those.
    quotes = [q for q in (quote_mod.parse_msg(m) for m in raw) if q["ticker_id"]]
    return quotes, ([err] if err else [])


def _quote_via_fugle(codes: list[str], key: str) -> tuple[list[dict], list[str]]:
    """Fugle path: one call per symbol, limit prices computed from reference."""
    raw, errors = fugle_mod.fetch_quotes(codes, key)
    quotes = [q for q in (fugle_mod.parse_quote(j) for j in raw) if q["ticker_id"]]
    return quotes, errors


@mcp.tool()
def quote(symbols: list[str], source: str = "auto") -> dict:
    """Current price(s) for one or a few named Taiwan tickers — near-realtime.

    When to use: the user asks "what's the price of X" for specific stocks they
    name. NOT a scanner — for "which stocks are…" breadth use flow_leaders_scan
    / scan_limit_board. Returns last/prev/open/high/low, best bid/ask, and the
    authoritative **limit-up / limit-down** prices (the daily ±10% caps a Taiwan
    stock cannot trade past) per symbol.

    Two sources: **Fugle** (keyed realtime feed, preferred — richer book, lower
    latency) and **TWSE MIS** (no key, but throttled). `source="auto"` uses
    Fugle when FUGLE_API_KEY is configured and falls back to MIS otherwise (or
    if Fugle returns nothing). `response._quote_source` says which answered.

    The response carries the live session `phase` and `price_is_indicative`: in
    the 08:30–09:00 pre-open auction the price is a 試撮 simulation, not a trade.
    A symbol that has not printed yet returns `last_price: null`, never a
    fabricated price. Ask 'is this real?' via session_state if in doubt.

    Args:
        symbols: Ticker codes, e.g. ['2330','4536','6488'].
        source: 'auto' (default) | 'fugle' | 'mis'.
    """
    codes = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    if not codes:
        return {"error": "symbols is required (e.g. ['2330','4536'])"}
    src = (source or "auto").lower()
    if src not in ("auto", "fugle", "mis"):
        return {"error": "source must be 'auto', 'fugle', or 'mis'"}

    key = fugle_mod.api_key()
    if src == "fugle" and not key:
        return {"error": "source='fugle' needs FUGLE_API_KEY to be configured"}

    use_fugle = key is not None if src == "auto" else src == "fugle"
    cap = fugle_mod._MAX_SYMBOLS if use_fugle else quote_mod._MAX_SYMBOLS
    if len(codes) > cap:
        return {"error": f"at most {cap} symbols per call for source '{'fugle' if use_fugle else 'mis'}'; got {len(codes)}"}

    if use_fugle:
        quotes, errors = _quote_via_fugle(codes, key)
        used = "fugle"
        # Auto-fallback: if Fugle produced nothing, try MIS rather than return empty.
        if src == "auto" and not quotes:
            mis_quotes, mis_errors = _quote_via_mis(codes)
            if mis_quotes:
                quotes, errors, used = mis_quotes, errors + mis_errors, "twse_mis"
    else:
        quotes, errors = _quote_via_mis(codes)
        used = "twse_mis"

    found = {q["ticker_id"] for q in quotes}
    missing = [c for c in codes if c not in found]

    phase, indicative = _current_phase()
    return _stamp(
        {
            "_quote_source": used,
            "phase": phase,
            "price_is_indicative": indicative,
            "warning": (session_state_mod._INDICATIVE_WARNING if indicative else None),
            "count": len(quotes),
            "quotes": quotes,
            "missing": missing,
            "errors": errors,
        },
        source=used,
        as_of=(quotes[0].get("quote_time") if quotes else None),
        freshness="realtime" if phase == "regular" else "delayed_or_closed",
    )


# ── Tool: Dividend Calendar (does a buyer today get the dividend?) ─────────

@mcp.tool()
def dividend_calendar(ticker_id: str, date: str | None = None) -> dict:
    """Does a buyer today still receive the dividend? — for a TWSE stock.

    When to use: the user asks about a stock's dividend, yield, or "if I buy now
    do I get the payout". Gloss: the *ex-dividend date* is the cutoff — buy on or
    after it and you do NOT get that distribution, so a headline yield can already
    be gone. Returns the most-recent-past and next-upcoming ex-dividend/ex-rights
    event relative to `date`, from the TWSE 除權除息 calendar.

    `most_recent.already_ex` is true once the stock has gone ex — its dividend
    is not available to a new buyer. `upcoming` (if any) is a future ex date; a
    buyer before it would receive that one (`buyer_today_receives_upcoming`).
    `ex_type` is 息 (cash), 權 (stock rights), or 權息 (both); `cash_dividend`
    is 元/股 (combined value for 權息).

    Coverage is TWSE-listed names (the 除權除息 tables). Values are official
    TWSE data — no forward estimate is ever synthesised here.

    Args:
        ticker_id: TWSE stock code, e.g. '2357'.
        date: 'YYYY-MM-DD' as-of. Defaults to today (Asia/Taipei).
    """
    tid = str(ticker_id).strip()
    if not tid:
        return {"error": "ticker_id is required"}
    if date:
        try:
            as_of = datetime.strptime(date, "%Y-%m-%d").date().isoformat()
        except (TypeError, ValueError):
            return {"error": f"date must be 'YYYY-MM-DD'; got {date!r}"}
    else:
        as_of = _today_iso()

    try:
        data = db_v2.query_dividend(tid, as_of)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"dividend query failed: {type(exc).__name__}: {exc}"}

    recent = data["most_recent"]
    upcoming = data["upcoming"]

    def shape(row: dict | None) -> dict | None:
        if not row:
            return None
        return {
            "ex_dividend_date": row["ex_date"],
            "ex_type": row.get("ex_type"),
            "cash_dividend": row.get("cash_value"),
            "pre_ex_close": row.get("pre_ex_close"),
            "reference_price": row.get("reference_price"),
            "record_status": row.get("status"),   # 'actual' | 'forecast'
        }

    recent_shaped = shape(recent)
    if recent_shaped is not None:
        recent_shaped["already_ex"] = recent["ex_date"] <= as_of  # always true here

    return _stamp(
        {
            "ticker_id": tid,
            "as_of": as_of,
            "most_recent": recent_shaped,
            "upcoming": shape(upcoming),
            "buyer_today_receives_upcoming": bool(upcoming and as_of < upcoming["ex_date"]),
            "note": (
                None if recent_shaped or upcoming
                else "No ex-dividend record found (TWSE-listed only; may not distribute)."
            ),
        },
        source="twse_twt49u+twt48u",
        as_of=as_of,
        freshness="EOD",
    )


# ── Tool: Quant Indicators (per ticker) ────────────────────────────────────

@mcp.tool()
def q_indicators(ticker_id: str) -> dict:
    """Latest technical indicator stack for one ticker.

    Returns RSI-14, MACD (line/signal/histogram), Bollinger %B, ATR-14,
    SMA-50, SMA-200, and 60-day relative strength vs the broad market
    (Yuanta Taiwan 50 / 0050).

    Indicators are recomputed daily from OHLCV data after market close.
    Read this before forming an opinion on a ticker — it tells you where
    momentum, volatility, and trend stand right now.

    Args:
        ticker_id: TWSE/TPEX code, e.g. '2330' for TSMC.
    """
    payload = db_v2.query_indicators(ticker_id)
    return _stamp(
        payload,
        source="view_latest_signals",
        as_of=str(payload.get("as_of") or _today_iso()),
        freshness="T+1",
    )


# ── Tool: Beginner Stock Card ─────────────────────────────────────────────

@mcp.tool()
def beginner_stock_card(ticker_id: str) -> dict:
    """A plain overview of one stock — the best first tool for a beginner.

    When to use: the user names a stock (or wants "the basics" on one) and you
    want a single grounded snapshot before going deeper. Groups price, recent
    trend, who's buying (institutional flow), valuation, and a short close
    series into simple sections. Factual only — no buy/sell/quality verdict; you
    supply the plain-language explanation around it.

    Key fields: `price`, `trend`, `flow` (foreign/trust/dealer net buying),
    `valuation` (P/E = price per $1 of yearly earnings; P/B = price per $1 of
    net assets), `dividend`, and a close series for a simple chart. Data is T+1.

    Args:
        ticker_id: TWSE/TPEX code, e.g. '2330' for TSMC.
    """
    payload = db_v2.query_beginner_stock_card(ticker_id)
    return _stamp(
        payload,
        source="beginner_stock_card",
        as_of=str(payload.get("as_of") or _today_iso()),
        freshness="T+1",
        glossary=_GLOSS_STOCK_CARD,
    )


@mcp.tool()
def price_history(ticker_id: str, days: int = 90) -> dict:
    """Recent daily prices for one stock — chart-ready history.

    When to use: the user asks how a stock has moved lately ("show me the last
    3 months", "has it been going up?"). Returns oldest-first daily OHLCV rows
    for a simple line or candle chart; data only — the client renders the chart.
    Gloss: OHLCV = each day's open, high, low, close and volume.

    Args:
        ticker_id: TWSE/TPEX code, e.g. '2330'.
        days: Number of trading days to return, capped at 365.
    """
    days = min(max(int(days), 1), 365)
    rows = db_v2.query_price_history(ticker_id=ticker_id, days=days)
    return _stamp(
        {"ticker_id": ticker_id, "days": days, "prices": rows, "count": len(rows)},
        source="raw_twse_ohlcv",
        as_of=rows[-1]["date"] if rows else _today_iso(),
        freshness="T+1",
    )


# ── Tool: Quant Screener ───────────────────────────────────────────────────

@mcp.tool()
def q_screener(
    rsi_below: float | None = None,
    rsi_above: float | None = None,
    macd_hist_above: float | None = None,
    above_sma_200: bool | None = None,
    rs_above: float | None = None,
    rs_below: float | None = None,
    foreign_z_above: float | None = None,
    foreign_z_below: float | None = None,
    pct_below_52w_high_above: float | None = None,
    pct_below_52w_high_below: float | None = None,
    universe: str = "classified",
) -> dict:
    """Filter tickers by TECHNICAL / indicator setup (AND-combined).

    When to use: the user wants a technical pattern — oversold, momentum,
    near-highs. Which screener? For raw institutional-flow ranking use
    `market_flow_screener` or `flow_leaders_scan`; for statistical alpha use
    `q_factor_screen`. Combines technical + flow signals. Examples:
      - oversold-in-uptrend: rsi_below=40, above_sma_200=true, macd_hist_above=0
      - foreign-buying surge: foreign_z_above=1.5
      - near-highs momentum: pct_below_52w_high_above=-3, rs_above=1.0
      - beaten-down relative weakness: rs_below=-5, pct_below_52w_high_below=-20

    Args:
        rsi_below: RSI-14 below this value.
        rsi_above: RSI-14 above this value.
        macd_hist_above: MACD histogram above this value.
        above_sma_200: True = price above 200-day MA; False = below.
        rs_above: 60d relative strength vs market threshold (1.0 = neutral).
        rs_below: 60d relative strength below this threshold.
        foreign_z_above: 20-day z-score of daily foreign net flow.
        foreign_z_below: 20-day z-score below this threshold.
        pct_below_52w_high_above: Filter to tickers within X% of 52w high
            (pass -3 to mean "within 3% of the high"; pass -10 for "within 10%").
        pct_below_52w_high_below: Filter to tickers farther below their 52w high
            than X% (pass -20 to mean "more than 20% below the high").
        universe: 'classified' (default) or 'all_with_signals'. Full-market
            flow-only screening is provided by `market_flow_screener`.
    """
    rows = db_v2.query_screener(
        rsi_below=rsi_below, rsi_above=rsi_above,
        macd_hist_above=macd_hist_above,
        above_sma_200=above_sma_200, rs_above=rs_above,
        rs_below=rs_below,
        foreign_z_above=foreign_z_above, foreign_z_below=foreign_z_below,
        pct_below_52w_high_above=pct_below_52w_high_above,
        pct_below_52w_high_below=pct_below_52w_high_below,
        universe=universe,
    )
    return _stamp(
        {"matches": rows, "count": len(rows), "universe": universe},
        source="view_latest_signals",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Quant Backtest ──────────────────────────────────────────────────

@mcp.tool()
def q_backtest(
    signal_name: str,
    threshold: float,
    direction: str = "below",
    forward_days: int = 5,
    lookback_days: int = 365,
) -> dict:
    """Backtest a single-threshold signal rule on the classified universe.

    Returns hit-rate (% of triggers that produced positive returns N days
    later), average / median / best / worst return, and per-ticker sample
    counts. If n_observations < 30, a sample_warning is included — treat
    such results as illustrative, not predictive.

    Use this BEFORE acting on any signal idea to know whether the rule
    has historically had positive expectancy on this universe.

    Args:
        signal_name: One of rsi_14, macd_line, macd_signal_line,
                     macd_histogram, bb_pct_b, atr_14, sma_50, sma_200,
                     rs_vs_market_60.
        threshold: The numeric threshold to compare against.
        direction: 'below' (signal < threshold) or 'above' (signal > threshold).
        forward_days: Trading days to measure forward return (default 5).
        lookback_days: Calendar days of history to scan (default 365).

    Examples:
        q_backtest('rsi_14', 30, 'below', 5)   — oversold mean reversion
        q_backtest('rsi_14', 70, 'above', 5)   — overbought continuation
        q_backtest('macd_histogram', 0, 'above', 5)  — bullish momentum
    """
    payload = db_v2.query_backtest(
        signal_name, threshold, direction, forward_days, lookback_days,
    )
    if "error" in payload:
        return payload
    return _stamp(
        payload,
        source="signal_value + raw_twse_ohlcv",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Compound Backtest ───────────────────────────────────────────────

@mcp.tool()
def q_backtest_compound(
    conditions: list[dict],
    forward_days: int = 5,
    lookback_days: int = 365,
) -> dict:
    """Backtest a multi-condition AND rule. Up to 4 conditions.

    Each condition is {'signal': str, 'op': '<' | '>', 'threshold': float}.
    All must hold on the same (ticker, date) to count as a trigger.

    Use this to test combined hypotheses that single signals miss. For
    example: naive RSI < 30 has weak edge in a strong uptrend, but
    "RSI < 40 AND MACD histogram > 0" (oversold dip within an uptrend)
    historically has stronger expectancy.

    Args:
        conditions: list of {'signal','op','threshold'} dicts.
        forward_days: trading days to measure forward return (default 5).
        lookback_days: history to scan (default 365).

    Example:
        q_backtest_compound(
          [{"signal":"rsi_14","op":"<","threshold":40},
           {"signal":"macd_histogram","op":">","threshold":0}],
          forward_days=5)
    """
    payload = db_v2.query_backtest_compound(conditions, forward_days, lookback_days)
    if "error" in payload:
        return payload
    return _stamp(
        payload,
        source="signal_value + raw_twse_ohlcv",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: News Recent ─────────────────────────────────────────────────────

@mcp.tool()
def n_recent(
    days: int = 1,
    source: str | None = None,
    lang: str | None = None,
    limit: int = 50,
) -> dict:
    """Recent news articles harvested into raw_news.

    Articles come from RSS feeds (DigiTimes Asia, Nikkei Asia, Bloomberg
    Tech/Markets, Federal Reserve, ECB) and Google News query feeds
    (per-pillar, per-theme, both English and Traditional Chinese for
    Taiwan-domestic coverage).

    Phase 2a: titles + summaries only, no sentiment scores yet.

    Args:
        days: Lookback window in days (default 1 = last 24h).
        source: Filter to one feed key, e.g. 'digitimes', 'gnews-tw-ai-zh'.
                Use n_source_status() to list available source keys.
        lang: Filter to 'en' or 'zh-Hant'.
        limit: Max articles to return (default 50, capped at 200).
    """
    rows = db_v2.query_news_recent(days=days, source=source, lang=lang, limit=limit)
    return _stamp(
        {"articles": rows, "count": len(rows), "days_window": days},
        source="raw_news",
        as_of=_today_iso(),
        freshness="hourly",
    )


# ── Tool: News for Ticker ─────────────────────────────────────────────────

@mcp.tool()
def n_for_ticker(
    ticker_id: str,
    days: int = 14,
    limit: int = 30,
) -> dict:
    """Recent news about a specific company.

    When to use: the user asks "any news on X" or what's happening with a stock.
    Returns recent articles mentioning the ticker (matched by code as a
    standalone token in the title, or the company name in title/summary until
    structured entity extraction lands). Treat these as headlines to summarise
    and explain, not as trading signals.

    Args:
        ticker_id: TWSE/TPEX code, e.g. '2330' for TSMC.
        days: Lookback window (default 14).
        limit: Max articles (default 30, capped at 100).
    """
    rows = db_v2.query_news_for_ticker(ticker_id, days=days, limit=limit)
    return _stamp(
        {"ticker_id": ticker_id, "articles": rows, "count": len(rows),
         "days_window": days},
        source="raw_news",
        as_of=_today_iso(),
        freshness="hourly",
    )


# ── Tool: News Source Status ──────────────────────────────────────────────

@mcp.tool()
def n_source_status() -> dict:
    """Per-source freshness report. Use to verify feeds are still updating."""
    rows = db_v2.query_news_source_status()
    return _stamp(
        {"sources": rows, "count": len(rows)},
        source="raw_news",
        as_of=_today_iso(),
        freshness="real_time",
    )


# ── Tool: Watchlist (Phase 3.5) ──────────────────────────────────────────

@mcp.tool()
def w_watchlist(status: str = "active") -> dict:
    """Active watchlist — names being monitored but not yet at thesis stage.

    Sourced from the `watchlist` table in Neon. Same source the Telegram
    bot reads/writes; the `w_add` / `w_remove` tools below mutate it
    from the Claude app.

    Args:
        status: 'active' (default), 'archived', or 'all'.
    """
    rows = db_v2.query_watchlist(status=status)
    return _stamp(
        {"watchlist": rows, "count": len(rows), "status": status},
        source="watchlist",
        as_of=_today_iso(),
        freshness="real_time",
    )


# ── Tool: Universe (unified view) ────────────────────────────────────────

@mcp.tool()
def u_universe(filter: str = "all") -> dict:
    """One row per classified ticker — knowledge + watch-state + signals.

    Watched names sort first. Most queries can replace a chain of
    `sc_supply_chain_map` + `q_indicators` + `w_watchlist` with a single
    call to this tool.

    Args:
        filter:
            'all' — every classified ticker (default, ~26 rows)
            'watching' — only watch_status='active'
            'extreme' — RSI>80 / RSI<20 / BB outside [0,1] / |foreign_z|>2
    """
    rows = db_v2.query_universe(filter=filter)
    return _stamp(
        {"universe": rows, "count": len(rows), "filter": filter},
        source="view_universe",
        as_of=_today_iso(),
        freshness="T+1",
    )


# ── Tool: Watchlist mutations (write-capable, narrowly scoped) ───────────

@mcp.tool()
def w_add(ticker_id: str,
          reason: str | None = None,
          escalation_trigger: str | None = None) -> dict:
    """Add a ticker to the watchlist (or reactivate an archived row).

    Validates that the ticker exists in `dim_supply_chain` — the
    classified 26-name universe. Outside that universe, the watchlist
    rejects the add (the system's edge is supply-chain-mapped flow,
    not arbitrary screening).

    Args:
        ticker_id: e.g. '2330'.
        reason: optional one-line free-form note (why is this on the
                list).
        escalation_trigger: optional specific data condition that would
                            promote this to a thesis (e.g. 'foreign_z
                            stays >1.5 for 2 more sessions').
    """
    return db_v2.mutate_watchlist_add(
        ticker_id=ticker_id, reason=reason, escalation_trigger=escalation_trigger,
    )


@mcp.tool()
def w_remove(ticker_id: str) -> dict:
    """Archive a watchlist entry.

    Idempotent: re-running on an already-archived ticker returns ok:true with
    `already_archived: true` and changes nothing. ok:false means the ticker was
    never on the watchlist at all.
    """
    return db_v2.mutate_watchlist_remove(ticker_id=ticker_id)


# ── Tool: Lead-lag analysis ─────────────────────────────────────────────

@mcp.tool()
def q_valuation(
    ticker_id: str | None = None,
    pillar: str | None = None,
    max_pe: float | None = None,
    max_pb: float | None = None,
    min_yield: float | None = None,
    top_n: int = 30,
) -> dict:
    """Is a stock cheap or expensive? — valuation metrics per ticker.

    When to use: the user asks whether something is over/under-valued, or wants
    cheap names in a pillar. Gloss: P/E = price per $1 of yearly earnings (lower
    can mean cheaper — or slower growth); P/B = price per $1 of net assets;
    dividend yield = yearly dividend ÷ price. Sourced from TWSE BWIBBU_d, daily.
    Filters compose AND-style (e.g. pillar='semiconductor' + max_pb=2 → AI-semi
    names below 2× book). A NULL P/E means no positive earnings (excluded when
    max_pe is set). Fields: `pe`, `pb`, `dividend_yield`, `close`, `pillar`.

    Args:
        ticker_id: Optional single-ticker lookup.
        pillar: 'semiconductor' | 'infrastructure' | 'equipment' | 'energy'.
        max_pe: Cap on P/E ratio. NULL P/E excluded when set.
        max_pb: Cap on P/B ratio.
        min_yield: Minimum dividend yield in % (e.g. 3.0 for 3%+).
        top_n: Result limit (default 30).

    Returns rows sorted by P/B asc (cheapest first), each with company_name,
    pillar, node, close, dividend_yield, dividend_year, pe, pb, fiscal_period.
    """
    rows = db_v2.query_valuation(
        ticker_id=ticker_id, pillar=pillar,
        max_pe=max_pe, max_pb=max_pb, min_yield=min_yield, top_n=top_n,
    )
    asof = rows[0]["date"] if rows else None
    return _stamp(
        {"valuations": rows, "count": len(rows)},
        source="raw_twse_valuation",
        as_of=asof,
        freshness="daily",
        glossary=_GLOSS_VALUATION,
    )


@mcp.tool()
def q_macro(series: str | None = None, days: int = 30, latest: bool = True) -> dict:
    """Global macro series that set the tone for the Taiwan open.

    Taiwan trades as a high-beta expression of the US semiconductor cycle and
    the dollar. These five series are the only data in this system that is
    already known BEFORE the Taipei open — everything else here is Taiwan
    domestic and T+1.

        sox      Philadelphia Semiconductor Index — the cycle Taiwan tracks
        tsm_adr  TSMC ADR (NYSE: TSM) — the usual tell for the TAIEX open gap
        us10y    US 10-year Treasury yield, in percent — the liquidity regime
        dxy      US dollar index — risk appetite
        usdtwd   USD/TWD — the foreign-flow tell

    IMPORTANT for interpretation: `date` is the US SESSION date (UTC), not a
    Taiwan trading date. A US close on a Taiwan holiday still appears here, and
    "today" in Taipei is usually the US session of the previous calendar day.
    Do not align these dates to TWSE dates without saying which you mean.

    Args:
        series: One of sox | tsm_adr | us10y | dxy | usdtwd. Omit for all.
        days: Trailing calendar days of history (1-365, default 30).
        latest: True (default) returns just the most recent row per series —
                the pre-market snapshot. False returns the `days` history.
    """
    if latest and series is None:
        rows = db_v2.query_macro_latest()
    else:
        rows = db_v2.query_macro(series=series, days=days)
    asof = max((r["date"] for r in rows), default=None)
    return _stamp(
        {"macro": rows, "count": len(rows), "series_available": list(_MACRO_SERIES)},
        source="raw_macro",
        as_of=asof,
        freshness="daily (US session close, known before the Taipei open)",
        glossary=_GLOSS_MACRO,
    )


@mcp.tool()
def q_index_history(
    index_name: str | None = None,
    days: int = 30,
) -> dict:
    """Sector / cross-market index closes & changes from TWSE MI_INDEX.

    With index_name: returns up to `days` recent observations for that one
    index (e.g. '半導體類指數'). Without: snapshot of every index for the
    most recent date.

    Args:
        index_name: Exact Chinese index name. Common ones include
                    '發行量加權股價指數' (TAIEX), '半導體類指數',
                    '電子工業類指數', '金融保險類指數'.
        days: Trailing trading days when index_name is given (default 30).
    """
    rows = db_v2.query_index_history(index_name=index_name, days=days)
    asof = rows[0]["date"] if rows else None
    return _stamp(
        {"indices": rows, "count": len(rows)},
        source="raw_twse_index",
        as_of=asof,
        freshness="daily",
    )


@mcp.tool()
def q_regime(window: int = 30, days: int = 120) -> dict:
    """Detect the current market regime across two axes.

    Computes both metrics over the last `window` trading days:

      vol regime    annualised realised volatility of the broad market
                    (0050 ETF) over the last `window` days
                      <12% → low (calm trend, alpha-friendly)
                      12-25% → normal
                      >25% → high (stress, cut size)

      corr regime   average pairwise correlation across classified
                    tickers' returns over the same window
                      <0.30 → dispersed (idiosyncratic, alpha-friendly)
                      0.30-0.55 → normal
                      >0.55 → crowded (factor-dominated, beta-only)

    Combined into a regime_label (e.g. 'high_vol_crowded' = worst time
    for fundamental single-name bets; 'low_vol_dispersed' = best).

    Also reports vol_trend / corr_trend (rising/falling/flat) over the
    prior ~60 days so you can tell if conditions are improving.

    Args:
        window: rolling window in trading days (default 30).
        days:   total history needed (default 120 — 4× the window).

    Use case: every position-sizing or thesis-opening decision should
    take regime into account. In high_vol_crowded → cut size, lean on
    factor exposure not alpha. In low_vol_dispersed → fundamental bets
    are most likely to pay off; q_factor_screen alphas are reliable.
    """
    from quant.regime import compute_regime
    result = compute_regime(window=int(window), days=int(days))
    return _stamp(result, source="regime",
                  as_of=_today_iso(), freshness="on-demand")


@mcp.tool()
def q_quality_score(
    ticker_id: str | None = None,
    pillar: str | None = None,
    node: str | None = None,
    tickers: list[str] | None = None,
    top_n: int = 30,
) -> dict:
    """Composite TW-specific quality score per ticker.

    Single 0-100 number per ticker, equal-weighted average of five subscores
    each mapped to [0, 100]:

      growth                latest monthly revenue YoY %
      growth_acceleration   latest YoY minus prior 3-month average
      valuation             P/B percentile vs own 90-day history
                            (low percentile = cheap = high score)
      flow                  foreign_net_z20 from view_latest_signals
      trend                 % above SMA-200

    Real "quality" in factor literature means high ROE / stable earnings,
    which we don't have. This composite reads as "growth-at-a-price + flow +
    trend" — TW-tailored. Higher score = better on this composite.

    Two modes:
      - Single ticker: pass ticker_id alone
      - Cross-section: pass pillar/node/tickers (omit ticker_id)

    Args:
        ticker_id: single-ticker mode
        pillar:    'semiconductor' | 'infrastructure' | 'equipment' | 'energy'
        node:      narrows pillar (e.g. 'server-odm', 'memory-dram')
        tickers:   explicit list (overrides pillar/node)
        top_n:     limit on cross-section returns (default 30)

    Single-ticker returns: ticker_id, name, pillar, node, quality_score,
    subscores{...}, raw{revenue YoY, P/B, foreign_z, ...}, missing[],
    interpretation string.

    Cross-section returns rows[] sorted by quality_score desc.
    """
    if ticker_id and not (pillar or node or tickers):
        from quant.quality_score import compute_quality_score
        result = compute_quality_score(ticker_id)
        return _stamp(result, source="quality_score",
                      as_of=_today_iso(), freshness="on-demand")
    from quant.quality_score import compute_quality_screen
    rows = compute_quality_screen(
        pillar=pillar, node=node, tickers=tickers, top_n=int(top_n),
    )
    return _stamp(
        {"rows": rows, "count": len(rows),
         "filter": {"pillar": pillar, "node": node, "tickers": tickers}},
        source="quality_score",
        as_of=_today_iso(),
        freshness="on-demand",
    )


@mcp.tool()
def q_cointegration_pair(
    ticker_a: str,
    ticker_b: str,
    days: int = 120,
) -> dict:
    """Pairs-trading primitive: tests if two tickers' spread mean-reverts.

    Engle-Granger two-step:
      1. Regress log(P_a) on log(P_b) — residual ε is the spread
      2. ADF test on ε — is it stationary? (reject unit root → cointegrated)
      3. Half-life from AR(1) on ε — how fast does a 2σ shock revert?
      4. Current z-score vs trailing distribution

    Decision rule: pair is "tradeable" when stationary at 5% AND |z|≥1.5.
    The signal field tells you the direction:
      'long_a_short_b'  spread far below mean — expects revert up
      'short_a_long_b'  spread far above mean — expects revert down
      'wait'            stationary but |z|<1.5
      'no_signal'       not cointegrated, mean-reversion invalid

    Use case: cluster two same-node tickers (e.g. 3037 Unimicron + 8046
    Nan Ya PCB substrate peers); if spread is stationary with short
    half-life, you have a tight stat-arb pair.

    Args:
        ticker_a, ticker_b: ticker IDs, both must have OHLCV in window.
        days: regression window (default 120).

    Returns: hedge_ratio, ADF stat + critical values, stationary flags,
    half_life_days, spread_now/mean/std, z_score, tradeable bool, signal,
    and a plain-English interpretation.
    """
    from quant.cointegration import compute_cointegration
    result = compute_cointegration(ticker_a, ticker_b, days=days)
    return _stamp(result, source="cointegration",
                  as_of=_today_iso(), freshness="on-demand")


@mcp.tool()
def q_pca_decompose(
    tickers: list[str],
    days: int = 120,
    k: int = 3,
) -> dict:
    """PCA risk decomposition on a basket of tickers.

    Decomposes daily log-returns into top-k orthogonal principal components
    and returns each ticker's loading on each PC, plus the % of variance
    explained. PC₁ is almost always a common-factor (≈ market β) for any
    correlated set; PC₂ and PC₃ usually split the universe along
    interpretable axes (e.g. "semi vs ODM", "AI-pure vs diversified",
    "memory vs logic").

    Use case: "I have N positions — am I diversified, or am I betting on
    one factor N different ways?"
      - PC₁ > 70% → concentration warning, the basket is effectively one
        position
      - PC₁ ~50%, PC₂ ~25% → genuine 2-factor split, real diversification
      - All PCs <40% → very diversified (rare for a focused basket)

    Args:
        tickers: 2-30 ticker IDs.
        days: trailing trading days for the regression (default 120).
        k: number of principal components to return (default 3).

    Returns: tickers, n_obs, components[] (each with pc index,
    explained_variance, explained_variance_pct, loadings dict, and an
    interpretation_hint), cumulative_variance_pct, and a plain-English
    `interpretation` string.
    """
    from quant.pca_decompose import compute_pca
    result = compute_pca(tickers=tickers, days=days, k=k)
    return _stamp(result, source="pca_decompose",
                  as_of=_today_iso(), freshness="on-demand")


@mcp.tool()
def q_factor_screen(
    pillar: str | None = None,
    node: str | None = None,
    tickers: list[str] | None = None,
    days: int = 90,
    sort_by: str = "alpha_tstat",
    top_n: int = 25,
) -> dict:
    """Statistically real idiosyncratic alpha across the classified universe.

    When to use: the most ADVANCED screener — for a beginner asking "what looks
    good", prefer `flow_leaders_scan` or `beginner_stock_card` instead. Runs the
    same factor regression as `q_factor_alpha` (market + sector + flow) on every
    ticker matching the filter, in one DB roundtrip, then returns them ranked to
    find names with statistically real idiosyncratic alpha — the t-stat (|t|>2 →
    significant) is the primary signal, not the raw alpha number (noisy at short
    windows).

    Args:
        pillar: filter by AI pillar — 'semiconductor' | 'infrastructure' |
                'equipment' | 'energy'. If None, screens the full classified
                universe.
        node: filter by node (e.g. 'server-odm', 'high-speed-pcb',
              'memory-dram'); composes with pillar.
        tickers: explicit ticker list; overrides pillar/node when given.
        days: regression window (default 90).
        sort_by: 'alpha_tstat' (default) | 'alpha_annualized' | 'r_squared'
                 | 'n_obs'. Default surfaces statistically real alpha.
        top_n: cap on rows returned (default 25).

    Returns rows with: ticker_id, company_name, ai_pillar, node,
    sector_index, alpha_daily, alpha_annualized, alpha_tstat,
    alpha_significant, betas{market,sector,flow}, beta_tstats{...},
    r_squared, factors_used, n_obs.

    Practical reading: ignore tickers with alpha_significant=false. Among
    those with |t|>2, large positive alpha = real idiosyncratic
    outperformance; large negative alpha = real underperformance even
    though the index is rising (often the most overlooked short signal).
    """
    from quant.factor_alpha import compute_factor_screen
    rows = compute_factor_screen(
        pillar=pillar, node=node, tickers=tickers,
        days=days, sort_by=sort_by,
    )
    rows = rows[: int(top_n)]
    return _stamp(
        {"rows": rows, "count": len(rows),
         "filter": {"pillar": pillar, "node": node,
                    "tickers": tickers, "days": days, "sort_by": sort_by}},
        source="factor_alpha",
        as_of=_today_iso(),
        freshness="on-demand",
    )


@mcp.tool()
def q_factor_alpha(ticker_id: str, days: int = 120) -> dict:
    """Decompose a ticker's recent returns into factor exposures + residual α.

    Fits an OLS regression of the ticker's daily log-returns over the last
    `days` trading days against three factors:

      market  — 0050 ETF return (broad TW market)
      sector  — pillar sector index return (e.g. 半導體類指數 for semis)
      flow    — long-short portfolio of classified tickers ranked daily
                by 20-day rolling z-score of T86 foreign_net (top quintile
                minus bottom quintile, equal-weight). This isolates whether
                the ticker is exposed to the "foreign-buying tide" or has
                idiosyncratic drift on top of it.

    Returns:
      alpha_daily        residual mean daily return after factor exposure
      alpha_annualized   alpha_daily × 252 (rough annualisation)
      alpha_tstat        t-statistic on alpha; |t|>2 is significant
      alpha_significant  bool: |t|>2
      betas              dict: factor name -> beta
      beta_tstats        dict: factor name -> beta t-stat
      r_squared          % of variance explained by factors
      interpretation     plain-English summary suitable for direct quoting

    Use case: "is this ticker's recent outperformance real (positive α with
    significant t-stat), or is it just exposure to the flow factor that any
    name with similar foreign-buying would have shown?" Read alpha_tstat
    and the interpretation field together to decide.

    Args:
        ticker_id: e.g. '3231', '2330'.
        days: Trailing trading days for the regression window (default 120).
              Minimum ~30 needed; more is more reliable.
    """
    from quant.factor_alpha import compute_factor_alpha
    result = compute_factor_alpha(ticker_id, days=days)
    return _stamp(result, source="factor_alpha",
                  as_of=_today_iso(), freshness="on-demand")


@mcp.tool()
def q_lead_lag(
    upstream: str | None = None,
    downstream: str | None = None,
    min_corr: float = 0.4,
    min_gain: float = 0.0,
    top_n: int = 20,
) -> dict:
    """Pairs where the upstream ticker's price moves predict the downstream's
    price moves N days later.

    Computed nightly from the last 60 trading days of returns. For each pair
    of classified tickers we compute correlation at lags 0..7 days and keep
    rows where lag>0 has meaningful forward predictive correlation.

    Use this to find supply-chain lead-lag effects: e.g. TSMC's foreign-flow
    moves often precede downstream ODMs by 1-3 days. A high `gain` (forward
    rho minus same-day rho) is the strongest signal — it means tomorrow's
    move in `downstream_id` is better predicted by today's move in
    `upstream_id` than by today's same-day correlation.

    Args:
        upstream: Optional ticker filter — only return rows where this is
                  the leading ticker.
        downstream: Optional ticker filter — only return rows where this is
                    the lagging ticker.
        min_corr: Minimum forward correlation (default 0.4).
        min_gain: Minimum forward-correlation gain over coincident (default 0.0).
        top_n: Limit (default 20).

    Returns rows with: upstream_id/name/pillar, downstream_id/name/pillar,
    lag_days, rho_lag, rho_0, gain, n_obs, window_days, asof.
    """
    rows = db_v2.query_lead_lag(
        upstream=upstream, downstream=downstream,
        min_corr=min_corr, min_gain=min_gain, top_n=top_n,
    )
    asof = rows[0]["asof"] if rows else None
    return _stamp(
        {"pairs": rows, "count": len(rows)},
        source="lead_lag",
        as_of=asof,
        freshness="nightly",
    )


# ── Tool: Digests (Phase 3) ──────────────────────────────────────────────

@mcp.tool()
def d_recent(days: int = 3, kind: str | None = None) -> dict:
    """Recent cron-generated briefs (pre_market / intraday_alert / post_close).

    Briefs are written by the GitHub Actions cron at meaningful times in
    the Taiwan trading day. Each one summarises news + signals and
    explicitly flags candidates that warrant deeper analysis.

    Args:
        days: Lookback window in days (default 3).
        kind: Optional filter — 'pre_market', 'intraday_alert',
              'post_close', or 'thesis_status'.
    """
    rows = db_v2.query_digest_recent(days=days, kind=kind)
    return _stamp(
        {"digests": rows, "count": len(rows)},
        source="daily_digest",
        as_of=_today_iso(),
        freshness="cron-driven",
    )


@mcp.tool()
def d_for_date(digest_date: str, kind: str | None = None) -> dict:
    """All digests for one specific date.

    Args:
        digest_date: ISO date (YYYY-MM-DD) in Taiwan time.
        kind: Optional filter as in d_recent.
    """
    rows = db_v2.query_digest_for_date(digest_date, kind=kind)
    return _stamp(
        {"digests": rows, "count": len(rows), "date": digest_date},
        source="daily_digest",
        as_of=digest_date,
        freshness="cron-driven",
    )


# ── Tool: Data Status ─────────────────────────────────────────────────────

@mcp.tool()
def sc_data_status() -> dict:
    """Check the status of the alphatecx v2 data pipeline.

    Returns row counts, latest ingestion date, and data freshness
    for all tables. Use this to verify data is up to date before analysis.
    """
    stats = db_v2.query_data_status()
    return _stamp(
        stats,
        source="ingestion_log",
        as_of=_today_iso(),
        freshness="real_time",
    )


# ── Tool: Capabilities ────────────────────────────────────────────────────

@mcp.tool()
def sc_capabilities() -> dict:
    """Describe all available tools and what this MCP server provides.

    alphatecx v2 is a Taiwan market intelligence system with deep AI supply
    chain classification. It tracks institutional capital flows (foreign
    investors, investment trusts, dealers) across ~7000 TWSE/TPEX stocks,
    with a curated subset classified into 4 AI pillars: semiconductor,
    equipment, infrastructure, energy.

    The system detects "trickle down" accumulation patterns as foreign
    capital flows from foundry (TSMC) → server ODMs → cooling/PCB → power.
    """
    # What the CALLER can actually reach. Without this the model is handed the
    # full technical map, tries a locked tool, and gets refused -- the same
    # class of failure as the capabilities list drifting from the registry,
    # just in the other direction.
    _plan = current_plan.get()
    _locked = tiers_mod.locked_for(_plan) if current_customer.get() not in (None, OWNER_SUBJECT) else []
    return {
        "server": "alphatecx-v2",
        "description": "Taiwan market intelligence — full-market flow tracking plus AI supply chain classification",
        "your_plan": _plan or tiers_mod.PRIVATE,
        "locked_tools": _locked,
        "locked_note": (
            f"{len(_locked)} tool(s) need a higher plan. They are listed below "
            "like everything else, but calling one returns `_locked` instead of "
            "data — tell the user it is a paid feature rather than retrying."
        ) if _locked else "All tools on this server are available to you.",
        "data_coverage": {
            "flow_tickers": "~7000 TWSE + TPEX stocks from T86",
            "classified": "~27 stocks across 4 AI pillars",
            "technical_signals": "computed where OHLCV history is harvested; currently deepest on classified tickers",
            "history": "bounded recent windows after storage-retention pruning",
            "update_frequency": "daily after 16:00 CST",
        },
        "ai_pillars": {
            "semiconductor": "Foundry (TSMC), ASIC/Custom IP (Alchip, GUC), Advanced Packaging (ASE, SPIL)",
            "equipment": "Testing (KYEC), Facility/Cleanroom (Marketech), Materials (GlobalWafers)",
            "infrastructure": "Server ODMs (Quanta, Wistron, Foxconn), Cooling (AVC, Auras), PCB (Unimicron), BMC (Aspeed)",
            "energy": "Power Supply (Delta, Lite-On), Heavy Electrical (Fortune), Green Energy (HDRE)",
        },
        # Every @mcp.tool() must appear here — the server instructions call this
        # "the full technical map", so a tool missing from it is a tool the model
        # is told does not exist. tests/test_capabilities.py enforces the match.
        "tools": [
            {"name": "start_here", "purpose": "Orientation menu for a new or open-ended question — plain-language asks mapped to the tool that answers each, plus a beginner glossary"},
            {"name": "sc_capabilities", "purpose": "This map: every tool, what it is for, and the data behind it"},
            {"name": "my_profile", "purpose": "The current user's saved risk profile (conservative/balanced/aggressive) and how to adapt framing to it"},
            {"name": "set_my_risk_profile", "purpose": "Persist the user's risk tolerance once they state it (writes to DB)"},
            {"name": "investing_principles", "purpose": "Durable school-neutral investing principles to ground reasoning, emphasised by the user's risk tier"},
            {"name": "ticker_lookup", "purpose": "Find a ticker id from a company name or partial code — the usual first step"},
            {"name": "sc_sector_momentum", "purpose": "Sector-level flow aggregation by pillar/node"},
            {"name": "sc_ticker_momentum", "purpose": "Per-ticker flow with buy streak tracking"},
            {"name": "sc_supply_chain_map", "purpose": "Look up ticker → pillar/node/US partner"},
            {"name": "raw_flow_history", "purpose": "Daily flow time series for one ticker"},
            {"name": "sc_compare_nodes", "purpose": "Side-by-side node flow comparison"},
            {"name": "sc_accumulation_screen", "purpose": "Find tickers with sustained FINI buying"},
            {"name": "market_flow_screener", "purpose": "Full TWSE/TPEX flow screener across classified and unclassified tickers"},
            {"name": "scan_limit_board", "purpose": "Scan the TWSE/TPEX limit-up/limit-down board (EOD) and triage each hit as sleeper vs chase"},
            {"name": "momentum_leaders_scan", "purpose": "Strong-and-early trend leaders with a mandatory trailing stop; rejects parabolic/retail-pump blow-offs as chases. mode=monitor re-checks held names' stops"},
            {"name": "flow_leaders_scan", "purpose": "Market-wide screen for quiet foreign accumulation into a still-cheap, still-flat price (generative sleeper board)"},
            {"name": "session_state", "purpose": "Taipei market phase + trading-calendar status; flags 試撮 pre-open indicative prices so a simulated quote is never read as real"},
            {"name": "quote", "purpose": "Realtime-ish watchlist quotes (Fugle preferred, TWSE MIS fallback) with authoritative limit-up/down prices; stamps 試撮 indicative prices"},
            {"name": "dividend_calendar", "purpose": "Ex-dividend/ex-rights dates + amounts; answers whether a buyer today still receives the dividend (TWSE 除權除息)"},
            {"name": "sc_data_status", "purpose": "Pipeline health and data freshness"},
            {"name": "q_indicators", "purpose": "Latest technical + flow indicators for one ticker"},
            {"name": "beginner_stock_card", "purpose": "Beginner-friendly factual stock card with grouped numbers and chart-ready points"},
            {"name": "price_history", "purpose": "Chart-ready OHLCV history for one ticker"},
            {"name": "q_screener", "purpose": "Filter signal-covered tickers by AND-combined indicator conditions"},
            {"name": "q_backtest", "purpose": "Backtest a single-threshold signal rule"},
            {"name": "q_backtest_compound", "purpose": "Backtest multi-condition (AND) compound rules; up to 4 conditions"},
            {"name": "q_valuation", "purpose": "Is a stock cheap or expensive — P/E, P/B and dividend yield per ticker (TWSE BWIBBU)"},
            {"name": "q_index_history", "purpose": "TAIEX / index close history for market context"},
            {"name": "q_macro", "purpose": "Global macro set before the Taipei open: SOX, TSMC ADR, US 10Y, DXY, USD/TWD"},
            {"name": "q_regime", "purpose": "Market regime classification (trend vs chop, risk-on vs risk-off)"},
            {"name": "q_quality_score", "purpose": "Composite fundamental quality score for a ticker"},
            {"name": "q_cointegration_pair", "purpose": "Test two tickers for a mean-reverting (cointegrated) relationship"},
            {"name": "q_pca_decompose", "purpose": "Principal components of the return matrix — what factor is driving the market"},
            {"name": "q_factor_screen", "purpose": "Screen by statistical factor exposures (advanced; prefer q_screener for technical setups)"},
            {"name": "q_factor_alpha", "purpose": "Residual alpha after factor exposures are stripped out"},
            {"name": "q_lead_lag", "purpose": "Which ticker's move tends to precede another's, and by how many days"},
            {"name": "n_recent", "purpose": "Recent news articles (RSS + Google News); titles + summaries"},
            {"name": "n_for_ticker", "purpose": "Articles mentioning a ticker (text-match fallback until Phase 2b entity extraction)"},
            {"name": "n_source_status", "purpose": "Per-source freshness — verify feeds still updating"},
            {"name": "d_recent", "purpose": "Recent cron-generated briefs (pre-market / intraday / post-close)"},
            {"name": "d_for_date", "purpose": "All digests for one specific date"},
            {"name": "w_watchlist", "purpose": "Active watchlist — bot-managed names being monitored"},
            {"name": "u_universe", "purpose": "Unified read: classified-ticker × knowledge × watch-state × signals"},
            {"name": "w_add", "purpose": "Add a ticker to the watchlist (writes to DB; same as bot /watch)"},
            {"name": "w_remove", "purpose": "Archive a watchlist entry (writes to DB; same as bot /unwatch)"},
            {"name": "rg_status", "purpose": "Risk Guard: today's market risk light, its five subitems, and settlement-cash state"},
            {"name": "rg_positions", "purpose": "Risk Guard: monitored positions/watch names with warn+exit lines and distance to each"},
            {"name": "rg_alerts", "purpose": "Risk Guard: recent alert stream (stop, settlement, light change) — what the operator was already told"},
            {"name": "rg_checklist", "purpose": "Risk Guard: six-question entry checklist; blocks or says nothing is stopping you — never recommends a buy"},
            {"name": "rg_journal_add", "purpose": "Risk Guard: record a decision made in conversation (writes to DB)"},
        ],
        "risk_guard": {
            "purpose": "Post-close risk system whose only job is to prevent large losses. "
                       "It never produces buy signals, target prices, or forecasts.",
            "phase": "Phase 1 live: M1 risk light, M2 stop alerts, M2b settlement check. "
                     "M3 sector strength, M4 intraday anomaly, M5 intent score, "
                     "M6 announcements and M7 rhythm veto are not yet built; checklist "
                     "questions backed by them report as skipped.",
        },
    }


# ── Risk Guard tools (rg_*) ────────────────────────────────────────────────
#
# PRD §6 介面三: the dashboard, the Telegram bot and this conversation all read
# one row of truth. Every tool below is a thin DB read except rg_journal_add —
# nothing here recomputes a light, so Claude can never disagree with the push
# the operator already received on their phone.


@mcp.tool()
def rg_status() -> dict:
    """Is the Taiwan market risky right now? — the market risk light.

    When to use: the user asks whether it's a safe time to invest, or before you
    discuss ANY new entry — a red light means new positions are off the table no
    matter how good a single name looks. Gloss: the light (green/yellow/red) is a
    whole-market caution gauge scored post-close from breadth, flows and futures
    — it is about market conditions, not any one stock.

    Returns the light (green/yellow/red), the score, the per-subitem breakdown
    with the inputs each one saw, upcoming settlement obligations, and the last
    reported settlement-account balance.
    """
    market = rg_db.latest_market_daily()
    if not market:
        return _stamp({"error": "no risk light computed yet — run "
                                "`python -m riskguard.pipeline --mode post_close`"},
                      source="rg_market_daily", as_of=None, freshness="none")

    today = _today_iso()
    balance = rg_db.latest_balance()
    reasons = market.get("reasons") or []
    return _stamp(
        {
            "risk_light": market.get("risk_light"),
            "risk_score": market.get("risk_score"),
            "behaviour": {
                "green": "正常",
                "yellow": "新倉減半、停損上移",
                "red": "禁新倉,建議總持股 ≤50%",
            }.get(market.get("risk_light")),
            "taiex": {
                "close": market.get("taiex_close"),
                "pct": market.get("taiex_pct"),
                "ma20": market.get("taiex_ma20"),
                "ma60": market.get("taiex_ma60"),
                "ret_5d_pct": market.get("taiex_ret_5d_pct"),
            },
            "subitems": reasons,
            "data_missing": [r["name"] for r in reasons if r.get("data_missing")],
            "breadth": {"adv": market.get("adv_count"), "dec": market.get("dec_count"),
                        "adv_ratio_5d": market.get("adv_ratio_5d")},
            "margin_chg_5d_pct": market.get("margin_chg_5d_pct"),
            "fut_foreign_net_oi": market.get("fut_foreign_net_oi"),
            "settlement": {
                "upcoming": rg_db.settlement_schedule(today),
                "balance": balance,
            },
            "no_trade_reason": rg_db.no_trade_reason(today),
        },
        source="rg_market_daily",
        as_of=market.get("date"),
        freshness="T+0 post-close",
        glossary=_GLOSS_RISK_LIGHT,
    )


@mcp.tool()
def rg_positions(include_inactive: bool = False) -> dict:
    """Monitored positions and watch names with their stop lines and distances.

    Shows cost, warning line (halve), exit line (full exit), the latest close,
    and how far price sits from each line. `exit_is_fallback` marks a line the
    system derived from cost × (1 − hard_stop_pct) because none was set.

    Args:
        include_inactive: also return archived rows, which include the
            blacklist ("拉黑") names kept as a do-not-buy record.
    """
    rows = rg_db.positions(include_inactive=include_inactive)
    closes = rg_db.latest_closes([r["ticker_id"] for r in rows])
    enriched = rg_stops.distances(rows, closes)
    return _stamp(
        {
            "positions": [r for r in enriched if r["kind"] == "position"],
            "watch": [r for r in enriched if r["kind"] == "watch"],
            "count": len(enriched),
        },
        source="rg_positions",
        as_of=_today_iso(),
        freshness="T+1 close",
    )


@mcp.tool()
def rg_alerts(days: int = 3) -> dict:
    """Recent Risk Guard alerts — what the system already told the operator.

    Read this before giving advice so the conversation reinforces the pushes
    rather than contradicting them. `pushed=false` means the alert was recorded
    but Telegram delivery failed.

    Args:
        days: lookback window in days (default 3).
    """
    rows = rg_db.recent_alerts(days=days)
    return _stamp(
        {"alerts": rows, "count": len(rows), "days": days},
        source="rg_alerts",
        as_of=_today_iso(),
        freshness="real_time",
    )


@mcp.tool()
def rg_checklist(
    ticker_id: str,
    buy_amount: float | None = None,
    available_cash: float | None = None,
) -> dict:
    """Run the six-question entry checklist against one ticker.

    This tool never recommends a buy. Any failed question returns
    「今天不買。原因:…」; a clean sheet returns 「沒有阻止你的理由」 — the
    absence of a reason to stop, not a reason to act. Questions whose module is
    not live yet (Q2 sector rank, Q4 disposition status) report as skipped and
    are listed under `warnings`, never silently passed.

    Args:
        ticker_id: TWSE/TPEX ticker, e.g. '2344'.
        buy_amount: intended purchase size in TWD, for Q6.
        available_cash: available cash in TWD; defaults to the last
            /balance report if omitted.
    """
    facts = rg_db.checklist_facts(ticker_id, _today_iso(),
                                  buy_amount=buy_amount, available_cash=available_cash)
    result = rg_checklist_mod.evaluate(facts)
    return _stamp(result, source="rg_checklist", as_of=_today_iso(), freshness="T+1")


@mcp.tool()
def rg_journal_add(text: str, ticker_id: str | None = None) -> dict:
    """Record a trading decision made in conversation into the Risk Guard journal.

    Use this whenever the operator commits to something concrete — a stop level,
    a decision to stay out, a condition they are waiting for. Later alerts can
    then quote the operator's own words back at them, which is far harder to
    rationalise away than a generic warning.

    Args:
        text: the decision, in the operator's own framing.
        ticker_id: optional ticker the decision is about.
    """
    if not text or not text.strip():
        return {"error": "text is required"}
    row = rg_db.journal_add(text.strip(), ticker_id)
    return _stamp({"saved": row}, source="rg_journal",
                  as_of=_today_iso(), freshness="real_time")


# ── FastAPI mount ──────────────────────────────────────────────────────────

mcp_app = mcp.streamable_http_app()


@contextlib.asynccontextmanager
async def lifespan(app):
    async with mcp._session_manager.run():
        yield


app = FastAPI(title="alphatecx-v2", version="0.2", lifespan=lifespan)


@app.get("/")
def root():
    return {"name": "alphatecx-v2", "ok": True}


# Deep-health cache. /health is PUBLIC (security.py) so the DB-touching variant
# must not be a free query amplifier — one probe per window, everyone else in
# that window gets the cached verdict. 10s is fine-grained enough for any
# monitor and coarse enough that hammering the endpoint costs one query.
_DEEP_HEALTH_TTL = 10.0
_deep_health_cache: dict = {"at": 0.0, "db": False}


@app.get("/health")
def health(deep: bool = False):
    """Liveness by default; `?deep=1` also proves the database answers.

    The split matters: Zeabur's restart-on-unhealthy probe should use the
    shallow form (restarting the server does not fix a down Postgres and would
    just flap), while an uptime monitor should use `?deep=1` — before this, the
    service reported ok while every data tool failed, which is exactly how the
    permission-denied outage looked from the outside.
    """
    if not deep:
        return {"ok": True, "server": "alphatecx-v2"}
    now = time.monotonic()
    if now - _deep_health_cache["at"] > _DEEP_HEALTH_TTL:
        try:
            db_v2._fetch("SELECT 1")
            _deep_health_cache.update(at=now, db=True)
        except Exception:               # noqa: BLE001 — a probe must not 500
            log.exception("deep health check failed")
            _deep_health_cache.update(at=now, db=False)
    if _deep_health_cache["db"]:
        return {"ok": True, "server": "alphatecx-v2", "db": True}
    return JSONResponse(status_code=503,
                        content={"ok": False, "server": "alphatecx-v2", "db": False})


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if is_authorized_path(path, MCP_BEARER_TOKEN, CONSOLE_TOKEN):
        # The URL-as-secret MCP path is the owner. It used to leave
        # current_customer unset, which meant the profile tools saw no identity
        # at all and set_my_risk_profile could only answer "can't persist" —
        # inert for the operator, who is the connector's heaviest user. Naming
        # the subject here gives it the reserved `owner` row (sql/025) to key on.
        # Metering is unaffected: _stamp skips sub="owner" either way.
        if path == f"/mcp/{MCP_BEARER_TOKEN}" or path.startswith(f"/mcp/{MCP_BEARER_TOKEN}/"):
            tok = current_customer.set(OWNER_SUBJECT)
            try:
                return await call_next(request)
            finally:
                current_customer.reset(tok)
        return await call_next(request)

    # Bare /mcp is the OAuth-protected mount that cloud connectors (and so
    # mobile) use. It is the ONE path that answers 401 instead of 404: the
    # WWW-Authenticate header is what starts discovery. Everything else keeps
    # 404-ing, so /g, /d, /h, /t and /mcp/<token> stay hidden.
    if path == "/mcp" or path.startswith("/mcp/"):
        claims = _access_claims(request.headers.get("authorization", ""))
        if claims is None:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token"},
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata='
                        f'"{_base_url(request)}/.well-known/oauth-protected-resource"'
                    )
                },
            )
        sub = claims.get("sub", OWNER_SUBJECT)
        # Per-session gate for customers. This also closes the residual from the
        # refresh fix: a suspended customer is now blocked at the read path, not
        # only at token refresh, so revocation bites within the access-token TTL.
        if sub != OWNER_SUBJECT:
            denial = _customer_gate(sub)
            if denial is not None:
                return denial
        # Serve /mcp as if it were /mcp/ rather than letting Starlette's mount
        # emit a 307. Connectors that just completed the OAuth dance do not
        # reliably re-issue a POST (with body and Authorization) against the
        # redirect target, so the handshake fails right after a successful
        # authorization — which is exactly what "your account was authorized,
        # but the server returned an error" looks like from the client side.
        if path == "/mcp":
            request.scope["path"] = "/mcp/"
            request.scope["raw_path"] = b"/mcp/"
        tok = current_customer.set(sub)
        try:
            return await call_next(request)
        finally:
            current_customer.reset(tok)
            current_plan.set(None)

    return JSONResponse(status_code=404, content={"error": "not_found"})


def _access_claims(header: str) -> dict | None:
    """Verified claims from an `Authorization: Bearer <access token>` header, or
    None. Refresh tokens are rejected (kind mismatch), same as the old
    bearer_token_valid, but here we keep the claims so the caller learns `sub`."""
    if not header or not header.lower().startswith("bearer "):
        return None
    return oauth_mod.verify(header[7:].strip(), "access")


def _customer_gate(sub: str):
    """Per-session enforcement for a customer subject. Returns a JSONResponse to
    deny, or None to allow. Account state is authoritative (402 if not usable);
    the monthly quota is a soft ceiling on top (429 when reached).

    A store we cannot reach is 503, NOT 402: `account_inactive` is a claim about
    the customer's subscription, and answering it on a Postgres blip told paying
    customers their account had lapsed. 503 is honest and reads as transient to
    every client's retry logic.
    """
    try:
        customer = customers_mod.get(sub)
    except customers_mod.LookupUnavailable:
        return JSONResponse(status_code=503, content={"error": "store_unavailable"})
    if not customer or customer.get("status") not in customers_mod.USABLE_STATUSES:
        return JSONResponse(status_code=402, content={"error": "account_inactive"})
    current_plan.set(customer.get("plan"))
    quota = tiers_mod.effective_quota(customer)
    if quota is not None and usage_mod.calls_this_month(sub) >= quota:
        return JSONResponse(status_code=429, content={"error": "quota_exceeded"})
    return None


# ── OAuth 2.1 + PKCE (cloud connectors / mobile) ──────────────────────────
#
# Additive: URL-as-secret keeps serving Claude Code and the Desktop bridge.
# See docs/OAUTH-PLAN.md and mcp_server/api/oauth.py for why this is stateless.

def _base_url(request: Request) -> str:
    """Public origin, honouring the proxy headers Zeabur sets — behind TLS
    termination request.url.scheme reads 'http', and an issuer that disagrees
    with the URL the client typed fails discovery validation."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get(
        "host", request.url.netloc)
    return f"{proto}://{host}"


@app.get("/.well-known/oauth-protected-resource")
def oauth_protected_resource(request: Request):
    return oauth_mod.protected_resource_metadata(_base_url(request))


@app.get("/.well-known/oauth-authorization-server")
def oauth_authorization_server(request: Request):
    return oauth_mod.authorization_server_metadata(_base_url(request))


@app.post("/register")
async def oauth_register(request: Request):
    """Dynamic Client Registration. The client_id is derived from the redirect
    URIs rather than stored, so nothing has to survive a restart."""
    body = await request.json()
    redirect_uris = body.get("redirect_uris") or []
    if not redirect_uris:
        return JSONResponse(status_code=400,
                            content={"error": "invalid_redirect_uri"})
    return JSONResponse(status_code=201, content={
        "client_id": oauth_mod.client_id_for(redirect_uris),
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    })


@app.get("/authorize")
def oauth_authorize_form(client_id: str = "", redirect_uri: str = "",
                         state: str = "", code_challenge: str = "",
                         code_challenge_method: str = "S256"):
    if code_challenge_method != "S256" or not code_challenge:
        return JSONResponse(status_code=400,
                            content={"error": "invalid_request"})
    # Exact match against the URIs this client_id was derived from. No prefix,
    # no wildcard — for a public client this check is the whole boundary.
    if not oauth_mod.client_id_matches(client_id, [redirect_uri]):
        return JSONResponse(status_code=400,
                            content={"error": "invalid_client"})
    return HTMLResponse(_authorize_html(client_id, redirect_uri, state,
                                        code_challenge))


def _resolve_subject(credential: str) -> str | None:
    """Map a login credential to a token subject, or None to reject.

    The shared OAUTH_PASSWORD is the owner login (checked first, needs no DB, so
    owner access survives a customers-table outage). Any other credential is
    tried as a per-customer connector secret. This is where single-tenant
    ("everyone is owner") becomes multi-tenant — kept in the HTTP layer so
    oauth.py stays DB-free and its stateless tests are unaffected.
    """
    if oauth_mod.password_ok(credential):
        return "owner"
    customer = customers_mod.authenticate(credential)
    return customer["id"] if customer else None


def _subject_still_valid(sub: str) -> bool:
    """Whether a token subject may still be re-minted at refresh time.

    Owner is always valid — its credential is the shared OAUTH_PASSWORD, revoked
    by rotating the env var, not the DB. A customer subject must still exist and
    hold a usable status.

    Unlike the read gate, this one still fails closed on an unreachable store: a
    refresh mints a fresh 90-day credential, so declining to issue one during a
    blip costs a retry, while issuing one wrongly costs three months. Access
    tokens outlive a short outage anyway, so live sessions are unaffected.
    """
    if sub == OWNER_SUBJECT:
        return True
    try:
        customer = customers_mod.get(sub)
    except customers_mod.LookupUnavailable:
        return False
    return bool(customer) and customer.get("status") in customers_mod.USABLE_STATUSES


@app.post("/authorize")
async def oauth_authorize_submit(request: Request):
    form = await request.form()
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    if not oauth_mod.client_id_matches(client_id, [redirect_uri]):
        return JSONResponse(status_code=400, content={"error": "invalid_client"})
    sub = _resolve_subject(str(form.get("password", "")))
    if sub is None:
        return HTMLResponse(
            _authorize_html(client_id, redirect_uri, str(form.get("state", "")),
                            str(form.get("code_challenge", "")),
                            error="Incorrect password."),
            status_code=401,
        )
    code = oauth_mod.make_code(client_id, redirect_uri,
                               str(form.get("code_challenge", "")), sub=sub)
    sep = "&" if "?" in redirect_uri else "?"
    target = f"{redirect_uri}{sep}code={quote_plus(code)}"
    if form.get("state"):
        target += f"&state={quote_plus(str(form.get('state')))}"
    return RedirectResponse(target, status_code=302)


@app.post("/token")
async def oauth_token(request: Request):
    form = await request.form()
    grant = str(form.get("grant_type", ""))
    if grant == "authorization_code":
        result = oauth_mod.exchange_code(
            str(form.get("code", "")),
            str(form.get("code_verifier", "")),
            str(form.get("redirect_uri", "")),
        )
    elif grant == "refresh_token":
        rt = str(form.get("refresh_token", ""))
        # Re-check the subject on every refresh. Without this a suspended
        # customer's client keeps refreshing (new 90-day token each time) and is
        # never cut off — revocation would only bound access to the 1h access
        # TTL if we stop RE-MINTING here. Kept in the HTTP layer so oauth.py
        # stays DB-free; `verify` is pure, the status lookup is the only DB hit.
        claims = oauth_mod.verify(rt, "refresh")
        if claims is None or not _subject_still_valid(claims.get("sub", "owner")):
            result = None
        else:
            result = oauth_mod.refresh(rt)
    else:
        return JSONResponse(status_code=400,
                            content={"error": "unsupported_grant_type"})
    if result is None:
        # Generic on purpose: never say which check failed.
        return JSONResponse(status_code=400, content={"error": "invalid_grant"})
    return result


def _authorize_html(client_id: str, redirect_uri: str, state: str,
                    code_challenge: str, error: str = "") -> str:
    note = f'<p class="err">{html_escape(error)}</p>' if error else ""
    return f"""<!doctype html><meta charset="utf-8">
<title>alphatecx — authorize</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:22rem;margin:12vh auto;padding:0 1rem}}
 input{{width:100%;padding:.6rem;font-size:1rem;box-sizing:border-box}}
 button{{margin-top:.8rem;padding:.6rem 1.2rem;font-size:1rem}}
 .err{{color:#b00}}
</style>
<h1>alphatecx</h1>
<p>Authorize this client to read your market data.</p>
{note}
<form method="post" action="/authorize">
 <input type="hidden" name="client_id" value="{html_escape(client_id)}">
 <input type="hidden" name="redirect_uri" value="{html_escape(redirect_uri)}">
 <input type="hidden" name="state" value="{html_escape(state)}">
 <input type="hidden" name="code_challenge" value="{html_escape(code_challenge)}">
 <input type="password" name="password" placeholder="Password" autofocus>
 <button type="submit">Authorize</button>
</form>"""


# ── Billing webhook (Merchant of Record — Lemon Squeezy) ──────────────────
#
# Flips customers.status on subscription events. Authenticated by the HMAC
# signature over the raw body (no URL secret — security.py exempts /billing/*).
# Pass our customer_id as `custom_data` when creating the LS checkout so events
# match; email is the fallback. See mcp_server/api/billing.py.

def _apply_billing(payload: dict) -> int:
    """Resolve the customer from an LS subscription event and set their status.
    Returns the HTTP status to answer. Unit-testable by patching customers_mod:
    the only I/O is the customer lookup/update.

    The resolution has to CONFIRM the id, not just read it. `custom_data` is
    whatever was attached at checkout, so an id that no longer exists (or never
    did) used to skip the email fallback, update zero rows, and return 500 —
    which Lemon Squeezy retries forever, while the customer the email would have
    matched is never activated. An id we cannot confirm is treated as no id.
    """
    mapping = billing_mod.event_to_status(payload)
    if mapping is None:
        return 200  # not a subscription-status event — ack so LS stops retrying
    customer_id, email, status = mapping
    try:
        customer = customers_mod.get(customer_id) if customer_id else None
        if customer is None and email:
            customer = customers_mod.get_by_email(email)
    except customers_mod.LookupUnavailable:
        # Transient: 500 so LS retries, unlike the permanent "unknown" case.
        log.warning("billing event deferred — customer store unreachable")
        return 500
    if customer is None:
        log.warning("billing event for an unknown customer "
                    "(custom_data id=%s, email=%s)", customer_id, email)
        return 200  # nothing to act on; ack rather than trigger endless retries
    # 500 on a failed write so Lemon Squeezy retries; 200 on a real update.
    return 200 if customers_mod.set_status(customer["id"], status) else 500


@app.post("/billing/lemonsqueezy")
async def billing_lemonsqueezy(request: Request):
    raw = await request.body()
    secret = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")
    if not billing_mod.verify_signature(raw, request.headers.get("x-signature", ""), secret):
        return JSONResponse(status_code=401, content={"error": "invalid_signature"})
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"error": "invalid_json"})
    code = _apply_billing(payload)
    return JSONResponse(status_code=code, content={"ok": code == 200})


@app.get("/g/{token}/")
def graph_index(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_viewer_html()


@app.get("/h/{token}/")
def home(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_home_html(token)


@app.get("/t/{token}/")
def tickers(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_tickers_html(token)


@app.get("/g/{token}/data.json")
def graph_data(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_snapshot_json()


@app.get("/g/{token}/graph.png")
def graph_png(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_graph_png()


@app.post("/g/{token}/classify")
async def graph_classify(token: str, request: Request):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid json"})
    return graph_view.classify_ticker(payload)


@app.post("/t/{token}/folders")
async def ticker_folders(token: str, request: Request):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid json"})
    return graph_view.update_ticker_folders(payload)


# ── Console ────────────────────────────────────────────────────────────────
#
# Every web surface now hangs off /d/<token>/ behind one navigation frame. They
# used to be five unrelated documents at three prefixes (/d/, /g/, /t/) with no
# links between them, so using any of them meant already knowing its URL. The
# old prefixes still resolve — bookmarks and the Telegram bot's links keep
# working — but nothing new should be added there.
#
# Nav links are relative, which is what lets a static file generated hours
# earlier by the harvester (which never sees the bearer token) link correctly
# once served under this prefix.

@app.get("/d/{token}/")
def console_overview(token: str):
    """Console home: pipeline health plus every surface, the page that was missing."""
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return HTMLResponse(console_pages.overview_html(graph_view.ticker_page_count()))


@app.get("/d/{token}/market")
def console_market(token: str):
    """Today's risk light with every check, threshold and input explained."""
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return HTMLResponse(console_pages.market_html())


@app.get("/d/{token}/system")
def console_system(token: str):
    """How the pipeline works, generated from the live tool registry."""
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    names = [t.name for t in mcp._tool_manager.list_tools()]
    return HTMLResponse(console_pages.system_map_html(names))


@app.get("/d/{token}/flow")
def console_flow(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_dashboard_html(nav="flow")


@app.get("/d/{token}/graph")
def console_graph(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_viewer_html(nav="graph")


@app.get("/d/{token}/tickers")
def console_tickers(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_tickers_html(token, nav="tickers")


@app.get("/d/{token}/home")
def dashboard_home(token: str):
    """Superseded by the console overview at /d/<token>/. Kept for old links."""
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return RedirectResponse(f"/d/{token}/", status_code=307)


@app.get("/d/{token}/dashboard.css")
def dashboard_css(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_dashboard_css()


@app.get("/d/{token}/dashboard.js")
def dashboard_js(token: str):
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_dashboard_js()


@app.get("/d/{token}/t/{ticker}")
def ticker_page(token: str, ticker: str):
    """Per-ticker analytical detail page (candlestick + flow + RS + thesis + news).

    Pages are pre-rendered nightly by `python -m src.dashboard.build_ticker_pages`
    and read from mcp_server/api/static/ticker/{ticker}.html. Same auth as /d/.
    """
    if not token_matches(token, CONSOLE_TOKEN):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return graph_view.get_ticker_page(ticker)


if not MCP_BEARER_TOKEN:
    raise RuntimeError(
        "MCP_BEARER_TOKEN is not set. Refusing to start with no auth — "
        "the URL-as-secret mount path would be empty and the auth gate "
        "would silently 404 every request."
    )

if not oauth_mod.SIGNING_KEY:
    # Warn rather than refuse: a missing OAuth key only costs the cloud-connector
    # surface, whereas MCP_BEARER_TOKEN above is fatal because an empty one would
    # 404 everything. URL-as-secret keeps working here.
    print("WARNING: OAUTH_SIGNING_KEY is not set — bare /mcp will 401 every "
          "request and cloud connectors (mobile) cannot authenticate. "
          "URL-as-secret at /mcp/<token>/ is unaffected.")

# Order matters: the token mount is the more specific prefix and must be
# registered first, or the bare /mcp mount below swallows /mcp/<token>/ and
# the URL-as-secret path starts demanding a bearer header — which would kill
# Claude Code and the Desktop bridge.
# ── Tier enforcement ──────────────────────────────────────────────────────
#
# Applied by wrapping every registered tool in ONE pass rather than putting a
# decorator on 49 handlers. A decorator you must remember to add is a decorator
# someone will forget -- the same failure that let sc_capabilities drift to 33
# of 48. Here a tool cannot escape the gate by omission; the only way to be
# unguarded is to not be registered at all.
#
# Owner traffic bypasses it, exactly as it bypasses metering: the URL-secret and
# OAUTH_PASSWORD paths resolve to OWNER_SUBJECT, and gating the operator out of
# their own server would be an outage, not a policy.
def _install_tier_gate() -> None:
    for name, tool in mcp._tool_manager._tools.items():
        tool.fn = _tier_guarded(name, tool.fn, tool.is_async)


def _tier_guarded(name, fn, is_async):
    """Wrap one tool handler with the entitlement check.

    Refusal is a normal return value, not an exception: FastMCP would render a
    raise as a tool error, which reads to the model as "this broke" and invites
    a retry. A `_locked` payload reads as "this is not yours yet" and carries
    the upgrade path.
    """
    def _denial():
        plan = current_plan.get()
        cust = current_customer.get()
        if cust is None or cust == OWNER_SUBJECT:
            return None                     # owner / unauthenticated URL-secret
        if tiers_mod.allows(plan, name):
            return None
        return tiers_mod.refusal(name, plan)

    if is_async:
        @wraps(fn)
        async def _async_guard(*args, **kwargs):
            denial = _denial()
            return denial if denial is not None else await fn(*args, **kwargs)
        return _async_guard

    @wraps(fn)
    def _sync_guard(*args, **kwargs):
        denial = _denial()
        return denial if denial is not None else fn(*args, **kwargs)
    return _sync_guard


_install_tier_gate()


app.mount(f"/mcp/{MCP_BEARER_TOKEN}", mcp_app)

# Same app object mounted twice, deliberately: FastMCP holds one session
# manager and `lifespan` runs it once, so building a second
# `mcp.streamable_http_app()` would leave the second one un-run.
app.mount("/mcp", mcp_app)
