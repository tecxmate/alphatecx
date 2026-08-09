---
title: Investing principles layer — school-neutral universals
type: topic
slug: investing-principles
date: 2026-08-09
updated: 2026-08-09
attributed_to: [niko, antigravity-agent]
belongs_to: [mcp-server, commercial-productization]
source: chat
status: active
tags: [principles, mcp, tools, personalization, ip, philosophy]
related: [2026-08-09-connector-teaching-ux, 2026-08-09-risk-profile-personalization, commercial-productization]
---

A reasoning layer that gives the AI an experienced investor's *mindset* — kept SEPARATE from the
clean data tools, which stay unbiased ground truth.

## What & why

[niko] has a shelf of canonical investing books and asked whether to fold their wisdom into the
tools. Decision: **yes, but only the principles the major schools AGREE on, in a separate layer.**

- **Data tools stay clean.** No philosophy is baked into what `q_valuation`/flow/`rg_status` return
  or screen. Wisdom lives in *reasoning*, never in the data.
- **Only universals.** The books openly disagree (Bogle/Malkiel: index, don't pick — vs
  Graham/Fisher/Lynch: pick with discipline; Murphy's technicals vs fundamentals). So contested
  doctrine (index-vs-pick, technical analysis, any specific strategy) is **excluded**. Only the
  cross-school agreements ship — [niko]'s explicit constraint ("only principles that are universally
  true").
- **Distilled, not ingested.** The books are in copyright; serving their text to customers would be
  redistribution. The layer is a **synthesis in our own words, attributed** to the thinkers — ideas
  aren't copyrightable, expression is. No PDF was parsed.

## The nine universals (see `_PRINCIPLES` in index.py)

margin of safety (Graham/Housel) · know what you own (Lynch/Fisher) · survival first —
risk = what you can't afford to be wrong about (Housel/Douglas) · master your psychology
(Douglas/Housel/Graham's Mr. Market) · price ≠ value (Graham) · beware manias & "this time is
different" (Kindleberger/Dalio) · time & compounding (Bogle/Housel) · costs & taxes compound against
you (Bogle) · humility, process over outcome (Douglas).

*(Horowitz's* Hard Thing About Hard Things *is a company-building book, not investing — for the
founders, not the tool.)*

## How it's wired

- **`investing_principles` tool** — returns the nine principles + (if the caller has a stored risk
  profile) `emphasis_for_profile`. The principles never change; only which to STRESS does:
  conservative → margin of safety / diversification / cost / preservation; aggressive → the
  guardrails matter most (survival-first sizing, psychology, avoid manias); balanced → weigh both.
  Ties into [risk-profile personalization](../decisions/2026-08-09-risk-profile-personalization.md).
- **Server `instructions`** tell the AI to ground reasoning in it — cite the principle, apply it,
  never preach, never push one strategy as gospel.
- 4 new tests. Suite 453 pass, ruff clean. Dormant until next `zeabur deploy`.
