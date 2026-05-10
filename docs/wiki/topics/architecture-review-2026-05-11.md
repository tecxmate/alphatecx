---
title: Architecture Review 2026-05-11
type: topic
slug: architecture-review-2026-05-11
date: 2026-05-11
updated: 2026-05-11
attributed_to: [antigravity-agent]
belongs_to: [system-architecture]
source: observation
status: active
tags: [architecture, refactor, mcp, pipeline, testing]
related: [system-architecture, alphatecx]
---

## Summary

The repo has a sound macro shape for a small trading-support system: scheduled Python ingestion, Neon Postgres as state, materialized/query views, a Vercel MCP/API surface, Telegram alerts, and static dashboards. The next architecture risk is not the database choice; it is codebase shape. MCP tools, query functions, dashboard generation, and cron orchestration are growing as large flat modules with duplicated concerns and little test coverage.

## Current State

- `mcp_server/api/index.py` is about 1,200 lines and mixes MCP tool registration, route/static serving, provenance stamping, auth, and on-demand quant imports.
- `mcp_server/api/db_v2.py` is about 900 lines and mixes read-model queries, watchlist mutations, serialization, SQL construction, and data-status helpers.
- `src/harvester/daily.py` is explicit and readable, but each stage is manually wired with repeated try/log/result/rate-limit structure.
- Dashboard builders generate static HTML directly from SQL and markdown/frontmatter parsing, duplicating data-access and parsing concerns.
- Quant modules exist in both `src/quant/` and `mcp_server/api/quant/`, and the copies differ, creating drift risk between cron and deployed API behavior.
- There are no visible tests, no `pyproject.toml`, and no lint/type gate in CI.

## Recommended Direction

Prefer an incremental modularization before any platform rewrite. The best next step is to split the application into clear packages while keeping the existing Neon/Vercel/GitHub Actions deployment:

- `src/alphatecx/db/`: connection, serialization, query primitives.
- `src/alphatecx/read_models/`: supply-chain, quant, news, watchlist, digest, graph query modules.
- `src/alphatecx/mcp/`: thin MCP tool adapters that validate inputs and stamp provenance.
- `src/alphatecx/pipeline/`: harvest stage definitions and orchestration runner.
- `src/alphatecx/dashboard/`: shared data loaders plus renderers.

Major rewrites, such as moving from GitHub Actions/Vercel to a job queue or service framework, should wait until the pipeline is too slow, needs retries/stateful scheduling beyond Actions, or serves multiple users.

## Priority Changes

1. Split `index.py` and `db_v2.py` by domain, preserving current tool names and response shapes.
2. Remove duplicated `mcp_server/api/quant/` implementations by packaging shared quant code for both cron and Vercel, or by making the deployed API import one canonical copy.
3. Introduce a declarative pipeline stage registry so `daily.py` records stage metadata, dependencies, fatal/non-fatal behavior, rate limiting, and result keys in one place.
4. Add a minimal test harness around SQL builders, indicator math, ticker validation, and watchlist mutations with mocked DB connections.
5. Add `pyproject.toml` with `pytest`, `ruff`, and import-path conventions; wire a non-network CI check.
6. Treat generated static assets as build artifacts unless Vercel deployment constraints require committing them; if committed, isolate their refresh PR/commit path from source changes.

## Open Questions

- Should the deployed Vercel function be allowed to import from repo-root `src/`, or does Vercel packaging require code to live under `mcp_server/api/`?
- Is this system intended to remain single-user, or will auth/account boundaries matter soon?
- Should dashboard HTML remain static-first, or is a small API-backed frontend expected after the trading workflow stabilizes?

## History

- 2026-05-11: Review requested by [niko]; recommendations authored by [antigravity-agent].
- 2026-05-11: Branch `codex/optimize` started. First changes extract URL-secret auth and SQL column allowlist helpers into dependency-light modules and add a no-install unit-test baseline. [antigravity-agent]
- 2026-05-11: Optimization pass added connection reuse for TWSE/TPEX HTTP fetches and reduced repeated ticker-page build work by loading active theses once and caching sector-index series per build. [antigravity-agent]
- 2026-05-11: Local tooling was installed into `.venv`; `pytest` passes, while full-repo `ruff check .` reports broad pre-existing lint debt, so the current practical gate is focused Ruff checks on touched/new files plus tests. [antigravity-agent]
- 2026-05-11: Ticker-page generation was further optimized by batching OHLCV, T86 flow, valuation, and latest-signal reads for all target tickers instead of issuing separate queries for each ticker. News matching remains per ticker pending a more careful search/indexing design. [antigravity-agent]
