---
title: Paid connector — deploy checklist
type: topic
slug: paid-connector-deploy
date: 2026-08-09
updated: 2026-08-09
attributed_to: [antigravity-agent]
belongs_to: [commercial-productization, system-architecture]
source: chat
status: active
tags: [deploy, runbook, zeabur, oauth, billing, metering, mcp]
related: [commercial-productization, infrastructure-accounts, 2026-07-31-mcp-server-vercel-to-zeabur, 2026-08-08-commercialization-direction]
---

Runbook to take the paid-connector work (productization Layers 0–2 + metering + billing) live. Until
every step here runs, the code sits dormant on `main` — nothing about a push changes production
([the Zeabur `mcp` service is manual-deploy, CLI-uploaded](2026-07-31-mcp-server-vercel-to-zeabur.md)).

**Run order matters:** migrate the DB first (code tolerates an old schema, but the grants must exist
before a customer hits the server), then deploy, then provision.

## 0. Preconditions

- On `main`, clean tree, suite green (`​.venv/bin/python -m pytest -q` → 427 pass).
- Root `.env` has `DATABASE_URL` (owner) and `MCP_VIEWER_PASSWORD` — `apply_schema.py` reads both.
- The Zeabur `mcp` service already has `OAUTH_SIGNING_KEY` + `OAUTH_PASSWORD` (shipped with the OAuth
  work) and `MCP_DATABASE_URL` + `MCP_BEARER_TOKEN`. Confirm they're set.

## 1. Apply the DB migrations (owner)

From the repo root, against the Zeabur Postgres:

```bash
python apply_schema.py --rls        # needs MCP_VIEWER_PASSWORD in env
```

This lands, in the right order, the new tables + the grants that 003's blanket REVOKE would otherwise
strip (all re-appended after 003): `019` customers (SELECT), `020` usage_monthly (SELECT/INSERT/UPDATE),
`021` watchlist write-grant restore, `022` customers `UPDATE(status)`. Idempotent — safe to re-run.

**Verify** (as `mcp_viewer`):
```sql
\dp customers        -- expect SELECT + UPDATE(status,updated_at) for mcp_viewer
\dp usage_monthly    -- expect SELECT, INSERT, UPDATE for mcp_viewer
select count(*) from customers;   -- table exists
```

## 2. Set the new env vars on the `mcp` service (Zeabur)

`zeabur variable create` hangs without `-i=false` (non-TTY). Optional ones:

- `ALPHATECX_DISCLAIMER` — override the default compliance line on every response (else the built-in
  English default ships).
- `LEMONSQUEEZY_WEBHOOK_SECRET` — **only if** turning on self-serve billing now (see §6). Omit while
  private; the webhook simply refuses every call (fails closed) until it's set.

## 3. Deploy the server

CLI-uploaded services can't `redeploy` in place (`CANNOT_REDEPLOY_INPLACE`):

```bash
zeabur deploy --service-id 6a6c4b0ed3dbd8abbc44eebb   # confirm the id in the Zeabur dashboard
```

First boot pulls the image (~2 min); health checks before that read 502 and look like a crash loop —
check `zeabur deployment log -t runtime` before diagnosing.

**Verify** the disclaimer shipped: any tool response now carries `_disclaimer`. Owner access is
unchanged (URL-secret `/mcp/<MCP_BEARER_TOKEN>/` **with trailing slash**, or bare `/mcp` via OAuth).

## 4. Provision a customer (owner)

```bash
python scripts/provision_customer.py --email investor@example.com --plan private --quota 5000
# prints the connector secret ONCE — copy it, it is never stored in plaintext
```

`--quota` omitted ⇒ unlimited. Hand the secret to the customer; they paste it as the password on the
OAuth authorize screen (bare `/mcp` cloud-connector flow, which is what claude.ai web/mobile use).
Give them the client-facing steps in [`docs/CLIENT-CONNECT.md`](../../CLIENT-CONNECT.md).

**Manual client ops** (the private wire-money-then-flip-access loop, no raw SQL):
```bash
python scripts/manage_customer.py list                        # everyone + usage this month
python scripts/manage_customer.py suspend client@example.com  # non-payment / end of term
python scripts/manage_customer.py activate client@example.com # money arrived -> back on
```

## 5. Verify multi-tenancy + metering end-to-end

- Customer authenticates → token carries `sub=<customer_id>` (not `owner`).
- A few tool calls → `select calls from usage_monthly where customer_id='<id>';` increments.
- Suspend test: `python scripts/manage_customer.py suspend <email>` → the customer's next session is
  refused **402** (and a refresh is refused too — the gate re-checks status per session).
- Quota test: set `monthly_quota` below current `calls` → next session **429**.

## 6. Billing (optional — only for self-serve paid signups)

While **private, skip this** and keep hand-provisioning (§4). To turn on:

1. Create the product/subscription in Lemon Squeezy; pass our `customer_id` as `custom_data` at
   checkout (email is the fallback match).
2. Set `LEMONSQUEEZY_WEBHOOK_SECRET` on the service (§2) and redeploy (§3).
3. Point the LS webhook at `https://<host>/billing/lemonsqueezy` (subscription events).
4. **Verify:** a test `subscription_created` flips the matched customer to `active`; a cancel →
   `suspended`. Bad signature → 401; unknown customer → 200 (ack, no-op).

## Rollback

- Vercel + Neon remain live rollback targets for the pre-Zeabur server (see the Zeabur move decision);
  the paid-connector code is additive and back-compat, so rolling back the deploy is the whole undo.
- The migrations are additive (new tables + narrow grants); nothing drops or alters existing data, so
  there is no destructive DB step to reverse. A suspended customer can be reactivated with
  `update customers set status='active' where id='…';`.

## Gotchas (don't re-learn)

- MCP endpoint is `/mcp/<token>/` **with the trailing slash** — `/mcp/<token>` 307-redirects.
- `apply_schema.py` re-appends 018/019/020/021/022 **after** 003 on purpose — 003 ends with a blanket
  `REVOKE INSERT, UPDATE, DELETE ON ALL TABLES` that strips any write grant made before it.
- The billing webhook writes `customers.status` through the read pool via a **column-scoped** grant —
  no owner DSN is (or should be) set on the internet-facing service.
