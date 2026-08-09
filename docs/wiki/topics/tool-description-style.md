---
title: Tool description style — writing for the model-as-consultant
type: topic
slug: tool-description-style
date: 2026-08-09
updated: 2026-08-09
attributed_to: [antigravity-agent]
belongs_to: [commercial-productization, mcp-server]
source: chat
status: active
tags: [mcp, tools, ux, onboarding, descriptions, template]
related: [commercial-productization, 2026-08-09-connector-teaching-ux]
---

How to write MCP tool descriptions so the model selects the right tool AND can teach a non-expert
retail investor. Descriptions are read by the **model, not the user**, so pedagogy here means giving
the model the *vocabulary and the "when"* — the user-facing teaching then comes from the server
`instructions` persona (set once, in `index.py`), not from repeating "act like a teacher" in every
tool.

## The template

Each tool docstring, in order:

1. **One line: what it returns**, plain language first, plumbing second.
2. **When to use** — the user question(s) this answers, in the words a beginner would use.
3. **When NOT to use / which tool instead** — only if it's easily confused with a sibling
   (the five screeners especially: `q_screener`, `q_factor_screen`, `sc_accumulation_screen`,
   `market_flow_screener`, `flow_leaders_scan`).
4. **Plain-language gloss of the concept** — define the jargon the tool is about, one sentence.
5. **Key output fields** — name the important returned fields and what each means, so the model
   labels them correctly instead of guessing.

Keep it tight — every description rides in context on every call. A crisp "when to use" beats a long
essay; move deep mechanics to a `# comment` if needed.

## Before / after (q_valuation)

**Before** (quant-facing — tells the model the plumbing, not the use):
> Latest valuation metrics (P/E, P/B, dividend yield) per ticker. Sourced from TWSE BWIBBU_d,
> harvested daily. Filters compose AND-style… NULL pe_ratio means no positive earnings…

**After** (adds use + gloss, keeps the mechanics):
> Is a stock cheap or expensive? Returns valuation metrics per ticker.
> **When to use:** the user asks whether something is over/under-valued, or wants cheap names in a
> pillar. **Gloss:** P/E = price per $1 of yearly earnings (lower can mean cheaper, or slower
> growth); P/B = price per $1 of net assets; dividend yield = yearly dividend ÷ price.
> **Fields:** `pe`, `pb`, `dividend_yield`, `close`, `pillar`. Sorted cheapest-first by P/B.
> A NULL P/E means no positive earnings (excluded when `max_pe` is set). Data is daily, T+1.

## The step-2 pass — priority order (beginner-facing first)

Rewrite these ~10 before the long tail; they're what a retail user hits first:

1. `beginner_stock_card` · 2. `quote` · 3. `q_valuation` · 4. `dividend_calendar` ·
5. `flow_leaders_scan` · 6. `rg_status` · 7. `price_history` · 8. `n_for_ticker` ·
9. `sc_ticker_momentum` · 10. `ticker_lookup`

Then the five overlapping screeners get a "when NOT to use / use X instead" line each, since
disambiguation is where selection accuracy is won.

## Where each layer lives (don't mix them up)

| Layer | Home | Job |
|---|---|---|
| Persona ("teach a beginner, define jargon, no buy/sell") | server `instructions` in `index.py` (set once) | whole-connector tone |
| When-to-use + concept gloss + field meanings | each tool docstring | selection + vocabulary |
| Orientation menu + glossary for a new user | `start_here` tool | first-reply onboarding |
| Optional per-field definitions in the payload | `_stamp` extension (selective) | prevent metric mislabeling |
