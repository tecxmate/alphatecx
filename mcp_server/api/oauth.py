"""OAuth 2.1 + PKCE for cloud connectors — the only route to mobile.

Claude Code and Claude Desktop reach this server fine over URL-as-secret
(`/mcp/<MCP_BEARER_TOKEN>/`, Desktop via an `mcp-remote` stdio bridge). Mobile
and claude.ai-web cannot: they only speak *cloud connector*, and that flow
requires OAuth. It probes `/.well-known/oauth-protected-resource`, gets the
blanket 404 `security.py` returns for unknown paths, falls back to Dynamic
Client Registration at `/register`, gets 404 again, and gives up with
"Couldn't register with Alphatecx's sign-in service".

**Stateless on purpose.** Tokens are HMAC-signed and carry their own claims;
`client_id` is derived from the registered redirect URIs. Nothing is written to
Postgres. That is not merely simpler — at the time of writing,
`postgresql.zeabur.internal` and the public host return *different rows* for the
same query, so a token table would have had to pick a side and would work from
one surface while silently failing from another. Deriving everything from a
signing key sidesteps the question entirely.

The single exception is `_CONSUMED`: a signature cannot make an authorization
code single-use. That set is process-local, not shared — codes live 60 seconds,
so a restart forgets nothing that matters.

This is additive. `/mcp/<token>/` keeps working exactly as before; bearer auth
is served at bare `/mcp`. Either can be removed without touching the other.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

log = logging.getLogger("oauth")

# Distinct from MCP_BEARER_TOKEN, which is already exposed in URLs and logs.
# Absent ⇒ signing and verification refuse rather than defaulting; a defaulted
# key would make every forged token valid.
SIGNING_KEY = os.environ.get("OAUTH_SIGNING_KEY", "")

# The only thing between the internet and the full read surface once bare /mcp
# answers 401 instead of 404. Must be strong, and must not be reused.
PASSWORD = os.environ.get("OAUTH_PASSWORD", "")

CODE_TTL = 60             # authorization codes are redeemed immediately
ACCESS_TTL = 3600
REFRESH_TTL = 90 * 86400

# Consumed authorization-code ids. Bounded in practice by CODE_TTL: an entry is
# only useful for 60s, and this is a single-user server.
_CONSUMED: set[str] = set()


# ── Signing ───────────────────────────────────────────────────────────────

def _require_key(key: str | None = None) -> str:
    k = SIGNING_KEY if key is None else key
    if not k:
        raise RuntimeError(
            "OAUTH_SIGNING_KEY is not set. Refusing to sign or verify tokens: "
            "a defaulted key would make every forged token valid."
        )
    return k


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    return _b64(hmac.new(_require_key().encode(), payload.encode(), hashlib.sha256).digest())


def issue(kind: str, ttl: int = ACCESS_TTL, **claims) -> str:
    """Mint a signed token. `kind` is part of the signed payload, so an
    authorization code can never be presented as an access token."""
    claims.update({"kind": kind, "exp": int(time.time()) + ttl})
    claims.setdefault("jti", secrets.token_urlsafe(12))
    payload = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    return f"{payload}.{_sign(payload)}"


def verify(token: str, kind: str) -> dict | None:
    """Return the claims, or None. Never raises — every caller is on a request
    path where an exception would be a 500 for an attacker-supplied string."""
    try:
        payload, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        claims = json.loads(_unb64(payload))
        if claims.get("kind") != kind or claims.get("exp", 0) < time.time():
            return None
        return claims
    except Exception:
        return None


def consume(code: str) -> bool:
    """Redeem an authorization code exactly once. False if already redeemed."""
    claims = verify(code, "code")
    if claims is None:
        return False
    jti = claims.get("jti")
    if not jti or jti in _CONSUMED:
        return False
    _CONSUMED.add(jti)
    return True


# ── Clients ───────────────────────────────────────────────────────────────

def client_id_for(redirect_uris: list[str]) -> str:
    """Deterministic client_id: HMAC over the registered redirect URIs.

    Nothing to persist, nothing to lose on restart. Anyone can register any
    redirect URI and get a valid id — fine for a public client *because* the id
    only ever validates against the exact URIs it was derived from, and both
    `/authorize` and `/token` re-check the incoming URI against it.
    """
    joined = "\n".join(sorted(redirect_uris))
    return _b64(hmac.new(_require_key().encode(), joined.encode(), hashlib.sha256).digest())[:32]


def client_id_matches(client_id: str, redirect_uris: list[str]) -> bool:
    return hmac.compare_digest(client_id, client_id_for(redirect_uris))


def password_ok(candidate: str) -> bool:
    if not PASSWORD or not candidate:
        return False
    return hmac.compare_digest(candidate, PASSWORD)


# ── Grant flow ────────────────────────────────────────────────────────────

def make_code(client_id: str, redirect_uri: str, code_challenge: str,
              sub: str = "owner") -> str:
    """Bind the redirect URI, PKCE challenge, and subject into the code itself,
    so `/token` can re-check the first two and carry the third without storing
    anything. `sub` is decided at authorize time (which credential logged in)
    but the token is minted at `/token`, so it has to ride inside the code."""
    return issue("code", ttl=CODE_TTL, client_id=client_id,
                 redirect_uri=redirect_uri, code_challenge=code_challenge, sub=sub)


def _pkce_ok(verifier: str, challenge: str) -> bool:
    expected = _b64(hashlib.sha256(verifier.encode()).digest())
    return hmac.compare_digest(expected, challenge)


def exchange_code(code: str, verifier: str, redirect_uri: str) -> dict | None:
    """authorization_code grant. None on any failure — the caller answers a
    generic invalid_grant rather than revealing which check failed."""
    claims = verify(code, "code")
    if claims is None:
        return None
    # Exact match, no prefix, no wildcard: this is the boundary.
    if claims.get("redirect_uri") != redirect_uri:
        return None
    if not _pkce_ok(verifier or "", claims.get("code_challenge", "")):
        return None
    if not consume(code):          # single-use, checked last so a failed
        return None                # attempt cannot burn a legitimate code
    return _token_response(claims.get("sub", "owner"))


def refresh(refresh_token: str) -> dict | None:
    claims = verify(refresh_token, "refresh")
    if claims is None:
        return None
    # Preserve the subject across refresh — otherwise a customer's refresh would
    # silently downgrade them to "owner".
    return _token_response(claims.get("sub", "owner"))


def _token_response(sub: str = "owner") -> dict:
    return {
        "access_token": issue("access", ttl=ACCESS_TTL, sub=sub),
        "refresh_token": issue("refresh", ttl=REFRESH_TTL, sub=sub),
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
    }


# ── Discovery ─────────────────────────────────────────────────────────────

def protected_resource_metadata(base: str) -> dict:
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
    }


def authorization_server_metadata(base: str) -> dict:
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }
