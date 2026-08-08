---
title: Commercialization direction — MCP connector first, headless Claude app second
type: decision
slug: 2026-08-08-commercialization-direction
date: 2026-08-08
updated: 2026-08-08
attributed_to: [niko, brian, antigravity-agent]
belongs_to: [alphatecx]
source: chat
status: proposed
tags: [commercialization, product, connector, mcp, oauth, safety, compliance, monetization]
related: [system-architecture, 2026-07-31-risk-guard-phase1, brian, niko]
---

## Context

[niko] and [brian] want to turn alphatecx into a commercial product. Target customer:
**funded investors who don't want to read much about finance but still want to consult an AI
(Claude) for financial decisions.** The tool's role is to give Claude a strong *ground truth*
(Taiwan equity flow / supply-chain / risk data) so Claude's consultation is better.

Two surfaces were on the table:
- **[niko]** — a headless web app exposed to Claude as a **remote MCP connector**, sold like
  Apollo.io (connects to Claude, works well) and WordPress.com (connector gated behind a paywall
  / upgrade). Customer brings their own cloud (Claude) account and sets up the connector.
- **[brian]** — a **native mobile app**, on safety / guard-rail grounds.

Surfaced first time this turn (chat 2026-08-08). **Not yet finalized — status `proposed`.**

## The clarification that reframes it

"Sell the credit usage through the connector" conflates two distinct models:

| | A. Remote MCP connector (Apollo / WordPress) | B. Headless web app embedding Claude |
|---|---|---|
| Who pays Anthropic | the customer's own Claude sub | you (your API key), marked up |
| You sell | subscription to your data/tools | bundled AI + data seat |
| Persona / guardrails / disclaimers | ❌ not yours — generic Claude chat | ✅ system prompt, suitability, compliance framing |
| Onboarding | customer needs a Claude acct + OAuth | just a login on your site |
| Build state (2026-08-08) | ~80% done (OAuth 2.1 + PKCE shipped, MCP deployed) | new build |

In model A you do **not** resell Claude tokens. Reselling the AI (so the customer needs no Claude
account of their own) *is* model B and requires running Claude server-side via the Messages / Agent SDK.

## Decision (proposed)

1. **Phase 1 — ship the remote MCP connector (model A), gated behind a paid subscription (Stripe).**
   It reuses the OAuth 2.1 + PKCE work already merged, matches the Apollo/WordPress precedent, adds
   zero AI-billing complexity, and is the fastest honest test of willingness-to-pay.
2. **Phase 2 — headless web app embedding Claude via the Agent SDK (model B)** for the
   guard-railed, own-the-customer, resell-the-AI version. This is where [brian]'s safety
   requirement is actually satisfied.
3. **Mobile is deferred** — at most a thin shell over the Phase-2 backend later, not the starting point.

## Rationale

- **[brian]'s safety concern is valid; the mobile lever is not the fix.** Unguarded generic Claude
  giving investment opinions to funded, finance-averse users is a real liability gap. But guardrails
  come from *owning the AI surface* (model B), not from being on mobile.
- **The "can't keep up with Claude" fear applies to the wrong layer.** It's true for apps replicating
  the *consumer chat UI* (Claude Code / Cowork / chat change daily). The **Messages / Agent SDK API is
  stable** — bumping one model string inherits model upgrades for free. So embedding Claude via the API
  gives [brian]'s guardrails *without* the treadmill and without app-store friction.
- **Model A is nearly built and lowest-maintenance**, so it de-risks demand before the model-B investment.

## Consequences / open items

- **Compliance is the non-negotiable gate.** Selling "help me make financial decisions" to funded
  investors can cross into **regulated investment advice** (RIA in US, SFC-type licensing elsewhere)
  depending on customer jurisdiction (Taiwan / US / …). The connector framing — *data/tool provider
  feeding a general-purpose AI*, not "we tell you what to buy" — is the lower-liability posture.
  Add disclaimers into tool responses (extend the existing `_stamp()` on every MCP response).
  **Get a lawyer's read before taking money.** Not hand-waved.
- Phase 1 productization work (not yet started): Stripe subscription gate layered on existing OAuth,
  per-customer metering / rate limits, and the disclaimer field on `_stamp()`.
- [brian] added as a stakeholder this turn.
