"""HTTP auth helpers for URL-secret routes."""

from __future__ import annotations

PUBLIC_PATHS = frozenset({"/", "/health"})
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
