"""Honest backtest statistics (quant/evidence.py) + the look-ahead fix.

The old `q_backtest` reported hit-rate and average forward return. Every defect
these tests pin biased the answer the SAME way — optimistic — which is the
dangerous direction for a tool a persona quotes at a user about their money.

The properties under test, in order of how much damage each prevented:
  1. a rule with no edge over the baseline is REPORTED as having no edge;
  2. costs can flip a gross winner to a net loser, and the verdict says so;
  3. correlated same-day triggers cannot inflate the confidence;
  4. entry price is the next session's close, not the one the signal was
     computed from.
"""

from __future__ import annotations

import pytest

from mcp_server.api.quant import evidence


def _obs(returns, dates=None, tickers=None):
    """Observations on DISTINCT dates unless a test says otherwise — so
    n_effective == n and the verdict under test is the one being exercised
    rather than the small-sample refusal."""
    n = len(returns)
    dates = dates or [
        f"2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}" for i in range(n)
    ]
    tickers = tickers or [f"T{i:04d}" for i in range(n)]
    return [
        {"ticker_id": t, "date": d, "pct_return": r}
        for r, d, t in zip(returns, dates, tickers, strict=True)
    ]


class TestBaselineIsTheHeadline:
    """The single most misleading omission: 'the market went up' reported as
    'my signal works'."""

    def test_a_rule_that_only_matches_the_market_reports_no_edge(self):
        # 60% of triggers win... and 60% of ALL bars won too.
        out = evidence.summarize(
            _obs([1.0] * 60 + [-1.0] * 40),
            baseline={"avg_return_pct": 0.2, "hit_rate_pct": 60.0, "n": 50000},
        )
        assert out["hit_rate_pct"] == 60.0
        assert out["hit_rate_edge_pp"] == 0.0
        assert out["edge_vs_baseline_pct"] == 0.0
        assert "No edge" in out["verdict"]

    def test_edge_is_measured_against_the_baseline_not_against_zero(self):
        out = evidence.summarize(
            _obs([2.0] * 50 + [-1.0] * 50),
            baseline={"avg_return_pct": 0.4, "hit_rate_pct": 52.0, "n": 40000},
        )
        assert out["avg_return_pct"] == 0.5
        assert out["edge_vs_baseline_pct"] == pytest.approx(0.1, abs=1e-9)

    def test_missing_baseline_is_admitted_never_assumed_to_be_zero(self):
        out = evidence.summarize(_obs([3.0] * 40 + [-1.0] * 20))
        assert out["baseline"] is None
        assert out["edge_vs_baseline_pct"] is None
        assert "no baseline" in out["verdict"]


class TestCostsAreSubtractedNotIgnored:
    def test_the_taiwan_round_trip_is_brokerage_both_ways_plus_the_sell_tax(self):
        assert evidence.ROUND_TRIP_COST_PCT == pytest.approx(0.585)

    def test_a_gross_winner_can_be_a_net_loser_and_the_verdict_says_so(self):
        """The 5-day rule averaging +0.4%: profitable-looking, actually losing."""
        out = evidence.summarize(
            _obs([0.4] * 100),
            baseline={"avg_return_pct": 0.0, "hit_rate_pct": 50.0, "n": 40000},
        )
        assert out["avg_return_pct"] == 0.4
        assert out["net_avg_return_pct"] < 0
        assert out["net_edge_vs_baseline_pct"] < 0
        assert "No edge" in out["verdict"]

    def test_a_discounted_brokerage_rate_can_be_supplied(self):
        out = evidence.summarize(_obs([0.4] * 100), cost_pct=0.2)
        assert out["net_avg_return_pct"] == pytest.approx(0.2, abs=1e-9)


class TestCorrelatedTriggersCannotInflateConfidence:
    def test_two_hundred_triggers_on_one_day_are_one_observation(self):
        """Taiwan semis move together. A rule firing across the whole sector on
        one afternoon has seen one market, not two hundred."""
        out = evidence.summarize(_obs([1.0] * 200, dates=["2026-03-02"] * 200))
        assert out["n_observations"] == 200
        assert out["n_effective"] == 1
        assert "not enough to conclude" in out["verdict"]

    def test_the_interval_widens_when_observations_are_clustered(self):
        spread = evidence.summarize(
            _obs([1.0] * 50 + [-1.0] * 50,
                 dates=[f"2026-{m:02d}-{d:02d}" for m in range(1, 11)
                        for d in range(1, 11)])
        )
        clustered = evidence.summarize(
            _obs([1.0] * 50 + [-1.0] * 50, dates=["2026-03-02"] * 50 + ["2026-03-03"] * 50)
        )
        s_lo, s_hi = spread["hit_rate_ci95_pct"]
        c_lo, c_hi = clustered["hit_rate_ci95_pct"]
        assert (c_hi - c_lo) > (s_hi - s_lo), (
            "clustered triggers must produce a WIDER interval, not the same one"
        )

    def test_effective_n_counts_distinct_dates(self):
        assert evidence.effective_sample_size(["a", "a", "b", "c", "c"]) == 3

    def test_a_tiny_effective_sample_beats_every_other_verdict(self):
        """Ordering matters: an impressive edge on 9 independent observations is
        not a weak result, it is an absent one."""
        out = evidence.summarize(
            _obs([50.0] * 9, dates=[f"2026-01-{i + 1:02d}" for i in range(9)]),
            baseline={"avg_return_pct": 0.1, "hit_rate_pct": 50.0, "n": 9000},
        )
        assert out["net_edge_vs_baseline_pct"] > 40      # spectacular...
        assert "not enough to conclude" in out["verdict"]  # ...and still refused


class TestWilsonInterval:
    def test_bounds_stay_inside_zero_to_one_hundred_at_the_extremes(self):
        """Where the normal approximation goes wrong, which is where this tool
        is most likely to be believed."""
        lo, hi = evidence.wilson_interval(10, 10)
        assert 0.0 <= lo <= hi <= 100.0
        lo, hi = evidence.wilson_interval(0, 10)
        assert 0.0 <= lo <= hi <= 100.0

    def test_more_data_narrows_the_interval(self):
        small = evidence.wilson_interval(30, 50)
        large = evidence.wilson_interval(300, 500)
        assert (large[1] - large[0]) < (small[1] - small[0])

    def test_zero_observations_is_maximally_uncertain_not_a_crash(self):
        assert evidence.wilson_interval(0, 0) == (0.0, 100.0)


class TestCaveatsAreAlwaysPresent:
    @pytest.mark.parametrize("obs", [[], [1.0] * 100])
    def test_survivorship_is_named_even_when_it_cannot_be_fixed(self, obs):
        out = evidence.summarize(_obs(obs) if obs else [])
        joined = " ".join(out["caveats"])
        assert "SURVIVORSHIP" in joined
        assert "not corrected" in joined

    def test_in_sample_tuning_is_named(self):
        out = evidence.summarize(_obs([1.0] * 100))
        assert any("IN-SAMPLE" in c for c in out["caveats"])

    def test_slippage_is_named_as_excluded_rather_than_invented(self):
        out = evidence.summarize(_obs([1.0] * 100))
        assert any("Slippage" in c for c in out["caveats"])

    def test_clustering_is_explained_when_it_bites(self):
        out = evidence.summarize(_obs([1.0] * 40, dates=["2026-03-02"] * 40))
        assert any("cluster into" in c for c in out["caveats"])

    def test_no_observations_is_a_clean_answer_not_an_exception(self):
        out = evidence.summarize([])
        assert out["n_observations"] == 0
        assert "nothing to evaluate" in out["verdict"]


class TestEntryTimingIsNotLookAhead:
    """The SQL-level half of the fix. `same_close` buys at the very close the
    signal was computed from — a price nobody can transact at, because the
    signal does not exist until that close is known."""

    def _db(self):
        import os
        os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")
        from mcp_server.api import db_v2
        return db_v2

    def test_next_close_is_the_default(self):
        import inspect
        db_v2 = self._db()
        sig = inspect.signature(db_v2.query_backtest)
        assert sig.parameters["entry"].default == "next_close"
        sig = inspect.signature(db_v2.query_backtest_compound)
        assert sig.parameters["entry"].default == "next_close"

    def test_next_close_entry_leads_by_one_bar_and_shifts_the_exit_with_it(self):
        """Holding period must stay `forward_days`. Leading the entry without
        leading the exit would silently shorten every trade by a day."""
        db_v2 = self._db()
        entry_lead, exit_lead = db_v2._ENTRY_MODES["next_close"]
        assert entry_lead == 1
        assert exit_lead == 1, "exit must shift with entry or the horizon shrinks"

    def test_same_close_is_still_reachable_so_the_bias_can_be_measured(self):
        db_v2 = self._db()
        assert db_v2._ENTRY_MODES["same_close"] == (0, 0)

    def test_an_unknown_entry_mode_is_refused_not_silently_defaulted(self):
        db_v2 = self._db()
        out = db_v2.query_backtest("rsi_14", 30, "below", 5, 365, entry="tomorrow")
        assert "error" in out and "entry must be one of" in out["error"]

    def test_entry_price_expression_is_a_literal_never_caller_text(self):
        """`entry` reaches SQL only through the _ENTRY_MODES table; the value
        interpolated is an int from that table, and it still binds through a
        placeholder."""
        db_v2 = self._db()
        assert db_v2._entry_expr(0) == "close"
        assert "%s" in db_v2._entry_expr(1)
        for mode, (lead, _) in db_v2._ENTRY_MODES.items():
            assert isinstance(lead, int), mode


class TestSystematicStrategies:
    """The catalogue's value is in what it REFUSES to claim."""

    def _mod(self):
        from mcp_server.api import strategies
        return strategies

    def test_the_unreproducible_funds_are_marked_out_of_reach(self):
        """A moving-average crossover wearing Renaissance's name would be a
        worse answer than 'that cannot be done here'."""
        s = self._mod()
        for key in ("high_frequency_market_making", "ml_alpha_ensemble"):
            assert s.STRATEGIES[key]["status"] == s.OUT_OF_REACH

    def test_out_of_reach_entries_offer_no_tools_to_fake_it_with(self):
        s = self._mod()
        for key in s.by_status(s.OUT_OF_REACH):
            assert s.STRATEGIES[key]["tools"] == [], (
                f"{key} is unreachable but lists tools — that invites a "
                f"degraded imitation under a famous name"
            )

    def test_every_strategy_states_an_honest_limit(self):
        s = self._mod()
        for key, entry in s.STRATEGIES.items():
            assert entry.get("honest_limit"), f"{key} has no stated limit"
            assert entry["status"] in (s.AVAILABLE, s.BUILDABLE, s.OUT_OF_REACH)
            assert entry.get("practitioners"), key

    def test_available_strategies_name_tools_that_actually_exist(self):
        """A strategy pointing at a renamed tool dead-ends the model."""
        import os
        os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")
        import index
        s = self._mod()
        registered = set(index.mcp._tool_manager._tools)
        for key, entry in s.STRATEGIES.items():
            for tool in entry["tools"]:
                assert tool in registered, f"{key} names missing tool {tool}"

    def test_risk_discipline_is_available_because_it_is_the_transferable_one(self):
        """Millennium's edge is cutting losers mechanically, not forecasting —
        and it is the one item on the list this system already implements."""
        s = self._mod()
        assert s.STRATEGIES["pod_risk_discipline"]["status"] == s.AVAILABLE

    def test_unknown_keys_are_refused_not_guessed(self):
        s = self._mod()
        assert s.describe("medallion_secret_sauce") is None
        assert s.by_status("nonsense") == []

    def test_quant_principles_each_name_what_enforces_them(self):
        s = self._mod()
        for p in s.QUANT_PRINCIPLES:
            assert p["enforced_by"], p["principle"]

    def test_the_costs_principle_matches_the_number_actually_used(self):
        """A principle quoting a cost the code does not apply is decoration."""
        from mcp_server.api.quant import evidence
        s = self._mod()
        cost = next(p for p in s.QUANT_PRINCIPLES if "Costs" in p["principle"])
        assert str(evidence.ROUND_TRIP_COST_PCT) in cost["detail"]

    def test_capacity_decay_admits_nothing_enforces_it(self):
        """Claiming enforcement for a principle no code implements would be the
        exact dishonesty this catalogue exists to avoid."""
        s = self._mod()
        cap = next(p for p in s.QUANT_PRINCIPLES if "Capacity" in p["principle"])
        assert "nothing" in cap["enforced_by"]
