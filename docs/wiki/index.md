# Wiki Index

Catalog of every page in `docs/wiki/`. One line per page. Update on every create/rename.

## Schema
- [LLM Wiki — Master Plan](llm-wiki-guide.md) — schema, conventions, agent workflow, portable pattern

## Stakeholders
*Things that can make decisions: people, teams, organizations, regulators, agents, automations.*

- [Niko](stakeholders/niko.md) — project owner, strategy & trading decisions (owner)
- [Antigravity Agent](stakeholders/antigravity-agent.md) — Claude agent, wiki curation & implementation (agent)
- [Codex Agent](stakeholders/codex-agent.md) — Codex agent, implementation and operational debugging (agent)
- [Gemini Agent](stakeholders/gemini-agent.md) — Google Gemini agent, initial architecture & strategy proposal (agent)

## Decisions
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

## Topics
*Areas, products, events, and synthesised concepts. Topics don't make decisions; stakeholders do.*

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

## Log
- [log.md](log.md) — append-only chronological record
