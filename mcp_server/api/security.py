"""HTTP auth helpers for URL-secret routes, plus the OAuth bearer check."""

from __future__ import annotations

try:
    from oauth import verify as _verify_oauth_token
except ModuleNotFoundError:      # package import path used by local tests
    from .oauth import verify as _verify_oauth_token

# The OAuth endpoints must answer before any credential exists — that is the
# point of discovery. Omitting them means this middleware 404s them and a cloud
# connector never gets far enough to register, which is precisely the failure
# this module used to cause.
_OAUTH_PATHS = frozenset({
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/register",
    "/authorize",
    "/token",
})

PUBLIC_PATHS = frozenset({"/", "/health"}) | _OAUTH_PATHS
TOKEN_PREFIXES = ("/mcp", "/g", "/d", "/h", "/t")

# The Telegram surface authenticates itself and carries no URL secret: the
# webhook verifies Telegram's X-Telegram-Bot-Api-Secret-Token header and then
# gates on the owner's chat_id. Under Vercel it was a separate function that
# never reached this middleware at all; serving both apps from one uvicorn
# process makes the exemption something we have to state out loud.
BOT_PREFIX = "/bot"


def is_authorized_path(path: str, token: str) -> bool:
    """Return whether a request path should pass the app auth gate.

    The project uses URL-as-secret routes for the MCP, graph, and dashboard
    surfaces. Prefix matching is segment-aware so `/g/<token>evil` does not
    pass for token `<token>`.
    """
    if path in PUBLIC_PATHS:
        return True
    if path == BOT_PREFIX or path.startswith(f"{BOT_PREFIX}/"):
        return True
    if not token:
        return False

    allowed_prefixes = tuple(f"{prefix}/{token}" for prefix in TOKEN_PREFIXES)
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in allowed_prefixes)


def token_matches(candidate: str, token: str) -> bool:
    """Route-param token check used by individual handlers."""
    return bool(token) and candidate == token


def bearer_token_valid(header: str) -> bool:
    """Whether an `Authorization` header carries a valid OAuth access token.

    Only bare `/mcp` consults this. The URL-secret surfaces (`/g`, `/d`, `/h`,
    `/t` and `/mcp/<token>`) never do, so they keep 404-ing for anyone without
    the secret and stay hidden.

    Refresh tokens are deliberately rejected: `verify` matches on the signed
    `kind` claim, so a long-lived refresh credential cannot be replayed against
    the resource.
    """
    if not header or not header.lower().startswith("bearer "):
        return False
    return _verify_oauth_token(header[7:].strip(), "access") is not None
