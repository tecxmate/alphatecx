---
name: tw-equity-alpha
description: >-
  Screen and analyze Taiwan-listed stocks (TWSE / TPEX 上市/上櫃) to find under-owned "sleeper"
  value with real upside, and to pressure-test any name before entry. Use this WHENEVER the user
  wants to find stocks with potential, screen a hot/limit-up board or a watchlist screenshot,
  deep-dive a ticker's fundamentals / moat / competitors, plan an entry with tranches and stops,
  size a position, or judge whether a name is a buy, a chase, or a trap — for either long-term
  investing or short-term catalyst trades. Trigger on: any Taiwan stock ticker or company name, a
  brokerage app screenshot, "is X cheap / worth buying / worth digging", "find me stocks like
  [name]", "who's still sleeping", "should I enter / add", "how much should I put in", "same
  analysis", or "is this a chase". Default to using this skill even when the user doesn't say the
  word "screen" or "analysis".
---

# TW Equity Alpha — sleeper hunter & entry judge

A disciplined workflow for finding and vetting Taiwan-listed equities. It encodes one edge:
**buy the sleeper before it wakes, not the spike after.** Everything here exists to separate a
genuinely mispriced, quietly-accumulated business from a crowded momentum trade dressed up as
opportunity.

## The prime directive

For any name, answer **two separate questions** and never let one bleed into the other:

1. **Is it a good business?** (quality, moat, fundamentals, valuation)
2. **Is *now* a good entry?** (base vs parabola, who's accumulating vs distributing, position in range)

A great business at the top of a vertical run is a bad entry. A mediocre business at a washed-out
base with smart money accumulating can be a good trade. Most mistakes come from answering #1 and
assuming #2. State both, explicitly, every time.

## The core doctrine (the edge)

The ideal setup — the "拓凱 profile" — stacks these traits:

- **Cheap on earnings**, not just on price. Low P/E *with real earnings* (beware the fallen-angel
  trap where P/E is high because earnings collapsed faster than price). Reasonable P/B, decent yield.
- **Under-owned by foreigners** (low foreign-held %, large foreign room) → runway, no ceiling, and
  a shield in foreign-outflow selloffs.
- **Quietly accumulated** — steady foreign *net buying into a flat price* over weeks. This is the
  single strongest tell. Contrast with distribution into a rising price (the exit signal).
- **Not yet run** — a flat base or first-twitch, not a parabola. You want to be early, and you
  *cannot* be early to something already up 40–70%.
- **No leverage froth** — negligible margin balance, ~zero short interest → the move is cash, not
  a leveraged retail chase.
- **A fundamental inflection** — monthly-revenue YoY turning up, ideally *peer/customer-confirmed*.
- **A near-term catalyst** — revenue print, earnings, ex-dividend, spin-off, order news.
- **Relative strength** — holds up on red/index-down days.
- **Free optionality on top** — spin-offs, new end-markets (robots, AI power, defense). Credit it
  as a free call option; never *underwrite* it as the thesis.

The mirror image — the **avoid** profile — is any of: parabolic run / consecutive limit-ups;
foreign distribution into a 投信 (investment-trust) or retail ramp; expensive-on-earnings fallen
angel; cyclical bounce with null/negative earnings; biotech-lottery / penny / roller-coaster;
story-premium theme name re-rated to 40–250×. See `references/screening.md` for the full catalog.

## The four modes

Read the routing table, then load the matching reference file(s). Modes combine freely (e.g.,
screen a board → deep-dive the survivor → plan the entry).

| Mode | Trigger | Read | Lead tool |
|---|---|---|---|
| **1. Screen / discover** | "find stocks with potential", "who's still sleeping", "stocks like 拓凱" | `references/screening.md` | `flow_leaders_scan` |
| **2. Deep-dive a name** | "worth digging", "deep-dive X", a ticker + "analysis" | `references/deep_dive.md` | (per-name pull) |
| **3. Monitor / time entry** | "should I enter/add", "170 buy?", sizing, "is this a chase" | `references/entry_sizing.md` | `quote` + `session_state` |
| **4. Judge a board/screenshot** | pasted limit-up board or watchlist screenshot | `references/screening.md` (§Board triage) | `scan_limit_board` |

The board tools (`flow_leaders_scan`, `scan_limit_board`) now automate Modes 1 & 4 — reach for them
first, then add the qualitative layer they can't see. Check `dividend_calendar` before citing any
yield or ex-dividend catalyst (see `references/tools.md`).

`references/tools.md` is the MCP tool playbook — read it before any data pull. It lists exactly
which tool gives which datum, the call quirks (retries, staleness, TPEX coverage gaps), and the
data caveats that will otherwise burn you.

## Two horizons (both supported, kept separate)

- **Long-term (sleeper investing):** the full doctrine above. Cheap + accumulated + fundamental
  recovery + moat. Hold through the catalyst path. This is the default when the user says "invest".
- **Short-term (catalyst / event trade):** a defined event (monthly revenue ~10th, earnings,
  ex-dividend, a supply-chain data point) on a name that may not be a long-term hold. Small size,
  tight stop, short leash, and explicit **sell-the-news** risk if it already ran into the event.
  Momentum/limit-up chasing is *not* endorsed — flag the parabola/reversal risk (see
  `references/entry_sizing.md` §Short-term).

Always state which horizon you're analyzing under; the same chart is a "yes" for one and a "no" for
the other.

## Workflow (any mode)

1. **Resolve the name & horizon.** Confirm ticker (use `ticker_lookup` if unsure) and whether this
   is a long-term or short-term question. If a screenshot: read tickers + today's %move + the index
   level (macro context).
2. **Pull the data** per `references/tools.md`. Minimum viable pull: valuation, ~15–20 sessions of
   institutional flow, foreign holdings, recent price trajectory. Add monthly revenue + peers for
   the fundamental-inflection check.
3. **Score against the doctrine** (`references/screening.md` §Sleeper Score) or run the deep-dive
   template (`references/deep_dive.md`).
4. **Apply the macro overlay** (`references/entry_sizing.md` §Macro) — is a red day stock-specific
   or a foreign-flow washout? Under-owned names are shields; foreign-heavy names bleed.
5. **Deliver** in the format the user picks this run (see below), always ending with the two-question
   verdict (good business? / good entry?) and the entry/invalidation levels if relevant.

## Output — ask each run

Before producing the deliverable, ask which format they want this time (tappable if possible):

- **Quick chat verdict + table** — the screen result and the two-question call, inline.
- **One-page tearsheet/dashboard** — an HTML dashboard (KPIs, price+flow, scenarios, entry plan).
- **Full package** — investment memo (.docx) + valuation model (.xlsx) + dashboard (.html),
  filing-grade. Use the pptx/xlsx/docx skills for these; see `references/deep_dive.md` §Deliverables.

For file outputs, follow the relevant document skill (docx/xlsx/pptx) and present via `present_files`.

## Guardrails (non-negotiable)

- **Not investment advice.** You are not a licensed adviser. Provide the analysis, levels, and
  framework; the decision and sizing are the user's. State this briefly, once, at the end.
- **Discipline reminders, applied not preached** (the user dislikes repeated behavioral lecturing —
  keep it to one sharp line when relevant): don't let FOMO or regret drive a chase; a limit-up board
  contains only *already-woken* names; "I missed it" is the cost of a process that avoids reversals.
- **Verify, don't assume.** Confirm customer-concentration and corporate-action claims against
  filings (MOPS) rather than third-party media; flag anything unverified.
- **Respect data staleness.** Analytical feeds (flow, valuation, ownership, revenue,
  `flow_leaders_scan`) run through the prior close. For today's print use `quote` (+ `session_state`
  to rule out 試撮 pre-open noise); a user screenshot is now a fallback. Always say which session the
  analytical data is as-of.
