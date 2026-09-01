"""Investor personas and the position-risk engine.

The load-bearing tests here are the SAFETY ones. The aggressive persona is the
one a determined user pushes toward "just tell me to buy", so the properties
that keep it defensible are pinned in code rather than trusted to prose:
every persona refuses to issue an instruction, and the aggressive one is
required to carry a quantified downside.

The arithmetic tests matter for a different reason: a wrong position size is
worse than no position size, because it is confidently wrong and someone sizes
real money on it.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")

from mcp_server.api import personas, position_risk  # noqa: E402


class TestPersonasAreTheProfiles:
    def test_persona_keys_match_the_valid_risk_profiles_exactly(self):
        """A persona set that drifts from VALID_RISK is a second list of the
        same thing — the failure sc_capabilities already demonstrated."""
        from mcp_server.api import customers
        assert set(personas.PERSONAS) == set(customers.VALID_RISK)

    def test_index_risk_guidance_is_generated_not_hand_copied(self):
        import index
        for profile in personas.PERSONAS:
            assert index._RISK_GUIDANCE[profile] == personas.guidance(profile)

    def test_unknown_profile_gets_no_persona_rather_than_a_default(self):
        """Inventing a default would silently pick a risk appetite for the user."""
        assert personas.guidance("nonsense") == ""
        assert personas.guidance(None) == ""
        assert personas.describe("nonsense") is None


class TestPersonaSafetyInvariants:
    @pytest.mark.parametrize("profile", sorted(personas.PERSONAS))
    def test_every_persona_carries_the_no_instruction_boundary(self, profile):
        g = personas.guidance(profile).lower()
        assert "never tell the user to buy, sell or hold" in g, profile

    def test_the_aggressive_persona_must_quantify_its_downside(self):
        """The whole basis on which a riskier persona is defensible."""
        g = personas.guidance(personas.AGGRESSIVE).lower()
        assert "risk_estimate" in g
        assert "unquantified" in g

    def test_the_aggressive_persona_leads_with_the_stop_not_the_upside(self):
        leads = personas.PERSONAS[personas.AGGRESSIVE]["leads_with"]
        assert "stop" in leads[0].lower(), (
            "the first thing the Opportunist leads with must be the exit"
        )

    def test_the_aggressive_persona_refuses_to_imply_odds(self):
        refuses = " ".join(personas.PERSONAS[personas.AGGRESSIVE]["refuses"]).lower()
        assert "probability" in refuses
        assert "limit-down" in refuses

    def test_no_persona_lists_a_tool_that_does_not_exist(self):
        """A persona telling the model to reach for a tool that was renamed
        sends it into a dead end on every conversation."""
        import index
        registered = set(index.mcp._tool_manager._tools)
        for key, p in personas.PERSONAS.items():
            unknown = [t for t in p["reaches_for"] if t not in registered]
            assert not unknown, f"{key} references non-existent tools: {unknown}"

    def test_conservative_risk_default_is_smaller_than_aggressive(self):
        assert (personas.PERSONAS[personas.CONSERVATIVE]["default_risk_pct"]
                < personas.PERSONAS[personas.AGGRESSIVE]["default_risk_pct"])


class TestPositionSizing:
    def test_the_core_arithmetic(self):
        """1% of 1,000,000 = 10,000 risked; entry 100, stop 94 -> 6/share
        -> 1,666.67 shares -> 1.667 lots -> 1 tradeable lot."""
        r = position_risk.position_size(1_000_000, 1, 100, 94)
        assert r["risk_budget_twd"] == 10_000
        assert r["risk_per_share_twd"] == 6
        assert r["shares"] == pytest.approx(1666.7, abs=0.1)
        assert r["lots_floor"] == 1
        assert r["actual_risk_twd"] == 6_000

    def test_lots_round_down_so_the_budget_is_never_exceeded(self):
        """Rounding up would silently breach the one number the caller
        asked to control."""
        r = position_risk.position_size(1_000_000, 1, 100, 94)
        assert r["actual_risk_twd"] <= r["risk_budget_twd"]

    def test_stop_at_or_above_entry_is_rejected(self):
        assert "error" in position_risk.position_size(1_000_000, 1, 100, 100)
        assert "error" in position_risk.position_size(1_000_000, 1, 100, 105)

    def test_non_positive_inputs_are_rejected_not_clamped(self):
        for bad in ({"account_value": 0}, {"risk_pct": 0}, {"entry": -5}):
            kwargs = {"account_value": 1_000_000, "risk_pct": 1,
                      "entry": 100, "stop": 94, **bad}
            assert "error" in position_risk.position_size(**kwargs), bad

    def test_a_tighter_stop_buys_a_bigger_position_for_the_same_risk(self):
        wide = position_risk.position_size(1_000_000, 1, 100, 90)
        tight = position_risk.position_size(1_000_000, 1, 100, 98)
        assert tight["shares"] > wide["shares"]
        assert tight["risk_budget_twd"] == wide["risk_budget_twd"]


class TestAtrStop:
    def test_two_atr_below_close(self):
        assert position_risk.atr_stop(100, 3) == 94.0

    def test_missing_or_zero_atr_yields_no_stop(self):
        assert position_risk.atr_stop(100, None) is None
        assert position_risk.atr_stop(100, 0) is None

    def test_a_stop_that_would_land_at_or_below_zero_is_none(self):
        """A stop that cannot be reached is not a stop. Naive arithmetic
        produces one for a low-priced name with a large ATR."""
        assert position_risk.atr_stop(5, 4) is None


class TestLimitDownRisk:
    def test_stop_inside_the_band_can_fill_on_an_ordinary_bad_day(self):
        r = position_risk.limit_down_gap_risk(100, 94)
        assert r["limit_down_price"] == 90.0
        assert r["stop_inside_daily_band"] is True

    def test_stop_beyond_one_daily_limit_is_gapped_through(self):
        """The case that matters: the stop protects nothing on a limit-down."""
        r = position_risk.limit_down_gap_risk(100, 85)
        assert r["stop_inside_daily_band"] is False
        assert "protects nothing" in r["explanation"]

    def test_loss_in_twd_when_size_is_known(self):
        r = position_risk.limit_down_gap_risk(100, 94, account_value=1_000_000, lots=5)
        assert r["one_limit_down_loss_twd"] == 50_000     # 5,000 sh x 100 x 10%
        assert r["one_limit_down_loss_pct_of_account"] == 5.0


class TestLiquidity:
    def test_small_position_exits_same_day(self):
        r = position_risk.liquidity_to_exit(1, 2_000_000)
        assert r["sessions_to_exit"] < 1
        assert "same-day" in r["verdict"]

    def test_large_position_needs_multiple_sessions(self):
        r = position_risk.liquidity_to_exit(100, 200_000)
        assert r["sessions_to_exit"] > 1
        assert "multiple sessions" in r["verdict"]


class TestEstimateDegradesBySection:
    """Silence about an uncomputed risk reads as 'no risk'. Everything that
    could not be computed has to be NAMED."""

    def test_full_inputs_give_every_section(self):
        r = position_risk.estimate(entry=100, atr=3, account_value=1_000_000,
                                   risk_pct=1, avg_daily_volume_shares=2_000_000)
        assert r["stop"] == 94.0 and r["stop_basis"] == "atr_x2.0"
        assert "sizing" in r and "limit_down_risk" in r and "liquidity" in r
        assert "missing" not in r

    def test_no_account_value_still_gives_stop_and_limit_down(self):
        r = position_risk.estimate(entry=100, atr=3)
        assert r["stop"] == 94.0
        assert "limit_down_risk" in r
        assert any("sizing" in m for m in r["missing"])

    def test_no_volume_names_liquidity_as_unknown_not_fine(self):
        r = position_risk.estimate(entry=100, atr=3, account_value=1_000_000,
                                   risk_pct=1)
        assert any("liquidity" in m and "UNKNOWN" in m for m in r["missing"])

    def test_no_stop_and_no_atr_refuses_to_size_anything(self):
        r = position_risk.estimate(entry=100, account_value=1_000_000, risk_pct=1)
        assert r["stop"] is None
        assert "sizing" not in r
        assert any("stop" in m for m in r["missing"])

    def test_explicit_stop_beats_the_atr_derived_one(self):
        r = position_risk.estimate(entry=100, atr=3, stop=97)
        assert r["stop"] == 97.0 and r["stop_basis"] == "explicit"

    def test_assumptions_are_always_stated(self):
        """A risk number whose assumptions are hidden is not auditable."""
        r = position_risk.estimate(entry=100, atr=3)
        assert r["assumptions"]["daily_limit_pct"] == 10.0
        assert r["assumptions"]["atr_stop_mult"] == 2.0


class TestToolSurface:
    def test_risk_estimate_says_it_does_not_forecast(self):
        import index
        # via the registry, not the module attribute: @mcp.tool() returns the
        # plain function, so index.risk_estimate has no .fn — and the registry
        # is what the model actually reads.
        doc = index.mcp._tool_manager._tools["risk_estimate"].description.lower()
        assert "does not forecast" in doc or "not forecast" in doc
        assert "probability of profit" in doc

    def test_risk_estimate_response_is_stamped_and_names_its_source(self):
        import index
        out = index.mcp._tool_manager._tools["risk_estimate"].fn(entry=100, atr=3)
        assert out["_disclaimer"]
        assert "no market data read" in out["_source"]

    def test_investing_personas_lists_both_characters(self):
        import index
        out = index.mcp._tool_manager._tools["investing_personas"].fn()
        assert out["personas"]["conservative"]["name"] == "The Steward"
        assert out["personas"]["aggressive"]["name"] == "The Opportunist"

    def test_investing_personas_rejects_an_unknown_profile(self):
        import index
        out = index.mcp._tool_manager._tools["investing_personas"].fn(profile="yolo")
        assert "error" in out and "options" in out
