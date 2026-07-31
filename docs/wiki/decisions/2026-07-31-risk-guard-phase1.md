---
title: Risk Guard Phase 1 built — M1 light, M2 stops, M2b settlement, rg_* MCP tools
type: decision
slug: 2026-07-31-risk-guard-phase1
date: 2026-07-31
attributed_to: [niko, claude-agent]
belongs_to: [risk-guard]
source: chat
status: active
tags: [risk, stop-loss, cron, mcp, telegram, schema, deviation]
related: [risk-guard, system-architecture, 2026-06-03-reenable-scheduled-harvest-crons]
---

## Context

[niko] handed over `RISK_GUARD_PRD.md` v1.1 and asked for it to be implemented against the
existing repo. The PRD defines its own phase order with per-phase acceptance (§7), so the
delivery is **Phase 1 exactly as §7 lists it**: schema + M1 + M2 + M2b + Telegram bot +
the five `rg_*` MCP tools + the held_pct snapshot. Phases 2–4 are not built.

## The constraint that shaped the build

Checked before writing any scorer: **a TAIEX-only M1 fails the 7/07 acceptance row.**
7/07 was −2.31% and closed under MA20 — subitem 1 (+1) and subitem 5 (+1) give score 2,
which is 🟢 green, while §7 demands ≥yellow (≥3). Reaching yellow needs breadth, margin,
or futures scoring, and **none of the three existed in the DB**: `raw_twse_margin` is
per-stock, `raw_twse_index` has no advance/decline counts, and TAIFEX was not ingested
at all.

All three were verified reachable before committing to the design:

- **Breadth** — TWSE `MI_INDEX?response=json&date=YYYYMMDD&type=MS` returns a table
  titled `漲跌證券數合計`. Confirmed live for 7/07, 7/16, 7/17, 7/24, 7/28, 7/29, 7/30.
  7/07 reads 128 up / 892 down on the 股票 column → ratio 0.126, which scores +2 and
  lifts 7/07 to yellow. Backfillable per date.
- **Futures** — TAIFEX `futContractsDateDown` POST returns Big5 CSV. 7/30 gives
  臺股期貨 / 外資及陸資 / 多空未平倉口數淨額 = **−81,017** → +2. Backfillable per date.
- **Margin** — needs no new feed; `SUM(margin_balance) GROUP BY date` over the existing
  per-stock rows gives the market aggregate.

Recording this because the alternative — tuning thresholds until the acceptance table
went green without the data behind it — would have produced a scorer that recognises
2026-07-24 rather than one that recognises the pattern.

## Decisions

**1. The light is a state machine, not `f(score)`.** PRD §5 v1.1 adds hysteresis that
the score→light table alone does not express. Two replay rows exist specifically to
catch a stateless implementation: 7/30 (−0.26%, must stay red) and 7/31 (+8.0%, must not
go green). Implemented as two pure functions, `score_day(metrics)` and
`resolve_light(score, prev_light, ctx)`, with DB access outside both. Downgrades toward
green are gated (紅轉黃 needs 2 sessions holding the prior low + no new penalties;
黃轉綠 needs an MA20 reclaim or 3 higher closes); upgrades to red are immediate; red
cannot skip yellow.

**2. Code is split across two folders, against the letter of PRD §2.** The PRD pins
everything to `/riskguard`. Vercel's Root Directory is `mcp_server/`, so a repo-root
package is not in the deployed bundle and the MCP tools could not import it. Pure logic
therefore lives in `mcp_server/api/rg/` (following the existing `api/quant/` precedent)
and the cron/fetch/write half in repo-root `riskguard/`. The `rg_` prefix and the
"no new MCP server" requirement are both honoured.

**3. Cron is GitHub Actions, not Vercel Cron — M1 lands ~16:40, not 15:30.** This repo
has no Vercel cron (`mcp_server/vercel.json` has only rewrites); everything scheduled
already runs on `daily_harvest.yml` at 16:30 Taipei. Appending the post-close step there
inherits `gssencmode=disable` and the Telegram secrets — both of which would otherwise
have to be re-derived. See
[[2026-06-03-reenable-scheduled-harvest-crons]]. The pre-market run gets its own
workflow at 00:30 UTC. For output whose subject is "what to do at tomorrow's open", the
one-hour delay is not load-bearing.

Unlike the briefs and dashboards in that workflow, the Risk Guard step is **not**
`continue-on-error`: a silent failure there is a stop-loss alert that never fired. The
pipeline isolates its own stages internally and exits non-zero only after every stage
has run.

**4. Delivery is guaranteed, not assumed.** Alerts are written to `rg_alerts` before being
sent, so a Telegram outage costs the send and not the record. That ordering is only a
safety net if something retries: `flush_undelivered()` re-sends undelivered `critical`
alerts (bounded to 3 days — a stop breached two weeks ago is stale advice) and runs at the
end of both post-close and pre-market. De-dup keys on `(date, kind, dedup_key)`, where
dedup_key is the ticker, or the settlement date, or the new light — two shortfalls on
different dates are two alerts, not one suppressed.

**4b. A position with no price is reported, not skipped.** `raw_twse_ohlcv` covers the
classified universe plus the benchmark, not everything in `rg_positions`. `stops.evaluate`
correctly stays silent on a missing price, but "0 stop alerts" and "your stop was never
checked" must not look identical — an unpriced active position now raises `stop_unchecked`.

**5. Missing data is never scored as calm.** A subitem whose feed failed scores 0 and is
stamped `data_missing`; the light message says so out loud. Substituting a neutral value
would read as "calm", and calm is the dangerous default for a system whose only job is
to warn.

**6. The two review gates are tests, not prose.** PRD §5-M7 and §6 state as *code-review
acceptance conditions* that the 節律 veto and the 兵法 quote table never enter a scoring
or triggering path. `tests/test_rg_checklist.py` asserts this structurally via
`inspect.getsource` over `scoring`, `light` and `stops`, and asserts that no checklist
output contains buy phrasing. A review condition that lives only in prose survives
exactly as long as the reviewer's attention.

**7. `/watch` now also feeds Risk Guard's 自選 list.** The existing handler refused any
ticker outside the 26-name classified universe. PRD §4 seeds the watch list with names
like 8299 that have no supply-chain row, and a name you cannot watch is a name whose
stop you cannot set. `/watch` writes `rg_positions` unconditionally and the classified
`watchlist` only when a `dim_supply_chain` row exists.

## Pre-existing issue found, not fixed

`sql/003_rls.sql` ends with `REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
FROM mcp_viewer` (line ~148) placed **after** its own watchlist INSERT/UPDATE grant
(line ~113). Re-running `apply_schema.py --rls` therefore strips the write grant that
`w_add`/`w_remove` depend on — and would strip `rg_journal`'s too. `sql/018_riskguard.sql`
carries a note; the ordering bug in 003 is left alone as out of scope.

`018_riskguard.sql` has been added to `apply_schema.py`'s hardcoded `sql_files` list.
(`014_dim_ticker_classify.sql`'s absence from the default list is deliberate, not drift —
it GRANTs to `mcp_viewer` and so can only run after `003` has created the role.)

Note the apply order this produces with `--rls`: `… 018, 003, 014`. Because `003`'s
blanket REVOKE runs last, **`sql/018_riskguard.sql` must be re-applied after any `--rls`
run** or `rg_journal_add` loses its INSERT grant.

## Verification

- `pytest -q` → **202 passed, 5 skipped** (was 112 passed; the 5 skips are the
  pre-existing DB tests — `psycopg_pool` is not installed locally).
- 85 new tests across `test_rg_scoring.py`, `test_rg_stops.py`, `test_rg_checklist.py`,
  `test_rg_sources.py`, `test_rg_pipeline.py`. Source parsers are tested against captured **real** 2026-07-30
  payloads, not mocks of our own assumptions.
- Focused `ruff check` clean apart from `UP045`/`B905`, which match the surrounding
  repo convention (`db_v2.py` alone carries 43 `UP045`).
- Import graph verified along the bare-import path the Vercel bundle uses
  (`from rg import ...` with `mcp_server/api` on `sys.path`).

**Not yet verified — needs [niko] with DB credentials.** There is no `.env` in this
working copy, so the replay acceptance table has never been run against live data:

```bash
python apply_schema.py
python -m riskguard.replay --start 2026-06-01 --end 2026-07-31          # report only
python -m riskguard.replay --start 2026-06-01 --end 2026-07-31 --write  # persist
```

`raw_twse_index` holds 94 sessions back to 2026-02-25 (verified via `q_index_history`),
so MA60 is computable for the whole replay range; it does have gaps (5/26–6/04, 7/10) and
ends at 7/30. The replay prints
`data_missing` per row and refuses to count an unscored acceptance row as a pass.

## Open

- 7/24 (−2.67%) is the acceptance row most at risk of landing at 4 (yellow) instead of
  red; it depends on breadth/margin/futures values not yet checked. Calibrate in
  `mcp_server/api/rg/config.py` via replay — never by special-casing a date.
- M4's intraday worker needs a host decision the PRD leaves open
  (fly.io / GitHub Actions / local). Deferred with Phase 2.5.
