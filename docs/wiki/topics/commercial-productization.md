---
title: Commercial productization — payments, multi-tenancy, metering, disclaimer
type: topic
slug: commercial-productization
date: 2026-08-08
updated: 2026-08-08
attributed_to: [niko, antigravity-agent]
belongs_to: [alphatecx]
source: chat
status: active
tags: [commercialization, payments, stripe, multi-tenant, oauth, metering, compliance]
related: [2026-08-08-commercialization-direction, system-architecture, brian, niko]
---

Plan for turning alphatecx into a paid product that sells a **subscription to the data + tools**
(model A — remote MCP connector), decided by [niko]. [brian] is pushing app-first; the
connector is the chosen surface for now. See
[2026-08-08-commercialization-direction](../decisions/2026-08-08-commercialization-direction.md).

## Payments (Taiwan customers, Vietnamese/Taiwanese business)

- **Stripe cannot be the merchant from Vietnam or Taiwan.** Neither VN nor TW is a self-serve
  Stripe country for *receiving* payouts. TW-issued cards can *pay* through Stripe fine — the block
  is on the entity that collects. (Verify at signup; support shifts.)
- **Chosen route: Merchant of Record (Lemon Squeezy / Paddle / Polar).** They are the legal seller,
  handle global tax/VAT/invoicing, and pay out to a VN/TW bank via wire/Payoneer. ~5% + fees.
  Sidesteps the VN/TW-can't-open-Stripe blocker. Integration = a checkout link + a webhook that
  flips account status.
- Alternatives: incorporate in **Singapore/HK** for native Stripe (later, if volume justifies the
  overhead); **local TW gateway** (ECPay 綠界 / NewebPay 藍新 / TapPay) needs a TW 統一編號 and only
  matters if going down-market to retail.
- **Local TW rails (Line Pay / JKoPay / ATM虛擬帳號) are not needed for the funded-investor segment** —
  they pay by international card / wire, and Line Pay's per-tx caps are wrong for high-ticket B2B.
- **Phase 0 = sell private, no payment code:** invoice + wire/Wise, hand-provision the account.
  Proves willingness-to-pay before any billing build.

## The single-tenant finding

The server is **single-tenant today**: `oauth.py` `_token_response()` hardcodes `sub="owner"` and
there is one shared `OAUTH_PASSWORD` — every authenticated caller is "owner". **Per-customer metering
is impossible until the server is multi-tenant.** Multi-tenancy is also the prerequisite for Phase 0
(distinct provisioned accounts). The token is already a stateless HMAC blob carrying arbitrary claims,
so making `sub` a real customer id is small.

**Reversal noted:** `oauth.py` deliberately stored nothing in Postgres because the split database
"returned different rows". The **Zeabur cutover collapsed that to one Postgres**, so the caveat has
expired — a small `customers` table is now safe, and this is a conscious reversal of the stateless-OAuth
decision.

## Status

- **2026-08-08 — Layer 0 + Layer 2 implemented** (not yet committed). New `sql/019_customers.sql`
  (customers table + role-guarded mcp_viewer SELECT/RLS), `mcp_server/api/customers.py`
  (pure secret helpers + fail-closed `authenticate` + owner-only `provision`),
  `scripts/provision_customer.py` (Phase-0 hand-provisioning CLI). `oauth.py` threads `sub` through
  code → access/refresh (default `"owner"` for back-compat). `index.py` gains `_resolve_subject`
  (owner password *or* customer secret → token subject, kept in the HTTP layer so `oauth.py` stays
  DB-free) and `_disclaimer` on every `_stamp()`. 20 new tests (`test_customers`,
  `test_oauth_multitenant`, `test_stamp_and_subject`); full suite 385 pass, 1 **pre-existing**
  unrelated failure (`test_news_watch::…second_cycle_alerts…`, date-dependent, fails on clean HEAD).
- **2026-08-09 — Layer 1 (metering) implemented.** `sql/020_usage.sql` (`usage_monthly` table +
  narrow `mcp_viewer` SELECT/INSERT/UPDATE grant, re-appended after 003 like 018 so the write grant
  survives the blanket REVOKE). `mcp_server/api/usage.py`: `record()` (best-effort upsert, never
  raises into a response) + `calls_this_month()` (fails **open** to 0). `index.py`: a
  `current_customer` ContextVar set by `auth_gate` after bearer verify (FastMCP runs the tool in the
  same task, so `_stamp` sees it — no 45-tool signature change); `_stamp` meters the call (owner and
  anonymous not counted); a `_customer_gate` per-session check → **402** if not active, **429** if
  `monthly_quota` reached. The gate **also closes the ≤1h residual** from the refresh fix — a
  suspended customer is now blocked at the read path per session, not only at refresh. 16 new tests;
  suite 405 pass, ruff clean.
- **2026-08-09 — pre-existing watchlist grant bug FIXED.** The `watchlist` INSERT+UPDATE grant
  (`003_rls.sql:119`) was stripped by the blanket `REVOKE` at `003_rls.sql:154` with no re-append, so
  after an `apply_schema.py --rls` run `w_add`/`w_remove` hit `permission denied` (same class as the
  018/rg_journal bug). Fixed by `sql/021_watchlist_grant.sql` (grant-only, role/table-guarded,
  idempotent), re-appended after 003 like 018/020. Re-running 003 couldn't fix it — it ends with the
  REVOKE — hence a separate file. RLS policies from 003 survive the REVOKE, so only the privilege
  needed re-issuing.
- **2026-08-08 — security review (AgentShield + security-reviewer agent).** AgentShield: Grade **A
  (98/100)**, 0 crit/high — but it only scans agent-configs, not the Python auth code, so the
  security-reviewer agent covered that. Result: **1 HIGH**, everything else clean (SQLi,
  fail-closed auth, hashing, credential enumeration, sub-forgery/privilege-escalation to owner,
  secret leakage, RLS grants all verified correct).
- **HIGH — refresh doesn't re-check status — FIXED 2026-08-09 (commit-pending).** `oauth.refresh()`
  re-minted a 1h access token **and a fresh 90-day refresh token** with no DB lookup, so a suspended
  customer whose client keeps refreshing (normal connector behaviour) stayed alive **indefinitely** —
  not "until token TTL" as the original commit said. **Fix:** the `/token` refresh grant in
  `index.py` now calls `_subject_still_valid(sub)` before re-minting — owner always passes (no DB;
  revoked by rotating `OAUTH_PASSWORD`), a customer must still exist and be `active`, and it **fails
  closed** (deleted/suspended/DB-blip ⇒ refused). `oauth.py` stays DB-free (`verify` is pure). This
  bounds a suspended customer to ≤ the 1h access-token TTL instead of forever; the residual ≤1h
  window on an already-issued *access* token closes fully with Layer-1's per-session gate. 4 new
  tests (`SubjectStillValidTests`). Still-open dead code: `customers.secret_matches()` unused (safe
  cleanup, not a vuln).

## Handoff — how to continue (for any agent picking this up)

**To take it live:** follow [paid-connector-deploy](paid-connector-deploy.md) — the step-by-step
runbook (migrate → set env → deploy → provision → verify → optional billing → rollback).

**Repo:** now under the `tecxmate` GitHub org — `github.com/tecxmate/alphatecx`. If your clone still
points at `nikolasdoan/alphatecx`, run `git remote set-url origin https://github.com/tecxmate/alphatecx.git`
(see [infrastructure-accounts](infrastructure-accounts.md) → GitHub repository). L0+L2 landed on
`main` as commits `141bb06` (feat) + `18d8a60` (wiki), pushed 2026-08-08.

**State:** L0+L2 code is on `main` but **dormant in production** — the Zeabur `mcp` service is
manual-deploy (CLI-uploaded, no repo binding), so a push changes nothing live. To activate:

1. `zeabur deploy --service-id <mcp>` — ships the code; the `_disclaimer` field goes live on every
   tool response at this point (review `ALPHATECX_DISCLAIMER` wording first).
2. Apply the migration to the Zeabur DB — `python apply_schema.py` (the customers grant needs the
   `--rls` pass ordering already wired in). Creates the `customers` table.
3. `python scripts/provision_customer.py --email <who>` — mint a customer + one-time connector
   secret. Until this runs, only the owner login (shared `OAUTH_PASSWORD`) works — i.e. today's
   behaviour. Order is safe either way: the code fails closed if the table is absent.

**Decision still open (do not skip):** connector-first ([niko]) vs app-first ([brian]) is `proposed`,
not settled — see [2026-08-08-commercialization-direction](../decisions/2026-08-08-commercialization-direction.md).

**Layer 1 (metering) is now built** (2026-08-09): `usage_monthly` + `usage.py` + the ContextVar/`_stamp`
counter + the `_customer_gate` session gate (402 inactive / 429 over-quota). To activate it you just
provision customers with a `monthly_quota` (NULL = unlimited); enforcement and counting are automatic.

**MoR billing webhook is now built** (2026-08-09): `POST /billing/lemonsqueezy` (`billing.py` +
`customers.set_status`/`get_by_email` + column-scoped `UPDATE(status)` grant `sql/022`). Lemon Squeezy
posts a subscription event, the HMAC signature is verified, and the customer's `status` flips
(active/on_trial → active; cancelled/past_due/etc → suspended). Ops: set `LEMONSQUEEZY_WEBHOOK_SECRET`,
point the LS webhook at `<host>/billing/lemonsqueezy`, and pass our `customer_id` as `custom_data` at
checkout (email is the fallback match). While **private** this can stay dormant — hand-provision with
`scripts/provision_customer.py` — and be switched on when self-serve paid signups are wanted.

**Compliance gate — set aside 2026-08-09 per [niko] (CEO):** current use is framed as **private, not a
commercial sale**, so the investment-advice-licensing (RIA / SFC-type) lawyer step is deferred as an
explicit risk call. It **reopens** if this ever becomes a public/commercial offering; the connector
"data provider, not advisor" framing remains the lower-liability posture.

## The plan (metering + disclaimer)

- **Layer 0 — multi-tenant identity (prerequisite).** `sql/019_customers.sql`:
  `customers(id, email, secret_hash, plan, status, monthly_quota, …)` +
  `usage_monthly(customer_id, yyyymm, calls)`. New `customers.py` (authenticate/provision).
  `/authorize` looks up the customer's *own* credential; `_token_response()` stamps `sub=customer.id`.
  Keep the shared `OAUTH_PASSWORD` as the owner/admin login + rollback target. **OAuth, not URL-secret**,
  because the audience is claude.ai web/mobile (cloud-connector-only).
- **Layer 1 — metering.** Middleware (`index.py:2114`) sets a `ContextVar current_customer` after
  `bearer_token_valid` (FastMCP runs the tool in the same asyncio task, so tools see it — no
  45-tool signature change). Count in `_stamp()` (`index.py:61`) → upsert `usage_monthly.calls`.
  Enforce twice: session gate in middleware (402/429 if suspended/over-quota) + soft flip in `_stamp`
  when the counter crosses quota.
- **Layer 2 — disclaimer.** One constant `_disclaimer` field added to the `_stamp()` dict, on every
  tool response. Cheapest liability reducer; pairs with (does not replace) the lawyer conversation.
- **Sequencing:** Layer 0 + Layer 2 first (unblocks Phase-0 private sales, disclaimer live) →
  Layer 1 metering (before charging) → MoR webhook (`/webhook/<mor>` → `customers.set_status`).
- **Open compliance gate (unchanged):** investment-advice licensing (RIA / SFC-type) — lawyer before
  taking money; connector = data-provider framing is the lower-liability posture.
