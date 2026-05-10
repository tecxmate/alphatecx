"""HTTP auth helpers for URL-secret routes."""

from __future__ import annotations

PUBLIC_PATHS = frozenset({"/", "/health"})
TOKEN_PREFIXES = ("/mcp", "/g", "/d", "/h", "/t")


def is_authorized_path(path: str, token: str) -> bool:
    """Return whether a request path should pass the app auth gate.

    The project uses URL-as-secret routes for the MCP, graph, and dashboard
    surfaces. Prefix matching is segment-aware so `/g/<token>evil` does not
    pass for token `<token>`.
    """
    if path in PUBLIC_PATHS:
        return True
    if not token:
        return False

    allowed_prefixes = tuple(f"{prefix}/{token}" for prefix in TOKEN_PREFIXES)
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in allowed_prefixes)


def token_matches(candidate: str, token: str) -> bool:
    """Route-param token check used by individual handlers."""
    return bool(token) and candidate == token
