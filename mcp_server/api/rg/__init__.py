"""Risk Guard — pure decision logic.

Everything in this package is a pure function over plain dicts: no DB handle,
no network, no clock reads. That is deliberate. The PRD's acceptance criteria
are a replay table over historical days (§7), and a replay is only meaningful
if the same inputs always produce the same light.

The impure halves live elsewhere:
  mcp_server/api/rg/db.py    read layer for the MCP tools
  riskguard/                 fetchers, writers, cron pipeline (repo root)

This package sits under mcp_server/api/ rather than the repo-root /riskguard
folder named in PRD §2 because the Vercel project's Root Directory is
mcp_server/ — a repo-root package is not in the deployed bundle, so the MCP
tools could not import it. `mcp_server/api/quant/` is the existing precedent.
"""
