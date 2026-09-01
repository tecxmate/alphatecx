---
title: Global macro coverage — Japan, Korea, China, Europe, and when a series is knowable
type: decision
slug: 2026-09-01-global-macro-coverage
date: 2026-09-01
updated: 2026-09-01
attributed_to: [niko, claude-agent]
belongs_to: [system-architecture, mcp-server]
source: chat
status: active
tags: [macro, data, harvester, mcp, tools, honesty, timezones]
related: [2026-09-01-investor-personas-and-risk-engine, system-architecture, mcp-server, niko]
---

## Context

[niko]: *"when I mean macroeconomics, I think you should also check Japan, Korean, Chinese,
US, Europe market."*

`raw_macro` shipped earlier the same day with five series — SOX, TSMC ADR, US 10Y, DXY,
USD/TWD — chosen under one stated rule, written at the top of `src/harvester/macro.py`:

> these five series are the only data that is ALREADY KNOWN before the Taipei open

That rule was true of all five, and it was the module's whole justification for existing.

## Decision

Add six series — `nasdaq` (^IXIC), `estoxx50` (^STOXX50E), `nikkei` (^N225), `kospi`
(^KS11), `shanghai` (000001.SS), `hangseng` (^HSI) — taking the table from 5 to 11. No
migration: `raw_macro` keys on `(date, series)` and `series` is free text, so new markets
are new rows.

**And record that the addition broke the premise, because that is the substantive part.**

**Tokyo, Seoul, Shanghai and Hong Kong trade at the same time as Taipei.** Their newest
stored row is a *previous* close while today's move is still happening. Reciting a live
KOSPI as "overnight macro" is a false statement about the world, not a formatting slip —
and it is the kind of falsehood that survives review because the number is real and the
label is plausible.

So every series carries `when_known`:

| | meaning |
|---|---|
| `before_open` | that session had **closed** before Taipei opened; it can inform today's open |
| `same_session` | the market trades **alongside** Taipei; this row is its previous close |

Three consumers had to change to stop asserting the old rule:

1. **`q_macro`** returns `when_known` and `market` on every row, glosses both, and gained a
   `market=` filter. Its `_freshness` stamp stopped reading *"US session close, known before
   the Taipei open"* — that string was about to become a lie on 4 of 11 rows.
2. **The pre-market brief emits two lines**, not one: 隔夜 Macro (US + Europe) and
   亞洲鄰近市場 (…前一日收盤,尚未開盤). At 08:30 Taipei the Asian peers' newest close is
   exactly as old as Taiwan's own — worth reading, but not as news about today. One line
   would have put two ages of information under one honest-looking label.
3. **The `sc_capabilities` entry**, which still described the old five and repeated the same
   false timing claim.

## Why these indices

- **Korea is the one usually left out and the one that matters most.** Samsung and SK Hynix
  sell into the same memory cycle as Taiwan, so a KOSPI/TAIEX divergence is signal rather
  than noise.
- **Japan** carries the semiconductor-equipment complex (Tokyo Electron, Advantest).
- **Shanghai** is mainland demand; **Hang Seng** is where China tech is actually priced.
  Different animals, so both rather than one as a proxy.
- **Europe** earns its place on timing alone: it closes ~00:30 Taipei, the last read before
  the open.
- **Nasdaq** for the broad US tech tape alongside the SOX's narrower cycle read.

## Notes / consequences

- **`SERIES_META` is the single source of truth** (symbol, vendor, market, label,
  `when_known`); `YAHOO_SERIES` / `FRED_SERIES` / `ALL_SERIES` / `MARKETS` are all derived.
  Four parallel maps is exactly how `sc_capabilities` drifted to 33 of 48.
- **`index.py` mirrors that metadata** because it cannot import `src/` — the Docker build
  context is `mcp_server/`, the same constraint behind the mirrored `quant/` trees. A test
  pins market **and** `when_known` for every series in both directions: a series the server
  calls `before_open` while the harvester calls it `same_session` is worse than a missing
  one, because it is confidently wrong.
- **`_utc_date`'s invariant is now written down.** Yahoo stamps a daily bar at the session
  OPEN, so a UTC date equals the market's own session date only while that open falls on the
  same UTC day. True for all eleven — Tokyo opens 00:00 UTC, Hong Kong 01:30, Frankfurt
  08:00, New York 14:30 — but that is a property of *these exchanges*, not of the code. The
  ASX (10:00 AEDT = 23:00 UTC the **previous** day) would be stamped a day early; whoever
  adds it must convert through the exchange timezone. Tested, including the ASX near-miss.
- **Yahoo calls went 4 → 10 in one change**, so `fetch_series` paces them
  (`MACRO_REQUEST_DELAY`, default 0.5s). Four unspaced calls never drew a 429; ten is a
  different ask of a free endpoint, and a 429 costs a whole series for the day.
- Unchanged and still true: `raw_macro` is **not a trading calendar** — `raw_twse_index`
  remains the authoritative "did Taiwan trade" oracle. Macro rows exist for foreign sessions
  on days the TWSE was shut; that is the feature and the trap.
- The container cannot exercise the fetch path (egress is a GitHub/PyPI allowlist that
  blocks Yahoo and FRED), so the parsers stay pure and fully tested offline while the six new
  symbols are unverified until the nightly Actions run. **The first run is the acceptance
  test**; `ingestion_log` under `source='macro'` is where a bad symbol will show up.
- 33 new tests; suite 709 pass, ruff clean. Mutation-verified three ways: labelling KOSPI
  `before_open` fails 6 tests, putting every series on the brief's 隔夜 line fails 2, and
  desynchronising the server mirror from the harvester fails 2.
