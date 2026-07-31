"""Risk Guard — the impure half (fetchers, writers, cron entry points).

PRD §2 pins Risk Guard's code to its own folder inside the existing alphatecx
repo, with no new MCP server and an `rg_` prefix on every table and tool. This
package is that folder.

The pure decision logic it calls lives in `mcp_server/api/rg/` instead, because
the Vercel project's Root Directory is `mcp_server/` — a repo-root package is
not in the deployed bundle, so the MCP tools could not import it from here.
Split by deployment reachability, not by taste:

    riskguard/            runs on GitHub Actions (network + DB writes)
    mcp_server/api/rg/    runs on Vercel and in tests (pure + DB reads)

Entry points:
    python -m riskguard.pipeline --mode post_close
    python -m riskguard.pipeline --mode pre_market
    python -m riskguard.replay   --start 2026-06-01 --end 2026-07-31
"""
