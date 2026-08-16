"""Plan tiers: policy, and the invariants that keep it honest.

The load-bearing test here is the registry-coverage one. `TOOL_TIERS` is a
second list of all 49 tool names, and this repo has already watched exactly that
shape rot once: the hand-maintained `sc_capabilities` map drifted to 33 of 48
before a test asserted both directions. A tier map that drifts is worse than a
stale doc — an unmapped tool is either given away or withheld silently.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")

from mcp_server.api import tiers  # noqa: E402


class TestRegistryCoverage:
    def test_every_registered_tool_has_exactly_one_tier(self):
        import index

        registered = set(index.mcp._tool_manager._tools)
        mapped = set(tiers.TOOL_TIERS)

        assert not (registered - mapped), (
            "registered tools missing from TOOL_TIERS: "
            f"{sorted(registered - mapped)}. Add them to mcp_server/api/tiers.py "
            "— an unmapped tool defaults to PRO and is silently withheld."
        )
        assert not (mapped - registered), (
            "TOOL_TIERS names tools that are not registered: "
            f"{sorted(mapped - registered)}. Stale entries mean the map is "
            "describing a server that no longer exists."
        )

    def test_every_tier_value_is_a_known_tier(self):
        unknown = {t: v for t, v in tiers.TOOL_TIERS.items() if v not in tiers.RANK}
        assert not unknown, f"tools mapped to an unknown tier: {unknown}"

    def test_the_documented_beginner_path_works_on_free(self):
        """The server `instructions` tell the model to chain these.

        If any were PRO, the documented onboarding flow would dead-end for the
        exact users it was written for.
        """
        for tool in ("start_here", "ticker_lookup", "beginner_stock_card",
                     "q_valuation", "sc_ticker_momentum", "my_profile",
                     "sc_capabilities"):
            assert tiers.allows(tiers.FREE, tool), f"{tool} must be free"


class TestEntitlement:
    def test_free_cannot_reach_pro(self):
        assert not tiers.allows(tiers.FREE, "q_backtest")
        assert not tiers.allows(tiers.FREE, "momentum_leaders_scan")

    def test_pro_reaches_free_and_pro(self):
        assert tiers.allows(tiers.PRO, "quote")
        assert tiers.allows(tiers.PRO, "q_backtest")

    def test_private_reaches_everything(self):
        assert tiers.locked_for(tiers.PRIVATE) == []

    def test_unknown_plan_fails_closed_to_free(self):
        """A typo in customers.plan must not hand out the paid surface."""
        # NB: "Pro " is NOT here — plan_rank strips and lowercases, so that is a
        # tolerated spelling of `pro`, pinned by the next test. Only genuinely
        # unrecognised names must fail closed.
        for plan in ("premium", "", None, "enterprise", "pro-plus"):
            assert not tiers.allows(plan, "q_backtest"), plan

    def test_known_plans_are_case_and_space_tolerant(self):
        assert tiers.allows(" PRO ", "q_backtest")

    def test_unknown_tool_is_withheld_not_given_away(self):
        assert tiers.tier_of("some_new_tool") == tiers.PRO
        assert not tiers.allows(tiers.FREE, "some_new_tool")


class TestEffectiveQuota:
    def test_explicit_column_wins_over_plan_default(self):
        """One-off deals must be a row edit, not a deploy."""
        assert tiers.effective_quota({"plan": "free", "monthly_quota": 20000}) == 20000

    def test_plan_default_applies_when_column_is_null(self):
        assert tiers.effective_quota({"plan": "free", "monthly_quota": None}) == 200
        assert tiers.effective_quota({"plan": "pro", "monthly_quota": None}) == 5000

    def test_private_stays_uncapped(self):
        """NULL quota already meant unlimited and the operator's row relies on
        it. A tier default that capped `private` would be a silent regression
        for the only customer currently provisioned."""
        assert tiers.effective_quota({"plan": "private", "monthly_quota": None}) is None

    def test_unknown_plan_with_null_quota_is_uncapped_not_zero(self):
        """Fail-open on quota, fail-closed on entitlement — deliberately
        opposite. A wrong 0 would lock out a paying customer over a typo;
        withholding a tool is recoverable, a bogus 429 storm is not."""
        assert tiers.effective_quota({"plan": "mystery", "monthly_quota": None}) is None


class TestRefusalPayload:
    def test_refusal_names_the_tool_and_the_upgrade(self):
        r = tiers.refusal("q_backtest", tiers.FREE)
        assert r["_locked"] is True
        assert r["tool"] == "q_backtest"
        assert r["your_plan"] == tiers.FREE
        assert r["requires_plan"] == tiers.PRO

    def test_refusal_tells_the_model_not_to_reconstruct_the_answer(self):
        """Without this the model cheerfully rebuilds a paid screen out of the
        free primitives, which gives the product away one tool call at a time."""
        msg = tiers.refusal("momentum_leaders_scan", tiers.FREE)["message"].lower()
        assert "do not retry" in msg
        assert "reconstruct" in msg


class TestGateWiring:
    """The wrapper is installed over the live registry, so test it there."""

    @pytest.fixture
    def ctx(self):
        import index
        from index import current_customer, current_plan
        c = current_customer.set("cust_x")
        p = current_plan.set(tiers.FREE)
        yield index
        current_customer.reset(c)
        current_plan.reset(p)

    def test_locked_tool_returns_payload_rather_than_raising(self, ctx):
        """A raise renders as a tool error, which reads as "broken" and invites
        a retry. A `_locked` return reads as "not yours yet"."""
        out = ctx.mcp._tool_manager._tools["q_backtest"].fn(ticker_id="2330")
        assert out["_locked"] is True
        assert out["requires_plan"] == tiers.PRO

    def test_owner_bypasses_the_gate(self, ctx):
        """Gating the operator out of their own server is an outage, not policy."""
        from index import current_customer
        current_customer.set(ctx.OWNER_SUBJECT)
        out = ctx.mcp._tool_manager._tools["sc_capabilities"].fn()
        assert out.get("_locked") is not True
        assert out["locked_tools"] == []

    def test_capabilities_reports_locked_set_to_a_free_customer(self, ctx):
        out = ctx.mcp._tool_manager._tools["sc_capabilities"].fn()
        assert out["your_plan"] == tiers.FREE
        assert "q_backtest" in out["locked_tools"]
        assert "quote" not in out["locked_tools"]

    def test_every_tool_is_wrapped(self, ctx):
        """The whole point of gating in one pass is that omission is impossible.

        If a future refactor registers tools after _install_tier_gate() runs,
        those escape silently — this catches that.
        """
        unwrapped = [
            n for n, t in ctx.mcp._tool_manager._tools.items()
            if not getattr(t.fn, "__wrapped__", None)
        ]
        assert not unwrapped, f"tools registered outside the tier gate: {unwrapped}"
