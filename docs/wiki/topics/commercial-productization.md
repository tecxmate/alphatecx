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
- **Layer 1 (metering) not started** — deferred until the connector-vs-app call is locked.

## Handoff — how to continue (for any agent picking this up)

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
**Layer 1 (metering) is deliberately not built** until that is locked, because metering only matters
once charging. When ready, Layer 1 = ContextVar in the `auth_gate` middleware (`index.py`) → count
in `_stamp()` → `usage_monthly` table → session gate (402/429) + soft quota flip.

**Compliance gate (blocking before taking money):** investment-advice licensing (RIA / SFC-type) —
lawyer read required; the connector "data provider, not advisor" framing is the lower-liability posture.

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
