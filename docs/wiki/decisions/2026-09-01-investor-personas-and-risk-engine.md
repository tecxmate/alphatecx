---
title: Investor personas — The Steward and The Opportunist, over a real risk engine
type: decision
slug: 2026-09-01-investor-personas-and-risk-engine
date: 2026-09-01
updated: 2026-09-01
attributed_to: [niko, claude-agent]
belongs_to: [mcp-server, investing-principles, commercial-productization]
source: chat
status: active
tags: [personalization, risk, personas, mcp, tools, instructions, safety]
related: [2026-08-09-risk-profile-personalization, investing-principles, risk-guard, mcp-server, niko, brian]
---

## Context

[niko], in his own words: *"one is a conservative long term investor, one is an opportunist who can
trade to make money. i know it's more risky. **bake that in and estimate the risk well**."*

That last clause is the whole design, and it is why this is a decision page rather than a feature
note. An aggressive persona **without numbers is not a persona, it is a personality** — "be
aggressive" with no sizing math is encouragement, and encouragement is the one thing this system has
spent every prior decision refusing to give (see [Risk Guard Phase 1](2026-07-31-risk-guard-phase1.md),
whose enforced non-goal is that it never emits a buy signal).

The precondition already existed. [Risk-profile personalization](2026-08-09-risk-profile-personalization.md)
put `risk_profile` (`conservative | balanced | aggressive`) on the customer and had `my_profile`
return a `how_to_adapt` one-liner. What was missing was substance behind the adjective.

## Decision

**1. The personas ARE the risk profiles — not a new axis.**

| `risk_profile` | Persona | Horizon | Leads with |
|---|---|---|---|
| `conservative` | **The Steward** | years | what could permanently impair this capital |
| `balanced` | **The Allocator** | quarters | weighing both sides |
| `aggressive` | **The Opportunist** | days–weeks | the stop and the size, *before* any upside |

Adding a second, parallel notion of investor style would have been the mistake. There is one column,
one vocabulary, three characters.

**2. `index._RISK_GUIDANCE` is GENERATED from `personas.py`, never hand-copied.**

```python
_RISK_GUIDANCE = {p: personas_mod.guidance(p) for p in personas_mod.PERSONAS}
```

This repo has a documented failure mode for hand-maintained parallel lists: `sc_capabilities` drifted
to 33 of 48 tools before a test caught it. A second copy of the persona text would rot identically.
A test pins the generation.

**3. `position_risk.py` — pure arithmetic, no DB, clock or network.**

Same rationale as `mcp_server/api/rg/`: **a risk number you cannot re-derive from stated inputs is
one nobody should size money on.** It computes:

- an ATR-based stop (×2 — the same multiple `momentum_leaders_scan` uses, so the two cannot disagree);
- position size risking exactly the caller's stated `risk_pct` to that stop;
- exit liquidity, in sessions, at 10% participation;
- **the Taiwan-specific piece generic models miss** — the ±10% daily price limit means a stop
  **does not fill in a limit-down**, and a stop further away than one full limit is gapped straight
  through. A model that assumes stops fill is wrong in exactly the session it matters.

Exposed as `risk_estimate` (PRO). `investing_personas` (FREE) explains the characters.

**4. Two behaviours chosen against the obvious default, both mutation-verified.**

- **Lots round DOWN.** Rounding up silently exceeds the one number the caller asked to control.
  Switching to `ceil` fails two tests.
- **`estimate()` degrades by section and NAMES what it could not compute.** No volume → *"liquidity
  is UNKNOWN, not fine."* No stop and no ATR → it refuses to size anything at all. **Silence about
  an uncomputed risk reads as no risk** — that is the failure this module exists to prevent, so it
  must never be reachable by omission.

**5. The non-advice boundary moves from *requested* to *enforced*.**

Previously the "never tell the user to buy, sell or hold" rule lived only in the server
`instructions`. The aggressive persona is precisely the one a determined user pushes on, so the
sentence is now appended to **every** persona's guidance and asserted by a parametrised test —
stripping it fails three tests. The Opportunist additionally refuses to imply a probability of
profit: **these numbers bound the loss, not the odds.**

## Notes / consequences

- A test pins that no persona's `reaches_for` names a tool that does not exist. A persona pointing at
  a renamed tool dead-ends the model on *every* conversation, silently.
- `test_my_profile_returns_saved_tier_with_adaptation` legitimately broke: it asserted the literal
  word *"preservation"* from the old one-liner, and The Steward says *"permanently impair this
  capital"* — same doctrine, different words. Rewritten to assert **meaning** (persona name,
  "capital", the boundary sentence) so richer guidance stops reading as a regression.
- **Still missing, and deliberately so: base rates.** The Opportunist can size a trade and bound its
  loss, but cannot say how often setups like it worked. `q_backtest` exists, but quoting a win rate
  from it needs an honest look-ahead and survivorship audit first. Deferred by [claude-agent] and
  accepted by [niko]; a persona that quotes an unaudited win rate would be worse than one that
  admits it has none.
- Owner sessions still have no stored profile — unchanged from the 2026-08-09 decision.
- 34 new tests; suite 676 pass, ruff clean, 52 registered = 52 advertised = 52 tiered.

Shipped in [PR #14](https://github.com/tecxmate/alphatecx/pull/14) (`9799d3e`).
