"""Plan tiers: which tools a customer's plan entitles them to call.

Policy lives here in code, not in the database, deliberately. Entitlement is a
security-relevant rule: a typo in a DB row would silently open a paid tool with
no diff, no review and no CI. Assignment stays in data — which plan a customer
is *on* is `customers.plan`, editable per customer without a deploy. Policy in
code, assignment in data.

Refusal is **show-and-refuse**, not hide. A locked tool stays listed and returns
a structured `_locked` payload naming the plan that would unlock it, so the
model can say "that needs Pro" instead of hitting a dead end. Hiding would also
mean `sc_capabilities` and the live registry disagree, which is exactly the
drift `tests/test_capabilities.py` exists to prevent.
"""

from __future__ import annotations

# Ordered weakest to strongest. An unknown plan is treated as FREE (fail
# closed): a typo in a customer row must not hand out the paid surface.
FREE = "free"
PRO = "pro"
PRIVATE = "private"

RANK: dict[str, int] = {FREE: 0, PRO: 1, PRIVATE: 2}

# `private` is the plan every existing customer was provisioned with
# (scripts/provision_customer.py defaults to it), so it must mean full access or
# this change would retroactively downgrade them. New commercial plans are FREE
# and PRO; PRIVATE stays the internal/operator tier.
FULL_ACCESS = PRIVATE

# Monthly call ceilings by plan. `None` = uncapped.
#
# These are DEFAULTS. `customers.monthly_quota` still wins when set, so a
# one-off deal needs no code change. Note PRIVATE is None on purpose: NULL quota
# already meant "unlimited" and the operator's own row relies on it, so the
# default must preserve that exactly rather than silently capping it.
PLAN_DEFAULT_QUOTA: dict[str, int | None] = {
    FREE: 200,
    PRO: 5000,
    PRIVATE: None,
}

# Every registered tool, exactly once. `tests/test_tiers.py` asserts this map
# and the live FastMCP registry match in BOTH directions -- a new tool with no
# entry fails the suite rather than defaulting to free or to locked. The
# hand-maintained `sc_capabilities` list drifted to 33 of 48 before an
# equivalent test existed; this is a second list of the same 49 names and would
# rot the same way.
#
# Split rationale: FREE is everything needed to look up and understand ONE name
# -- the acquisition surface, and the whole documented beginner path
# (ticker_lookup -> beginner_stock_card -> q_valuation / sc_ticker_momentum)
# works on it. PRO is the market-wide screens, the quant suite and Risk Guard:
# the tools that find ideas rather than explain one you already have.
TOOL_TIERS: dict[str, str] = {
    # ── free: orientation, identity, single-name lookup ──────────────────
    "start_here": FREE,
    "sc_capabilities": FREE,
    "investing_principles": FREE,
    "investing_personas": FREE,
    "systematic_strategies": FREE,
    "session_state": FREE,
    "sc_data_status": FREE,
    "my_profile": FREE,
    "set_my_risk_profile": FREE,
    "ticker_lookup": FREE,
    "quote": FREE,
    "price_history": FREE,
    "beginner_stock_card": FREE,
    "dividend_calendar": FREE,
    "q_valuation": FREE,
    "q_indicators": FREE,
    "sc_supply_chain_map": FREE,
    "sc_ticker_momentum": FREE,
    "sc_sector_momentum": FREE,
    "n_recent": FREE,
    "n_for_ticker": FREE,
    "n_source_status": FREE,
    "u_universe": FREE,
    # Watchlist writes are free on purpose: they are the retention hook, and a
    # watchlist you cannot build makes the paid alerts pointless to upgrade to.
    "w_add": FREE,
    "w_remove": FREE,
    "w_watchlist": FREE,

    # ── pro: market-wide discovery, quant, risk ──────────────────────────
    "flow_leaders_scan": PRO,
    "momentum_leaders_scan": PRO,
    "market_flow_screener": PRO,
    "sc_accumulation_screen": PRO,
    "scan_limit_board": PRO,
    "sc_compare_nodes": PRO,
    "raw_flow_history": PRO,
    "q_backtest": PRO,
    "q_backtest_compound": PRO,
    "q_cointegration_pair": PRO,
    "q_factor_alpha": PRO,
    "q_factor_screen": PRO,
    "q_index_history": PRO,
    "q_macro": PRO,
    "risk_estimate": PRO,
    "q_lead_lag": PRO,
    "q_pca_decompose": PRO,
    "q_quality_score": PRO,
    "q_regime": PRO,
    "q_screener": PRO,
    "rg_alerts": PRO,
    "rg_checklist": PRO,
    "rg_journal_add": PRO,
    "rg_positions": PRO,
    "rg_status": PRO,
    "d_recent": PRO,
    "d_for_date": PRO,
}


def plan_rank(plan: str | None) -> int:
    """Rank of a plan, defaulting to FREE for anything unrecognised."""
    return RANK.get((plan or "").strip().lower(), RANK[FREE])


def tier_of(tool: str) -> str:
    """Tier a tool requires. Unknown tools are PRO, not FREE.

    An unmapped tool means someone added one without touching this file. The
    test catches that in CI, but if it ever reaches production the safe answer
    is to withhold it, not to give it away.
    """
    return TOOL_TIERS.get(tool, PRO)


def allows(plan: str | None, tool: str) -> bool:
    return plan_rank(plan) >= RANK[tier_of(tool)]


def locked_for(plan: str | None) -> list[str]:
    """Tools this plan cannot call, sorted. Used by sc_capabilities so the model
    is told what it cannot reach instead of discovering it by being refused."""
    return sorted(t for t in TOOL_TIERS if not allows(plan, t))


def effective_quota(customer: dict | None) -> int | None:
    """Monthly ceiling for a customer: explicit column first, else plan default.

    `None` means uncapped. The column winning is what lets a one-off deal be a
    row edit rather than a deploy.
    """
    if not customer:
        return None
    explicit = customer.get("monthly_quota")
    if explicit is not None:
        return explicit
    return PLAN_DEFAULT_QUOTA.get((customer.get("plan") or "").strip().lower())


def refusal(tool: str, plan: str | None) -> dict:
    """The payload a locked tool returns instead of doing its work.

    Shaped as data the model can explain, not an exception: it names the tool,
    the plan in force and the plan that would unlock it. `_locked` is the flag
    to branch on.
    """
    needed = tier_of(tool)
    return {
        "_locked": True,
        "tool": tool,
        "your_plan": (plan or FREE),
        "requires_plan": needed,
        "message": (
            f"`{tool}` is part of the {needed} tier. Your plan is "
            f"{plan or FREE}. Tell the user this is a paid feature and what it "
            "would give them — do not retry the call, and do not attempt to "
            "reconstruct its output from other tools."
        ),
    }
