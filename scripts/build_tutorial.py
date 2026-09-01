"""Generate docs/TUTORIAL.md from the live system.

WHY GENERATED. A hand-written tutorial for a system that gains a tool most
weeks is worse than no tutorial: it goes stale silently, and a confidently
wrong instruction costs more than a missing one. Everything here that CAN drift
is read from the running code instead of retyped —

    tool names + purposes   sc_capabilities() (itself pinned to the FastMCP
                            registry by tests/test_capabilities.py, so this
                            inherits that guarantee)
    which plan unlocks what tiers.TOOL_TIERS
    the personas            personas.PERSONAS
    the strategy catalogue  strategies.STRATEGIES
    the macro series        src.harvester.macro.SERIES_META

— and `tests/test_tutorial.py` regenerates it and fails if the committed file
differs. Adding a tool therefore turns CI red until the tutorial is rebuilt,
which is the same mechanism that stopped `sc_capabilities` drifting to 33 of 48.

The prose lives in this file rather than in a separate template so there is one
source and no merge step. Edit the narrative HERE, run the script, commit both.

Regenerate:  python scripts/build_tutorial.py
Check only:  python scripts/build_tutorial.py --check
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("MCP_BEARER_TOKEN", "tutorial-build")

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "TUTORIAL.md"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp_server" / "api"))

# Groups, in reading order. A tool lands in the FIRST group whose predicate
# matches, so order is meaningful. `tests/test_tutorial.py` asserts every
# registered tool lands in exactly one group — without that, a new tool would
# quietly fall off the end of the tutorial while every other check stayed green.
GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "Start here",
        "Orientation, your profile, and what the system currently knows.",
        ("start_here", "sc_capabilities", "session_state", "sc_data_status",
         "my_profile", "set_my_risk_profile", "investing_principles",
         "investing_personas", "systematic_strategies"),
    ),
    (
        "Look up one company",
        "The whole beginner path. Everything here is free.",
        ("ticker_lookup", "quote", "price_history", "beginner_stock_card",
         "dividend_calendar", "q_valuation", "q_indicators"),
    ),
    (
        "Supply chain",
        "Who sells to whom, and where the money is moving inside the chain.",
        ("sc_supply_chain_map", "sc_ticker_momentum", "sc_sector_momentum",
         "sc_compare_nodes", "sc_accumulation_screen"),
    ),
    (
        "Find ideas across the market",
        "Screens over the whole market rather than one name you already have.",
        ("flow_leaders_scan", "momentum_leaders_scan", "market_flow_screener",
         "scan_limit_board", "raw_flow_history", "u_universe"),
    ),
    (
        "Quant and evidence",
        "Test an idea before believing it. Read `q_backtest`'s caveats.",
        ("q_backtest", "q_backtest_compound", "q_factor_alpha", "q_factor_screen",
         "q_quality_score", "q_screener", "q_regime", "q_lead_lag",
         "q_cointegration_pair", "q_pca_decompose", "q_index_history", "q_macro"),
    ),
    (
        "Risk",
        "Sizing before entry, and the stop discipline after it.",
        ("risk_estimate", "rg_status", "rg_positions", "rg_alerts",
         "rg_checklist", "rg_journal_add"),
    ),
    (
        "News and digests",
        "What was published, and what the system said about it.",
        ("n_recent", "n_for_ticker", "n_source_status", "d_recent", "d_for_date"),
    ),
    (
        "Watchlist",
        "Free on purpose — the alerts are only useful once this has names in it.",
        ("w_add", "w_remove", "w_watchlist"),
    ),
]


def _tools_by_name() -> dict[str, str]:
    """{tool name: one-line purpose} from sc_capabilities."""
    import index
    caps = index.sc_capabilities()
    return {t["name"]: t["purpose"] for t in caps["tools"]}


def group_of(tool: str) -> str | None:
    for title, _, members in GROUPS:
        if tool in members:
            return title
    return None


def _tier_badge(tool: str) -> str:
    import tiers
    return {"free": "free", "pro": "**Pro**", "private": "operator"}.get(
        tiers.tier_of(tool), tiers.tier_of(tool)
    )


def _section_tools() -> str:
    purposes = _tools_by_name()
    out = []
    for title, blurb, members in GROUPS:
        out.append(f"### {title}\n\n{blurb}\n")
        out.append("| Tool | Plan | What it does |")
        out.append("|---|---|---|")
        for name in members:
            purpose = purposes.get(name, "_(not registered)_").replace("|", "\\|")
            out.append(f"| `{name}` | {_tier_badge(name)} | {purpose} |")
        out.append("")
    return "\n".join(out)


def _section_personas() -> str:
    """`leads_with` is a LIST of behaviours. The table wants the headline one —
    rendering the list itself dumps a Python repr into the cell."""
    import personas
    out = ["| Profile | Persona | Horizon | Leads with |", "|---|---|---|---|"]
    for key, p in personas.PERSONAS.items():
        first = p["leads_with"][0] if p["leads_with"] else ""
        first = first.replace("|", "\\|")
        out.append(
            f"| `{key}` | **{p['name']}** | {p['horizon']} | {first} |"
        )
    return "\n".join(out)


def _section_strategies() -> str:
    import strategies
    label = {
        strategies.AVAILABLE: "✅ available",
        strategies.BUILDABLE: "🔨 buildable",
        strategies.OUT_OF_REACH: "🚫 out of reach",
    }
    out = ["| Strategy | Practised by | Status | The catch |", "|---|---|---|---|"]
    for _key, s in strategies.STRATEGIES.items():
        who = ", ".join(s["practitioners"][:2])
        catch = s["honest_limit"].split(".")[0].strip().replace("|", "\\|")
        out.append(
            f"| {s['name']} | {who} | {label[s['status']]} | {catch}. |"
        )
    return "\n".join(out)


def _section_macro() -> str:
    from src.harvester import macro
    out = ["| Series | Market | Known when |", "|---|---|---|"]
    for key, m in macro.SERIES_META.items():
        when = ("before the Taipei open" if m["when_known"] == macro.BEFORE_OPEN
                else "**trades alongside Taipei**")
        out.append(f"| `{key}` ({m['label']}) | {m['market']} | {when} |")
    return "\n".join(out)


def _section_quant_principles() -> str:
    import strategies
    out = []
    for p in strategies.QUANT_PRINCIPLES:
        out.append(f"**{p['principle']}**  \n{p['detail']}  \n"
                   f"*Enforced by: {p['enforced_by']}*\n")
    return "\n".join(out)


def render() -> str:
    import tiers
    n_tools = len(tiers.TOOL_TIERS)
    n_free = sum(1 for t in tiers.TOOL_TIERS.values() if t == tiers.FREE)

    return f"""<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     Source: scripts/build_tutorial.py
     Rebuild: python scripts/build_tutorial.py
     CI fails (tests/test_tutorial.py) if this file drifts from the code. -->

# alphatecx — how to use it

A Taiwan equity (TWSE/TPEX) supply-chain and flow intelligence system. There are
{n_tools} tools; {n_free} are free. You do not need to learn their names — you
ask in plain words and the assistant picks.

**What this is not:** investment advice. Nothing here will tell you to buy, sell
or hold, by design. It exists so you can understand a decision you make
yourself.

---

## The three surfaces

| Where | What it carries | Why |
|---|---|---|
| **Claude** (MCP connector) | Analysis you talk back to | The only surface with the tools. Ask questions here. |
| **Telegram** | The machine's own voice — stop alerts, briefs, failure notices | Push, not conversation. It tells you when something needs you. |
| **The console** `/d/<token>/` | Dashboards, per-ticker pages, system health | Look at it when you want a picture rather than an answer. |

The split is deliberate: Telegram is for messages that must reach you when you
are not looking; Claude is for anything you would want to reply to.

---

## First five minutes

Just talk. A good opening is one of:

- *"What's the system tracking right now?"* → the assistant calls `start_here`
  and `sc_data_status` so you can see what is fresh before trusting anything.
- *"Tell me about 2330."* → `ticker_lookup` → `beginner_stock_card` →
  `q_valuation`. Every term gets defined the first time it appears.
- *"I'm cautious with money — remember that."* → `set_my_risk_profile`, which
  changes how everything is framed from then on.

**Set your risk profile early.** It is one call, it persists across every future
chat, and it is what makes the rest of the system speak to you rather than at
you.

---

## The two investor characters

Your saved risk profile picks one. They are not different data — they are
different questions asked of the same data.

{_section_personas()}

The Opportunist is the one people expect to be reckless. It is not: it leads
with the stop and the position size *before* any mention of upside, and it
refuses to imply a probability of profit. The numbers bound the **loss**, not
the odds.

Ask for `investing_personas` to see all three in full.

---

## Sizing a position before you take it

`risk_estimate` is the tool most worth knowing about. Give it your account size,
the entry, and how much of the account you are willing to lose on the idea, and
it returns the position size that risks exactly that — plus three things generic
calculators miss:

- **Taiwan's ±10% daily limit means a stop does not fill in a limit-down.** A
  stop further away than one full limit gets gapped straight through.
- **Exit liquidity** in sessions, at 10% of daily volume. A stop you cannot
  trade out of is decoration.
- **What it could not compute**, named out loud. No volume data means
  "liquidity is UNKNOWN", never silence.

Lots round **down**, always. Rounding up would quietly exceed the one number you
asked it to control.

---

## Reading `q_backtest` without fooling yourself

This is the part that matters most, because a backtest is the easiest place in
the system to be lied to — including by yourself.

**Read `verdict` first, then `net_edge_vs_baseline_pct`.** Never quote a bare
hit rate. Four fields decide whether a result means anything:

| Field | Why |
|---|---|
| `baseline` | The same window with no condition applied. A 58% hit rate against a 56% baseline is a **two point** edge, not a 58% one. |
| `net_edge_vs_baseline_pct` | That edge after Taiwan round-trip friction (0.585% — brokerage both ways plus the sell-side transaction tax). Short-horizon rules routinely go negative here while looking profitable gross. |
| `n_effective` | Independent observations, clustered by date. 400 raw triggers may be 25 real ones, because names triggering on the same day share one market. |
| `caveats` | Survivorship and in-sample tuning. Both bias **upward** and neither is corrected. |

Entry defaults to `next_close` — the first price you could actually have traded.
The old default bought at the very close the signal was computed from, which
nobody can do.

**"No edge" is the common result and a useful answer.** A tool that always finds
something is a tool that is fitting noise.

---

## What can be copied from quant funds

{_section_strategies()}

Ask `systematic_strategies` for the full entry on any of these. The
`out of reach` rows are the honest part: they cannot be approximated here, and a
moving-average crossover wearing a famous fund's name would be a worse answer
than saying so.

### Principles systematic investors agree on

{_section_quant_principles()}

---

## World markets

`q_macro` carries the tape around the Taiwan session.

{_section_macro()}

**The timing column is not decoration.** Tokyo, Seoul, Shanghai and Hong Kong
trade *at the same time as Taipei*, so their stored row is a previous close
while today's move is still happening. Only the `before the Taipei open` rows
are genuinely overnight information.

---

## What arrives when

All times Taipei.

| Time | What | Where |
|---|---|---|
| 08:30 weekdays | Risk Guard pre-market light; macro brief | Telegram |
| 09:00–13:30 | Intraday stop watcher, every ~3 min | Telegram (only if a line breaks) |
| ~15:00 | T86 institutional flow publishes | — |
| 16:30 weekdays | Full harvest → brief → Risk Guard → dashboards | Telegram + console |
| 18:30 | Database backup | — |
| every ~3 min | News poller; watchlist matches pushed | Telegram |

Institutional flow is **structurally end-of-day** — T86 publishes once. No
transport makes it faster. Price against a stop line is the only genuinely
intraday signal here, which is exactly what the stop watcher does.

---

## The tools

You never need to name these. They are here so you know what exists.

{_section_tools()}

---

## When something looks wrong

| Symptom | Likely cause |
|---|---|
| `permission denied` on a table | A `mcp_viewer` grant did not land. Run **Actions → DB Migrate (manual)**, type `apply`. |
| `q_macro` returns nothing | `raw_macro` does not exist yet — same migration. |
| No Telegram at all | `TELEGRAM_ENABLED=false`, or a category switch is off. Check the repo variable and the Zeabur service env. |
| Telegram quiet but the run went red | Expected when the kill switch is off: the Actions log is then the only record. |
| The stop watcher never fires | `FUGLE_API_KEY` unset on the Zeabur `worker` service. It logs one line and idles. |
| Data looks stale | Ask for `sc_data_status` — it reports per-table freshness, and the console overview renders the same list. |

---

## For the operator

```bash
.venv/bin/python -m pytest -q        # full suite, no network or DB needed
ruff check .                          # CI enforces this repo-wide
python -m src.harvester.daily         # the nightly pipeline
python -m src.cron.brief --mode post_close
python scripts/build_tutorial.py      # regenerate THIS file
```

The console lives behind `CONSOLE_TOKEN`, which is deliberately **not** the same
secret as `MCP_BEARER_TOKEN` — sharing a dashboard link should not share the API
key. If `CONSOLE_TOKEN` is unset it falls back to the API token, which is the
old behaviour and the reason to set it.

---

## How this page stays true

It is generated from the running system by `scripts/build_tutorial.py`. Tool
names, plans, personas, strategies and macro series are read from the code, not
retyped. `tests/test_tutorial.py` rebuilds it and fails CI if the committed file
differs — so adding a tool without updating this page turns the build red.

Edit the prose in `scripts/build_tutorial.py`, run it, and commit both files.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the committed file is stale")
    args = ap.parse_args()

    rendered = render()
    if args.check:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        if current != rendered:
            print("docs/TUTORIAL.md is stale — run: python scripts/build_tutorial.py")
            return 1
        print("docs/TUTORIAL.md is current")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered)
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(rendered):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
