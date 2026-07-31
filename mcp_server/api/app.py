"""Single ASGI entrypoint serving both the MCP surface and the Telegram bot.

Vercel ran `api/index.py` and `api/bot.py` as two independent serverless
functions, with `vercel.json` rewrites steering `/bot/*` to the second one.
Zeabur runs one uvicorn process, so the two FastAPI apps have to be composed
here instead. `index.py` and `bot.py` are deliberately left untouched: they
remain individually deployable, which keeps the Vercel project usable as a
rollback target.

Start command (run from `mcp_server/`, not `mcp_server/api/`):

    uvicorn api.app:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

try:
    from bot import app as _bot_app
    from index import app
except ModuleNotFoundError:  # package import path — how uvicorn loads api.app
    from .bot import app as _bot_app
    from .index import app

# Only the bot's own endpoints. Copying `_bot_app.router.routes` wholesale would
# also drag in its FastAPI-generated /docs, /redoc and /openapi.json, which
# collide with the ones `app` already has — shadowed rather than fatal, but the
# kind of thing that makes a later reader doubt which app answered.
_BOT_ROUTES = [
    route for route in _bot_app.router.routes
    if getattr(route, "path", "").startswith("/bot")
]

if not _BOT_ROUTES:
    raise RuntimeError(
        "No /bot routes found on bot.py's app. The Telegram webhook would "
        "silently 404 and Telegram would retry forever against a dead URL."
    )

app.router.routes.extend(_BOT_ROUTES)

__all__ = ["app"]
