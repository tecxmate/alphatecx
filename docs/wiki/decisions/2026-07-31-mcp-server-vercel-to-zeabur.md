---
title: MCP server moved from Vercel to Zeabur
type: decision
slug: 2026-07-31-mcp-server-vercel-to-zeabur
date: 2026-07-31
attributed_to: [niko]
belongs_to: [mcp-server, system-architecture]
source: chat
status: active
tags: [deploy, zeabur, vercel, security, mcp]
related: [2026-07-31-migrate-neon-to-zeabur, mcp-server, system-architecture, infrastructure-accounts]
---

## Context

The Neon → Zeabur database migration earlier the same day closed with one item open: the Vercel
deployment's env vars still pointed at Neon, so the MCP server kept reading the old database. That
migration also logged an unmitigated risk — Zeabur's Postgres has TLS disabled outright
(`sslmode=require` is rejected), so every client reaching it over the public TCP proxy at
`8.209.197.81:32046` sends credentials in cleartext across the internet.

While retrieving the connection string for the pending Vercel env switch, [niko] asked whether the
server could simply be hosted on Zeabur too — "maybe host another in my zebuar no need in vercel
anymore" — then approved implementation.

## Decision

Host the MCP server as a second Zeabur service in the same `alphatecx` project as `postgresql`,
and drop the Vercel env switch rather than perform it. Live at
`https://alphatecx-mcp.zeabur.app`, service `6a6c4b0ed3dbd8abbc44eebb`.

## Rationale

The convenience framing undersells it. Co-locating the two services puts the database connection on
the project's private network — the server now reaches Postgres at
`postgresql.zeabur.internal:5432`. That does not mitigate the cleartext-credentials risk on the
server's path; it removes that path from the public internet entirely. The pending cutover item
stopped being something to fix and became something to delete.

The risk is **not fully retired**: the GitHub Actions harvesters still write over
`8.209.197.81:32046` in cleartext, because they run outside Zeabur. Only the read path moved.

Vercel and Neon both stay live as rollback.

## Consequences

- `mcp_server/requirements.txt` gained `uvicorn` and, more importantly, a `mcp<2` ceiling.
  `mcp` on PyPI is now **2.0.0**, which removed `mcp.server.fastmcp` that `index.py` imports.
  Vercel's build predated the release; a fresh container build resolves latest and dies at import.
  This was the single likeliest first-deploy failure and was pinned before it could happen.
- New `mcp_server/api/app.py` composes the two FastAPI apps. Vercel ran `index.py` and `bot.py` as
  separate functions with `vercel.json` rewrites steering `/bot/*`; one uvicorn process cannot.
  `index.py` and `bot.py` are deliberately unmodified so Vercel stays a working rollback target.
- `security.py` now exempts `/bot/*` from the URL-secret gate. This is not a weakening: on Vercel
  those routes were a separate function that never reached the middleware. The webhook authenticates
  on Telegram's `X-Telegram-Bot-Api-Secret-Token` header and then gates on the owner's `chat_id`.
  Verified: correct secret → 200, wrong secret → 403, absent → 403, and `/botevil` → 404.
- `mcp_viewer`'s password was rotated (its old value was not recoverable from Zeabur's service
  vars) and root `.env` re-synced, since `apply_schema.py --rls` reads `MCP_VIEWER_PASSWORD`.
  Safe because Vercel was still pointed at Neon, so nothing depended on the Zeabur-side value.
- **`MCP_BEARER_TOKEN` is new.** The old one lived only in Vercel's env and was unreachable without
  `vercel login`. Since the host changed, every consumer URL had to change regardless. The Telegram
  webhook secret is likewise new.
- Telegram webhook re-registered from `alphatecx-v2-mcp.vercel.app` to the Zeabur host. Rolling back
  means calling `setWebhook` again with the Vercel URL and its original secret.
- `DATABASE_URL` is deliberately **not** set on the service — same read-only boundary the original
  Vercel deploy established. The bot gets `BOT_DATABASE_URL` (root) because it writes.

## Non-goals

`src/quant/*.py` and `mcp_server/api/quant/*.py` are mirrored copies that exist *only* because
Vercel's Root Directory was `mcp_server/`. Container hosting dissolves that constraint, so the
duplication becomes removable — but deliberately not as part of this move. Same for `db_v2.py`'s
`max_size=3` pool, sized for concurrent serverless invocations and now merely conservative.

## Gotchas worth not re-learning

- The MCP endpoint is `/mcp/<token>/` **with the trailing slash**. `/mcp/<token>` 307-redirects and
  `/mcp/<token>/mcp` returns 404 — `web/README.md` documented that wrong suffix and was corrected.
- `zeabur variable create` hangs forever without `-i=false`; the interactive default waits on a
  prompt that never renders in a non-TTY.
- CLI-uploaded services cannot `zeabur service redeploy` — it fails `CANNOT_REDEPLOY_INPLACE`,
  which requires a bound GitHub repo. Re-run `zeabur deploy --service-id ...` instead.
- First boot pulls a ~94 MB image and took 1m46s. Health checks started before that will read 502
  and look like a crash loop; check `zeabur deployment log -t runtime` before diagnosing.

## Provenance

- Discussed and executed on 2026-07-31 between [niko] (owner) and [claude-agent] (agent).
- Verified live: 44 tools listed over the MCP protocol (paginated `tools/list`), `sc_data_status` returning 608,082
  `raw_twse_t86` rows, `sc_sector_momentum` fresh as of 2026-07-31 — all read over the private
  network. `pytest -q` 211 passed; focused `ruff check` clean.
