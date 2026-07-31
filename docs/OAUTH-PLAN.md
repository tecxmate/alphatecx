# OAuth for the MCP server — implementation plan

**Status:** not started. Written 2026-07-31 so a fresh session can execute without re-deriving.

**Why:** mobile and claude.ai-web can only reach the MCP server through a *cloud
connector*, and Anthropic's connector flow now requires OAuth. Claude Code and
Claude Desktop do not — both already work (Desktop via an `mcp-remote` bridge in
`~/Library/Application Support/Claude/claude_desktop_config.json`).

---

## Do these two things FIRST — the plan is unsafe without them

### 1. Decide which Postgres instance is authoritative

`postgresql.zeabur.internal:5432` and `8.209.197.81:32046` present the same
username (`root`) and database name (`zeabur`) but **return different rows**.
Measured 2026-07-31:

| Reached via | `rg_positions` active watch rows |
|---|---|
| `.env` → `8.209.197.81:32046` | 7 — `2327 2338 2344 2408 3374 6239 8299` |
| the deployed bot → `postgresql.zeabur.internal` | 4 — `2324 2344 2408 8299` |

`2324` exists in one and not the other. Not a caching artefact.

It matters here because **OAuth tokens need a home**. Put the table on the wrong
instance and you get auth that works from one surface and silently fails from
another — the same failure class that made `/status` return nothing, with no
error, for an hour.

It is also the likely cause of that `/status` bug: `cmd_status` reads
`rg_market_daily`, which has rows on the instance reachable from `.env` (it
returned a full 232-character reply when run locally) and evidently not on the
one the deployed bot reads. `if reply:` then skips the send — no message, no
error, nothing in the log.

**Check:** compare `SELECT count(*)` on `rg_market_daily`, `raw_twse_t86`, and
`rg_positions` across both hosts. Then confirm whether the harvesters
(`deploy/daily-chain.sh` and the GitHub Actions workflows, all using
`DATABASE_URL`) write to the same instance the `mcp` service reads. If they
don't, that is a data-integrity problem larger than OAuth.

### 2. Rotate the exposed credentials

All of these appeared in a chat transcript on 2026-07-31:

- Postgres superuser `root` / `Kq487X06...` — **internet-reachable** via
  `8.209.197.81:32046`, and that server has TLS disabled, so it also crosses the
  public internet in cleartext
- The Zeabur service `PASSWORD`
- `TELEGRAM_TOKEN` for `@ATecxbot`
- `MCP_BEARER_TOKEN` (`6FV0oIl2…`) — appears in the MCP URL and in server logs

Building an authorization server on top of compromised credentials produces the
appearance of security, not security. Rotate, then update: `.env`, the `mcp` /
`worker` / `cron` / `newswatch` Zeabur services, the GitHub Actions
`DATABASE_URL` secret, every MCP connector, and the Desktop bridge config.

---

## Current auth model (what changes)

`mcp_server/api/security.py` is **URL-as-secret**:

- `PUBLIC_PATHS = {"/", "/health"}`
- `TOKEN_PREFIXES = ("/mcp", "/g", "/d", "/h", "/t")` — each requires
  `/<prefix>/<MCP_BEARER_TOKEN>` as a *segment-aware* prefix match
- `/bot/*` is exempt; the webhook verifies Telegram's
  `x-telegram-bot-api-secret-token` header, then gates on the owner's chat_id
- Everything else → `404`, never `401`. The 404 is deliberate: it hides the surface.

`index.py:2221` does `app.mount(f"/mcp/{MCP_BEARER_TOKEN}", mcp_app)`, and the
FastMCP instance is `stateless_http=True, json_response=True` with
`streamable_http_path="/"`.

**That 404-on-everything behaviour is exactly what breaks connector registration.**
The client probes `/.well-known/oauth-protected-resource`, gets 404, falls back
to Dynamic Client Registration at `/register`, gets 404, and reports
"Couldn't register with Alphatecx's sign-in service."

---

## Design

Single user, so the authorization server can be minimal — but it must be a real
OAuth 2.1 + PKCE implementation, because the client is a real OAuth client.

### Keep both auth paths alive

**Do not remove URL-as-secret.** Serve the MCP app at two paths:

| Path | Auth | Used by |
|---|---|---|
| `/mcp/<MCP_BEARER_TOKEN>/` | URL-as-secret (today) | Claude Code, Desktop bridge |
| `/mcp/` | `Authorization: Bearer <access_token>` | cloud connectors, mobile |

Additive and independently revertable. Migrate later, or never.

### Endpoints to add

| Endpoint | Notes |
|---|---|
| `GET /.well-known/oauth-protected-resource` | `{"resource": "<base>/mcp", "authorization_servers": ["<base>"]}` |
| `GET /.well-known/oauth-authorization-server` | issuer, `authorization_endpoint`, `token_endpoint`, `registration_endpoint`, `code_challenge_methods_supported: ["S256"]`, `grant_types_supported: ["authorization_code","refresh_token"]`, `response_types_supported: ["code"]` |
| `POST /register` | Dynamic Client Registration. Accept client metadata, store `redirect_uris`, return `client_id`. Public client — no `client_secret`; PKCE is the protection. |
| `GET /authorize` | Single-user login form. Verify one password (`OAUTH_PASSWORD` env, **not** reused from any existing secret). Validate `redirect_uri` against what was registered. Issue a short-lived code bound to the PKCE `code_challenge`. |
| `POST /token` | `authorization_code` + `refresh_token` grants. Verify `code_verifier` against the stored challenge. |

All five must be added to `PUBLIC_PATHS` in `security.py`, or the existing
middleware 404s them before they ever run.

### Bare `/mcp` must return 401, not 404

For that mount only:

```
WWW-Authenticate: Bearer resource_metadata="https://<host>/.well-known/oauth-protected-resource"
```

That header is the signal that starts the whole flow. `/g`, `/d`, `/h`, `/t` and
the token-prefixed `/mcp/<token>` keep returning 404 — the surface stays hidden.

### Storage

One migration, applied to **whichever instance step 1 identifies as authoritative**:

```sql
-- sql/019_oauth.sql  (apply_schema.py has a HARDCODED file list — adding the
-- file is not enough, it must be added to that list or it silently no-ops)
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id     TEXT PRIMARY KEY,
    redirect_uris TEXT[] NOT NULL,
    client_name   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    token_hash     TEXT PRIMARY KEY,          -- sha256; never the raw token
    client_id      TEXT NOT NULL REFERENCES oauth_clients(client_id),
    kind           TEXT NOT NULL,             -- 'access' | 'refresh' | 'code'
    code_challenge TEXT,                      -- codes only
    redirect_uri   TEXT,                      -- codes only
    expires_at     TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_expiry ON oauth_tokens (expires_at);
```

Store **hashes**, never raw tokens — then a DB dump leaks nothing usable.
Codes expire in 60s, access tokens ~1h, refresh tokens long-lived.
`mcp_viewer` needs no grant; the app's own role writes this table.

### Files

| File | Change |
|---|---|
| `mcp_server/api/oauth.py` | new — router + store. Keep it a plain `APIRouter` so it is unit-testable without booting the whole app. |
| `mcp_server/api/security.py` | add the five well-known/oauth paths to `PUBLIC_PATHS`; add `bearer_token_valid(header) -> bool` |
| `mcp_server/api/index.py` | include the router; serve MCP at bare `/mcp`; 401 + `WWW-Authenticate` for that path only |
| `sql/019_oauth.sql` | above — **and add it to `apply_schema.py`'s hardcoded list** |
| `tests/test_oauth.py` | new |

Rough size: 300–400 lines plus tests.

---

## Tests to write first

The existing suite runs with **no network and no DB**, and must stay that way —
so the token store needs a seam tests can substitute.

- discovery documents are well-formed and self-consistent (issuer matches host)
- `/register` returns a `client_id` and persists `redirect_uris`
- `/authorize` rejects a `redirect_uri` that was not registered
- `/authorize` rejects a wrong password
- `/token` rejects a `code_verifier` that doesn't match the stored challenge
- `/token` rejects a replayed authorization code (single use)
- `/token` rejects an expired code
- bare `/mcp` without a bearer → **401**, carrying `WWW-Authenticate`
- bare `/mcp` with a valid bearer → passes
- `/mcp/<MCP_BEARER_TOKEN>/` still works with **no** bearer — regression guard;
  this is what keeps Claude Code and the Desktop bridge alive
- `/g`, `/d`, `/h`, `/t` still 404 without the URL secret
- tokens are stored hashed — the raw value never appears in the table

Gate: `.venv/bin/python -m pytest -q` (**not** bare `pytest` — a Homebrew python
is PEP-668 externally-managed and can't install feedparser/polars) plus focused
`ruff check` on touched files.

---

## Sharp edges

- **`stateless_http=True`** — both paths share one FastMCP instance and session
  manager. Verify a single `lifespan` still covers both; two
  `mcp.streamable_http_app()` calls may not be safe. Prefer one app object
  mounted twice.
- **`redirect_uri` validation is the entire security boundary** for a public
  client. Exact match against what was registered. No prefix matching, no
  wildcards.
- **Don't reuse `MCP_BEARER_TOKEN` as the login password.** Separate secret,
  separate blast radius.
- **The Zeabur image takes ~1m45s to pull** on every redeploy (the newswatch one,
  227 MB, took 7m40s). Use `zeabur service restart` for env-var-only changes.
- **`bot.py:_send` never checks Telegram's response** — no `raise_for_status()`,
  no status check. A 400 (bad HTML, >4096 chars) vanishes with no log anywhere.
  Fix that *before* debugging anything else in that file; it is what made the
  2026-07-31 chat-id bug take an hour to find.

---

## Deployment

1. Apply `sql/019_oauth.sql` to the authoritative instance via
   `python apply_schema.py` — manual; nothing runs migrations automatically.
2. Set `OAUTH_PASSWORD` on the `mcp` service.
3. Redeploy `mcp`.
4. Add the cloud connector at `https://alphatecx-mcp.zeabur.app/mcp/` — **bare
   path, no token segment.**
5. Confirm on mobile.
6. Delete the stale `Alpha` / `Alphatecx` connectors pointing at Vercel; they
   read the old database and would return different numbers from identically
   named tools.

## Related

- [`docs/wiki/decisions/2026-07-31-near-realtime-news-poller.md`](wiki/decisions/2026-07-31-near-realtime-news-poller.md)
- [`docs/wiki/decisions/2026-07-31-mcp-server-vercel-to-zeabur.md`](wiki/decisions/2026-07-31-mcp-server-vercel-to-zeabur.md)
