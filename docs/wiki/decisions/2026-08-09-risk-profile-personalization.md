---
title: Risk-profile personalization — per-user investment style
type: decision
slug: 2026-08-09-risk-profile-personalization
date: 2026-08-09
updated: 2026-09-01
attributed_to: [niko, antigravity-agent]
belongs_to: [mcp-server, commercial-productization]
source: chat
status: active
tags: [personalization, risk, onboarding, mcp, tools, instructions]
related: [2026-09-01-investor-personas-and-risk-engine, 2026-08-09-connector-teaching-ux, commercial-productization, niko, brian]
---

## Context

[niko] wants the AI to adapt investment style to each user's risk tolerance — [niko] is
conservative/low-risk/high-safety, [brian] is aggressive/high-risk/high-reward — and to establish
that profile during onboarding so the same data is framed differently per person.

## Decision

Persist a **per-customer risk profile** (fixed tiers `conservative | balanced | aggressive` + an
optional free-text `risk_note`) and have the AI establish and honor it.

- **Stored on the customer**, not conversation-only, so it sticks across every chat/session.
- **Fixed tiers** (not free-form) so the model adapts consistently; a `note` carries nuance
  ("dividends only, no small caps").
- **Set three ways:** the user states it → `set_my_risk_profile` tool; at provision
  (`provision_customer.py --risk`); or by the operator (`manage_customer.py set-risk`).
- **Read** via the `my_profile` tool (returns the tier + a `how_to_adapt` string) and surfaced in
  `start_here`. Server `instructions` tell the AI to call `my_profile` early, ask + save if unset,
  and adapt: conservative → capital preservation / dividends / downside; aggressive → growth /
  momentum / higher risk-reward (always naming risk); balanced → both.

## Built this turn

- `sql/023_customers_risk_profile.sql` — `risk_profile` + `risk_note` columns; extends the
  column-scoped `mcp_viewer` UPDATE grant (from 022) to them; re-appended after 003.
- `customers.py` — `VALID_RISK`, `get_risk` (fails soft), `set_risk_profile` (writes via the read
  pool + grant); `list_all` now includes `risk_profile`.
- `index.py` — `my_profile` + `set_my_risk_profile` tools, `_RISK_GUIDANCE`, the persona paragraph in
  `CONSULTANT_INSTRUCTIONS`, and a `personalize` nudge in `start_here`.
- CLIs — `provision_customer.py --risk`, `manage_customer.py set-risk` + risk shown in `list`.
- 12 new tests. Suite 448 pass, ruff clean.

## Notes / consequences

- Owner sessions (shared `OAUTH_PASSWORD`) have no stored profile — the tools say so and tell the AI
  to adapt within the conversation. The real per-user feature is for provisioned customers (which is
  what [niko]/[brian] each are).
- A latent trap surfaced and was handled in tests: any tool goes through `_stamp`, which meters via
  `usage.record`; tests that set a `current_customer` must patch `usage.record` or they hit the live
  DB. Documented in the test.
- Dormant until the next `zeabur deploy` + `apply_schema.py` (adds 023).

## Extended 2026-09-01

The three tiers were given characters and arithmetic — `conservative` = The Steward,
`aggressive` = The Opportunist — and `_RISK_GUIDANCE` is now generated from `personas.py`
rather than living here as a hand-written one-liner per tier. This page stays `active`: the
column, the CLIs and the read path are unchanged. See
[Investor personas + risk engine](2026-09-01-investor-personas-and-risk-engine.md).
