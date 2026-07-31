# Zeabur WORKER image — the scheduled half of the system (harvesters, quant
# compute, Risk Guard crons). Build context is the repo root because these need
# `src/` and `riskguard/`, which the MCP server deliberately cannot import.
#
# The MCP server is a SEPARATE image built from mcp_server/Dockerfile. Two
# services, two images, two dependency sets: this one installs the root
# requirements.txt (polars, feedparser, plotly), which must never reach the MCP
# image — importing polars from an MCP tool breaks that deploy.
#
# There is no cron service type on Zeabur, so this runs as a long-lived
# container with supercronic as PID 1. supercronic rather than Debian cron
# because it logs to stdout (where `zeabur deployment log` can see it), needs no
# root, and does not silently swallow the environment the way crond does.
FROM python:3.12-slim

# TWSE publishes on Taipei wall-clock, and the whole codebase reasons in
# Asia/Taipei. A UTC container would fire the "16:30 post-close" job at
# 00:30 Taipei — eight hours before the data it is meant to harvest exists.
ENV TZ=Asia/Taipei \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# supercronic, arch-matched. TARGETARCH is set by BuildKit — without it an
# arm64 laptop build would fetch the amd64 binary and fail at exec time with a
# format error that looks nothing like an architecture problem.
ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.48
RUN curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
    && chmod +x /usr/local/bin/supercronic \
    && supercronic -test /dev/null

# Requirements first so the dependency layer survives source-only changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY riskguard ./riskguard
COPY sql ./sql
COPY deploy ./deploy
COPY apply_schema.py ./
# Not a layering mistake: riskguard/{pipeline,store,replay}.py import the pure
# decision functions from mcp_server/api/rg/, and rg/db.py falls back to
# mcp_server/api/db_v2.py. mcp_server and mcp_server.api are PEP 420 namespace
# packages (no __init__.py), so /app being on sys.path is what makes the import
# resolve. .dockerignore drops api/static/ — 5 MB of dashboards nothing reads.
COPY mcp_server/api ./mcp_server/api
# brief.py and thesis_status.py read thesis frontmatter from here.
COPY docs/theses ./docs/theses

RUN chmod +x deploy/daily-chain.sh \
    && supercronic -test deploy/worker-crontab \
    && useradd --create-home --uid 10001 worker \
    && chown -R worker:worker /app
USER worker

CMD ["supercronic", "-passthrough-logs", "deploy/worker-crontab"]
