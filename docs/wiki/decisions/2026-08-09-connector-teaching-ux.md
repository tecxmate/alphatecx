---
title: Connector teaching UX — persona in server instructions, not tool count
type: decision
slug: 2026-08-09-connector-teaching-ux
date: 2026-08-09
updated: 2026-08-09
attributed_to: [niko, antigravity-agent]
belongs_to: [mcp-server, commercial-productization]
source: chat
status: active
tags: [mcp, tools, ux, onboarding, instructions, context]
related: [tool-description-style, commercial-productization, 2026-08-08-commercialization-direction]
---

## Context

[niko] asked whether 44 tools is too many for the model to handle (assume clients on Opus 5, 1M
context), and whether we should bake teacher/consultant explanatory language into tools so the AI
onboards a non-expert retail investor well.

## Decision

**Keep the ~44 tools; fix the guidance layers, not the tool count.**

- **Context is a non-issue.** ~44 tool schemas ≈ 8–15k tokens — trivial on 1M (fine even on 200k).
  The real cost of many tools is *selection accuracy*, not context length.
- **Teaching lives in layers, each with one job** (do NOT repeat "act like a teacher" in 44
  descriptions):
  1. **Server `instructions`** (MCP initialize field) — the consultant persona, set once. Was
     `None`; now populated in `index.py` (`CONSULTANT_INSTRUCTIONS`): advise a non-expert, define
     jargon plainly, start from the question, chain simplest-first, never buy/sell, cite `_as_of`.
  2. **Tool descriptions** — "when to use" + a plain-language gloss of the concept + field meanings,
     so the model selects correctly and can explain. Template + priority in
     [tool-description-style](../topics/tool-description-style.md).
  3. **`start_here` tool** — a plain-language menu (what to ask → which tool) + beginner glossary,
     for first-reply orientation. Complements the technical `sc_capabilities`.
  4. **Optional** — selective `_glossary` in responses; consolidate the 5 overlapping screeners
     (the one place fewer tools genuinely helps selection).

## Built this turn (steps 1 + 3)

Server `instructions` set; `start_here` tool added (first tool). 5 new tests; suite 436 pass, ruff
clean. Step 2 (the top-10 description rewrite) is **done** (2026-08-09) — each now leads with a plain-
language question + a jargon gloss. Step 4 deferred.

## Rationale

Cutting tools for "context" reasons would be solving the wrong problem. The leverage is in telling
the model *how to be a consultant* (once, in instructions) and *when/why each tool applies* (in
descriptions) — which also makes it a better teacher to the user without bloating anything.

## Consequences

- New: `CONSULTANT_INSTRUCTIONS` + `start_here` in `index.py`, `test_onboarding.py`,
  `topics/tool-description-style.md`. Dormant until the next `zeabur deploy` (like all server code).
- Follow-ups: the top-10 description pass; then the screener disambiguation lines.
