---
title: Console authentication
type: topic
slug: console-auth
date: 2026-08-16
updated: 2026-08-16
attributed_to: [claude-agent]
belongs_to: [system-architecture, mcp-server]
source: synthesis
status: active
tags: [auth, console, security, cloudflare]
related: [infrastructure-accounts, paid-connector-deploy]
---

## Summary

How the human-facing console (`/d/<token>/`) is protected, why that is now a
different secret from the MCP API, and the runbook for putting real login in
front of it with Cloudflare Access.

## The problem this fixes

`security.py` gated **five** prefixes on one secret: `/mcp` (the API — 49 tools,
several of which write) and `/g`, `/d`, `/h`, `/t` (the console). One string.

So **the dashboard link was the API credential.** Showing the console to a
customer, a co-founder, or anyone in a screenshot also handed them the ability
to call every tool, including `w_add`, `w_remove`, `rg_journal_add` and
`set_my_risk_profile`. Nothing about the console URL suggested that.

URL-as-secret has the usual costs on top: the token rides in browser history,
`Referer` headers, proxy and server logs, and any shared screenshot; there is no
per-person identity; and revocation means rotating one shared string for
everyone at once.

## What changed (2026-08-16)

`CONSOLE_TOKEN` — a second, optional environment variable.

- Unset, it falls back to `MCP_BEARER_TOKEN` and behaviour is **byte-identical**
  to before. The split cannot break a running deploy; it only allows a safer one
  to be configured.
- Set, `/d`, `/g`, `/h`, `/t` gate on it while `/mcp` keeps gating on
  `MCP_BEARER_TOKEN`. Neither token opens the other's surface.

Verified live through the real ASGI app with both tokens set:

| Request | Result |
|---|---|
| API token on `/mcp/…` | 200 — reachable |
| console token on `/mcp/…` | **401** — denied |
| API token on `/d/…` | **404** — denied |
| console token on `/d/…` | 200 — allowed |

The console token is denied on `/mcp` with **401, not 404**, because the path
falls through to the bare-`/mcp` OAuth-protected mount rather than the
URL-secret one. Denied either way; worth knowing so the response code is not
mistaken for a routing bug.

`tests/test_security.py::TestConsoleTokenSplit` pins all of it, including the
fallback — that last case is what makes the change safe to ship before anyone
configures anything.

## Runbook — real login via Cloudflare Access

[niko] owns `tecxmate.com` on Cloudflare, which is the prerequisite: Access
needs a hostname on a zone you control, so `*.zeabur.app` cannot be used.

**Design: give the console its own hostname.** Do *not* put Access in front of
`alphatecx-mcp.zeabur.app` — MCP clients and the Telegram webhook are not
browsers and will break the moment Access challenges them. A second hostname on
the same Zeabur service avoids every path-carve-out mistake.

1. **Zeabur** → `mcp` service → Networking → add custom domain
   `console.tecxmate.com`. Leave `alphatecx-mcp.zeabur.app` in place and
   untouched; that stays the API/webhook hostname.
2. **Cloudflare DNS** → `CNAME console → <the target Zeabur gives you>`, proxied
   (orange cloud). Proxying is required — Access only works on proxied records.
3. **Cloudflare Zero Trust** → Access → Applications → Add → Self-hosted:
   - Domain `console.tecxmate.com`, path left blank (whole hostname).
   - Policy: Allow → *Emails* → the operator addresses. Add a second identity
     provider (Google/GitHub) or leave the default one-time PIN over email.
4. **Set `CONSOLE_TOKEN`** on the Zeabur `mcp` service to a fresh random value,
   so the console URL is no longer the API key. Restart the service.
5. Browse `https://console.tecxmate.com/d/<CONSOLE_TOKEN>/`.

Result: two independent controls. Cloudflare SSO decides *who* may reach the
hostname; the console token is what the app itself checks. Losing either one
alone does not expose the console, and neither exposes the MCP API.

**Revocation** becomes removing an email from the Access policy — instant,
per-person, and it leaves the audit log Cloudflare keeps of every access.

## Known limitation, and the optional next step

The token is still in the URL. Access is a second gate in front of it, not a
replacement for it, so browser history and screenshots still carry a secret —
one that now only opens the console, which is the substantive improvement.

To remove it entirely, the app would verify Cloudflare's `Cf-Access-Jwt-Assertion`
header (a signed JWT, validated against the team's JWKS endpoint) and serve the
console at a plain `/d/` with no token segment. That needs a JWT library in
`mcp_server/requirements.txt` — currently absent, and every dependency there
ships in the deployed image — plus a JWKS fetch and cache. Deferred as its own
piece of work rather than smuggled into the token split.

Helpfully, `console.NAV` links are **relative** (`./market`, not
`/d/<token>/market`), so moving the console from `/d/<token>/` to `/d/` is
mostly free. A few absolute asset references (`/d/{token}/dashboard.css` in
`graph_view.py`) would need updating.

## Alternative considered

A signed session cookie over the existing `customers` table — `oauth.py` already
has HMAC `issue()`/`verify()` with TTLs, and `customers` already stores `email`,
`secret_hash` and `status`, so revocation is a column that exists. Roughly 150
lines plus CSRF and login rate-limiting.

Rejected as the *first* move only because [niko] owns a Cloudflare zone, which
makes Access strictly better: real SSO, an audit log, and no authentication code
to own or get wrong. The cookie remains the right answer if the console ever
needs per-customer views rather than operator-only access, since Access
authenticates people while `customers` identifies tenants.
