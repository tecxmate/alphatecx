---
title: Six live-tested connector defects — grants, identity, delivery, freshness
type: decision
slug: 2026-08-10-live-connector-defects
date: 2026-08-10
updated: 2026-08-10
attributed_to: [niko, claude-agent]
belongs_to: [mcp-server, paid-connector-deploy, risk-guard]
source: chat
status: active
tags: [rls, grants, migrations, identity, telegram, freshness, idempotency, live-testing]
related: [2026-08-09-risk-profile-personalization, paid-connector-deploy, risk-guard, session-state]
---

## Context

[niko] exercised the live connector end to end — every read tool, both watchlist writes, the
journal write, and the profile loop — and reported what actually failed. That is the first test
pass against production data rather than mocks, and it surfaced six defects that the 453-test
suite could not have caught: five of them are environment- or deployment-shaped, and the sixth is
a contract the tests asserted from the wrong side.

## The defects and their root causes

**1 & 5 — `permission denied` on valuation, dividend, and the trading calendar.** One root cause,
two symptoms. `sql/003_rls.sql` grants `mcp_viewer` SELECT on an **enumerated list** of tables, so
every table created by a later migration needs its own grant. Two things went wrong: `010`
(`lead_lag`) and `011` (`raw_twse_valuation`, `raw_twse_index`) ship **no grant block at all**;
`015` (`market_holidays`), `016` (`raw_twse_dividend`) and `017` (`raw_finmind_*`) grant correctly
but behind `IF EXISTS (… rolname = 'mcp_viewer')` — and `apply_schema.py` runs them in the **base
pass, before 003 creates that role**, so the guard is false and the grant silently no-ops. Unlike
`018/019/020/021/022/023`, none is re-appended after 003, so it never lands.

This is a **different trap** from the one this repo already knew about. The documented trap is
003's closing blanket `REVOKE INSERT, UPDATE, DELETE`, which strips *write* grants made before it.
This one is about role **creation** order and costs *read* grants. Both produce the same
signature: a fully-populated table that the server cannot read.

**2 — the personalization loop was inert.** `set_my_risk_profile` answered `saved: false` every
time. The risk layer keys on `customers.id`, but neither owner path supplied one: the
URL-as-secret mount (`/mcp/<token>/`, what Claude Code and the Desktop bridge use) never set
`current_customer` at all, and the OAuth owner login resolves to the literal subject `"owner"`,
which the profile tools special-cased into "can't persist". The loop the server instructions lean
on — call `my_profile`, ask, save, tailor — was therefore dead for the operator, the connector's
heaviest user. Customer sessions were unaffected; this was owner-only.

**3 — every alert stuck at `pushed: false`.** An interaction between two deliberate decisions.
`TELEGRAM_TOKEN` is intentionally unset on the Zeabur `cron` service so a double run cannot
double-buzz ([2026-07-31 scheduled work](2026-07-31-scheduled-work-on-zeabur.md)). But `_emit`
writes the row *before* sending, so the token-less run records the alert and cannot deliver it —
and the GitHub Actions run, the one that **does** hold the token, then hit the same-day de-dup
index, logged "already recorded", and returned **without ever sending**. `flush_undelivered`
sweeps only `severity='critical'`, so anything softer was lost outright. Whichever service wins
the race decides whether the alert is ever delivered.

**4 — the margin subitem scored blind every day.** `build_metrics` required margin data dated
exactly `as_of`. TWSE publishes 融資融券彙總 *after* the 16:30 harvest window, so at post-close the
newest stored balance is structurally at least one session behind — the condition could never be
satisfied. The strictness was deliberate and its reasoning was sound (the 2026-07 harvest gap
handed June's balance to July sessions), but the rule it produced was unsatisfiable rather than
strict. Note this is the *read* side of the same blindness the harvest gap caused: the table was
full this time.

**6 — `w_remove` was not idempotent.** A second removal returned `ok: false`, contradicting its
own docstring. The UPDATE matching no row means two different things — already archived, or never
on the list — and conflating them made a caller checking `ok` read a completed archive as a
failed one.

## Decisions

- **`sql/024_read_grants_backfill.sql`** is now the single place that re-grants every table the
  read path touches and 003 does not cover. Re-appended after 003 by `apply_schema.py`, applied
  standalone by `apply_delta.py`. Deliberately **absent from the base list**: every statement is
  role-guarded, so a base pass would be a pure no-op — the same mistake that caused the bug.
- **`apply_delta.py` now reads the privileges back** and exits non-zero if `mcp_viewer` still
  cannot SELECT. A grant that runs, reports nothing and does nothing is exactly this bug class, so
  "applied ✓" without a read-back is worthless here.
- **`owner` becomes a reserved `customers` id** (`sql/025`) rather than a second table, so
  `get_risk`/`set_risk_profile` work unchanged and the column-scoped UPDATE grant from `022/023`
  already covers the write. `secret_hash` is the literal `'-'` — not a 64-char sha256 hex, so
  `authenticate()`, which looks callers up *by that hash*, can never match it; `status` is
  `suspended` for the same belt-and-braces reason. The owner credential stays the shared
  `OAUTH_PASSWORD` and the URL secret. The auth gate now names the subject on the URL-secret path;
  metering is unaffected because `_stamp` skips `sub="owner"` either way.
- **`_emit` retries the send when the row it collided with is unpushed.** Whoever gets there
  holding a working token finishes the delivery; a run without one still changes nothing. This
  makes the write-then-send order safe regardless of which service wins the race — and, as a
  consequence, giving `cron` a token would no longer risk a double buzz, though we are **not**
  doing that now (GH Actions remains the path that alerts on failure).
- **Margin staleness is bounded, not forbidden** — `MARGIN_MAX_LAG_SESSIONS = 3`, counted in
  **trading sessions** off the TAIEX series so a weekend or Lunar New Year break is not mistaken
  for a stalled feed. `_session_lag` returns `None` (not 0) when the lag is unmeasurable, so
  callers fail closed. The session actually used is surfaced as `margin_as_of` in the subitem's
  inputs, so "資料缺漏" can be told apart from "a day behind, which is normal".
- **`w_remove` distinguishes the two cases**: already archived is `ok: true` with
  `already_archived: true`; never on the watchlist is `ok: false`.

## Consequences

- **The two migrations must be applied to the live Zeabur DB before any of this takes effect** for
  #1, #2 and #5. Nothing in the code change helps until `apply_delta.py` runs against the owner
  DSN. #3, #4 and #6 are code-only and ship on the next push.
- **Replay determinism shifts for #4.** Historical sessions that scored `margin: data_missing`
  will now score the subitem where a balance within the lag bound exists. That is a correction —
  they were blind, not neutral — but `riskguard.replay` output before and after this change is not
  comparable.
- The `trial` status remains a latent lockout (`VALID_STATUSES` advertises it; both gates compare
  against `active` only), and a DB blip on the read path still presents to a paying customer as
  402 `account_inactive`. Both were surfaced in the same review and are **not** fixed here.

## Open

- Rotate/decommission the legacy Neon project — a credential leaked to a terminal on 2026-08-09.
- Decide whether `flush_undelivered` should sweep beyond `critical` now that we know a token-less
  run records everything. Left alone for now: the `_emit` retry covers the same-day case, and
  yesterday's undelivered warn is stale advice.
