# Wiki Index

Catalog of every page in `docs/wiki/`. One line per page. Update on every create/rename.

## Schema
- [LLM Wiki — Master Plan](llm-wiki-guide.md) — schema, conventions, agent workflow, portable pattern

## Stakeholders
*Things that can make decisions: people, teams, organizations, regulators, agents, automations.*

- [Niko](stakeholders/niko.md) — project owner, strategy & trading decisions (owner)
- [Brian](stakeholders/brian.md) — co-founder, commercial product direction & safety posture (internal)
- [Antigravity Agent](stakeholders/antigravity-agent.md) — Claude agent, wiki curation & implementation (agent)
- [Codex Agent](stakeholders/codex-agent.md) — Codex agent, implementation and operational debugging (agent)
- [Gemini Agent](stakeholders/gemini-agent.md) — Google Gemini agent, initial architecture & strategy proposal (agent)
- [Claude Agent](stakeholders/claude-agent.md) — Claude Code agent, database operations & implementation (agent)

## Decisions
- [2026-08-09 — Risk-profile personalization](decisions/2026-08-09-risk-profile-personalization.md) — per-user risk tier (conservative/balanced/aggressive) stored on the customer; set at onboarding via `set_my_risk_profile` / `--risk`; AI reads `my_profile` and adapts framing
- [2026-08-09 — Connector teaching UX](decisions/2026-08-09-connector-teaching-ux.md) — keep ~44 tools (context is fine on 1M); teaching lives in server `instructions` (persona) + tool descriptions + a `start_here` tool, not fewer tools
- [2026-08-08 — Commercialization direction](decisions/2026-08-08-commercialization-direction.md) — *(proposed)* sell to funded, finance-averse investors who consult Claude; Phase 1 = Stripe-gated remote MCP connector (Apollo/WordPress model, ~80% built), Phase 2 = headless web app embedding Claude for guardrails, mobile deferred; open gate = investment-advice licensing (needs a lawyer)
- [2026-05-07 — Stateful Upgrade](decisions/2026-05-07-stateful-upgrade.md) — upgrade from stateless MCP to systematic Postgres pipeline
- [2026-05-07 — v2 Implementation Decisions](decisions/2026-05-07-v2-implementation-decisions.md) — Supabase confirmed, Telegram alerts, historical backfill, v1 coexistence, Claude Code as tech team
- [2026-05-07 — Neon over Supabase](decisions/2026-05-07-neon-over-supabase.md) — switched to Neon Postgres (v1's DB); Supabase not necessary for standard Postgres workloads
- [2026-05-07 — V2 review fixes](decisions/2026-05-07-v2-review-fixes.md) — review of Gemini's V2; SQL injection, timezone, idempotency, view bug, RLS portability
- [2026-05-08 — Analysis system plan](decisions/2026-05-08-analysis-system-plan.md) — phased plan for quant + news + dual-agent analysis layered on v2; Scheduled Tasks for digests, Skills for depth
- [2026-05-17 — assistant-ui frontend](decisions/2026-05-17-assistant-ui-frontend.md) — scaffold Next.js chat at `web/`, talk to the existing Python MCP via AI SDK; defer Clerk/Stripe
- [2026-05-27 — Disable scheduled harvest crons](decisions/2026-05-27-disable-scheduled-harvest-crons.md) — remove unattended GitHub Actions schedules to stop CPU-hour churn; keep manual dispatch
- [2026-06-03 — Re-enable scheduled harvest crons](decisions/2026-06-03-reenable-scheduled-harvest-crons.md) — reverse the 2026-05-27 pause after observing concrete staleness cost; assumed CPU concern did not materialise
- [2026-06-11 — Neon retention prune](decisions/2026-06-11-neon-retention-prune.md) — pruned old all-market raw data and compacted Neon from 490 MB to 158 MB
- [2026-06-17 — Disable scheduled Telegram briefs](decisions/2026-06-17-disable-scheduled-telegram-briefs.md) — stop scheduled pre-market/intraday Telegram messages while leaving news harvests and manual dispatch available
- [2026-07-17 — scan_limit_board ships EOD-only](decisions/2026-07-17-limit-board-scanner-eod-only.md) — realtime MIS sweep doesn't fit the stateless Vercel function; board fetched live from the exchanges since Neon can't serve full-market
- [2026-07-21 — flow_leaders_scan](decisions/2026-07-21-flow-leaders-scan.md) — median-anchored flatness (survives corrupt prints), single-day z demoted from a gate to optional; valuation.close is the price source since ohlcv misses the acceptance names
- [2026-07-21 — session_state calendar](decisions/2026-07-21-session-state-calendar.md) — holiday classifier, manual typhoon overrides, and the mcp_viewer GRANT/RLS every new MCP-read table needs
- [2026-07-26 — Flow-leaders dividend enrichment](decisions/2026-07-26-flow-leaders-dividend-enrichment.md) — Tool Review v2 Phase 1 (TWSE-native): forward-cash yield flag, ex-div proximity, stale-price guard, revenue numeric guard; FinMind items deferred
- [2026-07-27 — FinMind Phase 2 built](decisions/2026-07-27-finmind-phase2-build.md) — cash/stock split + honest ex-date dividend_trap (fill-probability isn't computable free) + governance-news overlay; nightly FinMind ETL
- [2026-07-31 — Migrate Neon → Zeabur Postgres](decisions/2026-07-31-migrate-neon-to-zeabur.md) — dump/restore onto self-hosted PG 18.4; roles don't travel so `mcp_viewer` must pre-exist; Zeabur has TLS disabled
- [2026-07-31 — MCP server moved Vercel → Zeabur](decisions/2026-07-31-mcp-server-vercel-to-zeabur.md) — co-locating with Postgres puts the read path on the private network, deleting the cleartext exposure rather than fixing it; `mcp<2` pin; new bearer token; harvesters still exposed
- [2026-07-31 — Scheduled work on Zeabur (`cron` service)](decisions/2026-07-31-scheduled-work-on-zeabur.md) — supercronic container on Taipei time, GH Actions left running in parallel; Telegram unset to stop double alerts; `riskguard` needs `mcp_server/api/rg` and `docs/theses/` is a runtime input
- [OAuth plan — mobile MCP access](../OAUTH-PLAN.md) — cloud connectors need OAuth; blocked on resolving the split database and rotating exposed credentials
- [2026-07-31 — Near-real-time news poller](decisions/2026-07-31-near-realtime-news-poller.md) — no Redis, no SSE/WebSocket: ingestion cadence was the constraint, so a Zeabur worker polls feeds every 3 min and pushes to Telegram; conditional GET is load-bearing, and T86's once-a-day publish caps "real-time signals" regardless
- [2026-07-31 — Risk Guard Phase 1 built](decisions/2026-07-31-risk-guard-phase1.md) — M1 light as a hysteresis state machine, M2 stops, M2b T+2 settlement, five `rg_*` tools; TAIEX-only scoring provably fails the 7/07 acceptance row, so breadth + TAIFEX feeds were added; cron on GH Actions, not Vercel

## Topics
*Areas, products, events, and synthesised concepts. Topics don't make decisions; stakeholders do.*

- [Commercial productization](topics/commercial-productization.md) — paid connector plan: MoR payments (Stripe can't be merchant from VN/TW), multi-tenant OAuth, per-customer metering, `_disclaimer` on `_stamp()`
- [Paid connector — deploy checklist](topics/paid-connector-deploy.md) — runbook to take Layers 0–2 + metering + billing live: migrate → deploy → provision → verify; billing + rollback
- [Investing principles](topics/investing-principles.md) — school-neutral universal principles as a reasoning layer (distilled + attributed, not ingested); `investing_principles` tool, tier-aware emphasis; data tools stay clean
- [Tool description style](topics/tool-description-style.md) — template for writing MCP tool docstrings the model-as-consultant can select and teach from; step-2 priority list
- [alphatecx](topics/alphatecx.md) — Taiwan AI supply chain analysis & trading system (project overview)
- [alphatecx v1](topics/alphatecx-v1.md) — existing system: APEX TW strategy, TWSE MCP, Telegram alerts
- [Taiwan AI Supply Chain Map](topics/taiwan-ai-supply-chain.md) — 4-pillar strategic map (Semiconductor, Equipment, Infrastructure, Energy)
- [System Architecture (v2)](topics/system-architecture.md) — Neon-centered stateful pipeline, schema, MCP security, daily workflow
- [Historical Data Backfill](topics/historical-backfill.md) — 90-day backfill strategy, rate limits, storage estimates
- [Infrastructure accounts](topics/infrastructure-accounts.md) — Neon, Vercel, Telegram: which org/account owns what, console URLs
- [Supply Chain Audit & Expansion 2026-05-10](topics/supply-chain-audit-2026-05-10.md) — fixed 4 wrong-coded tickers in Gemini's seed; expanded to 50 classified across 21 nodes; added `sc_edges` for explicit supplier→customer links
- [3D Correlation Graph](topics/correlation-graph-3d.md) — Mantegna-distance MDS embedding of TW universe; three.js viewer at `/g/{TOKEN}/`; pipeline + auth + math
- [Architecture Review 2026-05-11](topics/architecture-review-2026-05-11.md) — repo architecture assessment and prioritized modularization plan
- [Web Frontend (Next.js + assistant-ui)](topics/web-frontend.md) — `web/` chat app; layout, env, turn flow, how to add generative UI
- [Limit Board Scanner](topics/limit-board-scanner.md) — `scan_limit_board`: 漲停/跌停 board + sleeper/chase triage; exchange quirks, spec deviations, enrichment coverage gaps
- [Flow-Leaders Scan](topics/flow-leaders-scan.md) — `flow_leaders_scan`: market-wide screen for quiet foreign accumulation into a flat, cheap price (generative sleeper board); median-anchored flatness, data-source map
- [Session State + Market Calendar](topics/session-state.md) — `session_state`: Taipei market phase + trading calendar; 試撮 indicative-price guard, holiday classifier, mcp_viewer grant rule
- [Realtime Quote](topics/realtime-quote.md) — `quote`: watchlist realtime via TWSE MIS; authoritative limit prices, serverless watchlist-only constraint, 試撮 indicative stamp
- [Dividend Calendar](topics/dividend-calendar.md) — `dividend_calendar`: ex-dividend dates + amounts (TWT49U/TWT48U); "does a buyer today get the dividend?"; the 華碩 fix
- [view_ticker_momentum refresh break](topics/view-ticker-momentum-refresh-break.md) — issuer renames split one `ticker_id` into two grouped rows and violate `idx_vtm_ticker`; fails silently under `continue-on-error`
- [Risk Guard](topics/risk-guard.md) — post-close loss-prevention system (`rg_*`): M1 risk light, M2 stops + entry checklist, M2b settlement check; never emits buy signals
- [FinMind integration (Phase 2)](topics/finmind-phase2-plan.md) — deferred Tool Review v2 items needing a FinMind token: dividend_trap/填息 probability, governance news overlay, dividend-adjusted flatness

## Log
- [log.md](log.md) — append-only chronological record
