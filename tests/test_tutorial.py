"""docs/TUTORIAL.md must not drift from the system it documents.

A stale tutorial is worse than a missing one: a confidently wrong instruction
costs more than an absent one, and nothing else in CI would notice. So the file
is generated, and this suite is the tripwire —

  * the committed file must match a fresh render, and
  * every registered tool must land in exactly one section, so a new tool cannot
    silently fall off the end while every other check stays green.

The second is the one that actually earns its keep. `test_capabilities.py`
already stops a tool going missing from `sc_capabilities`; without the grouping
assertion here, a tool could be correctly registered, correctly tiered,
correctly advertised — and still invisible to any human reading the docs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TUTORIAL = ROOT / "docs" / "TUTORIAL.md"
BUILDER = ROOT / "scripts" / "build_tutorial.py"


@pytest.fixture(scope="module")
def builder():
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_tutorial
    return build_tutorial


class TestTutorialIsCurrent:
    def test_the_committed_file_matches_a_fresh_render(self, builder):
        """The whole point. Adding a tool turns this red until the page is
        rebuilt with `python scripts/build_tutorial.py`."""
        assert TUTORIAL.exists(), "docs/TUTORIAL.md is missing — run the builder"
        assert TUTORIAL.read_text() == builder.render(), (
            "docs/TUTORIAL.md is stale. Run: python scripts/build_tutorial.py"
        )

    def test_the_check_flag_agrees(self):
        """The same guard has to work from the command line, or a contributor
        cannot fix the failure above without reading this test."""
        result = subprocess.run(
            [sys.executable, str(BUILDER), "--check"],
            capture_output=True, text=True, cwd=ROOT,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_it_says_it_is_generated(self):
        head = TUTORIAL.read_text()[:400]
        assert "GENERATED FILE" in head
        assert "build_tutorial.py" in head


class TestEveryToolIsDocumented:
    def _registry(self):
        import os
        os.environ.setdefault("MCP_BEARER_TOKEN", "testtoken")
        import index
        return set(index.mcp._tool_manager._tools)

    def test_every_registered_tool_appears_in_exactly_one_section(self, builder):
        registry = self._registry()
        seen: dict[str, list[str]] = {}
        for title, _blurb, members in builder.GROUPS:
            for name in members:
                seen.setdefault(name, []).append(title)

        missing = sorted(registry - set(seen))
        assert not missing, (
            f"tools registered but absent from the tutorial: {missing}. "
            f"Add them to GROUPS in scripts/build_tutorial.py."
        )
        duplicated = {k: v for k, v in seen.items() if len(v) > 1}
        assert not duplicated, f"tools listed in two sections: {duplicated}"

    def test_no_section_lists_a_tool_that_does_not_exist(self, builder):
        """A tutorial pointing at a renamed tool sends the reader nowhere."""
        registry = self._registry()
        listed = {n for _t, _b, members in builder.GROUPS for n in members}
        assert not (listed - registry), (
            f"tutorial names tools that are not registered: {sorted(listed - registry)}"
        )

    def test_every_tool_row_carries_a_real_purpose(self, builder):
        """`sc_capabilities` is the source; a tool missing from it would render
        as '(not registered)' rather than failing loudly."""
        body = TUTORIAL.read_text()
        assert "_(not registered)_" not in body

    def test_group_lookup_is_total_over_the_registry(self, builder):
        for tool in self._registry():
            assert builder.group_of(tool) is not None, tool


class TestGeneratedContentTracksTheCode:
    """Spot-checks that the generated sections really read from the modules
    rather than from prose someone typed once."""

    def test_the_persona_table_names_the_live_personas(self, builder):
        from mcp_server.api import personas
        body = TUTORIAL.read_text()
        for p in personas.PERSONAS.values():
            assert p["name"] in body, p["name"]

    def test_the_macro_table_marks_the_asian_peers_as_same_session(self, builder):
        """The timing distinction has to survive into the docs, or a reader
        learns the wrong thing about KOSPI."""
        body = TUTORIAL.read_text()
        assert "trades alongside Taipei" in body
        for label in ("KOSPI", "Nikkei", "Hang Seng", "Shanghai"):
            assert label in body, label

    def test_out_of_reach_strategies_are_shown_as_such(self, builder):
        from mcp_server.api import strategies
        body = TUTORIAL.read_text()
        assert "out of reach" in body
        for key in strategies.by_status(strategies.OUT_OF_REACH):
            assert strategies.STRATEGIES[key]["name"] in body

    def test_the_backtest_section_leads_with_baseline_not_hit_rate(self):
        """The single most misleading number in the system. If the tutorial
        teaches the hit rate first, it teaches the mistake."""
        body = TUTORIAL.read_text()
        assert "Never quote a bare\nhit rate" in body or "never quote a bare" in body.lower()
        assert "net_edge_vs_baseline_pct" in body

    def test_the_non_advice_boundary_is_stated_near_the_top(self):
        head = TUTORIAL.read_text()[:2000]
        assert "not" in head.lower() and "advice" in head.lower()

    def test_free_tool_count_matches_the_tier_table(self, builder):
        from mcp_server.api import tiers
        n_free = sum(1 for t in tiers.TOOL_TIERS.values() if t == tiers.FREE)
        assert f"{n_free} are free" in TUTORIAL.read_text()
