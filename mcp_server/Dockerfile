# Zeabur build for the MCP server. Build context is mcp_server/ — the same
# directory Vercel used as its Root Directory, so the rule that a repo-root
# package cannot be imported by an MCP tool still holds here.
#
# 3.12 rather than latest: bot.py uses PEP 604 unions (`int | str`), so 3.10 is
# the floor, and psycopg[binary] ships wheels well ahead of the newest release.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements first so the dependency layer survives source-only changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY api ./api

# The app only ever reads its database and writes nothing to disk.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# Zeabur injects PORT, so the command needs a shell to expand it; the fallback
# keeps `docker run` usable locally without setting it. `exec` matters — without
# it uvicorn is a child of sh, never receives SIGTERM, and every redeploy waits
# out the 10s kill timeout instead of shutting down cleanly.
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
