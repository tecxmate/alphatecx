# Wiki Index

Catalog of every page in `docs/wiki/`. One line per page. Update on every create/rename.

## Schema
- [LLM Wiki — Master Plan](llm-wiki-guide.md) — schema, conventions, agent workflow, portable pattern

## Stakeholders
*Things that can make decisions: people, teams, organizations, regulators, agents, automations.*

- [Niko](stakeholders/niko.md) — project owner, strategy & trading decisions (owner)
- [Antigravity Agent](stakeholders/antigravity-agent.md) — Claude agent, wiki curation & implementation (agent)
- [Gemini Agent](stakeholders/gemini-agent.md) — Google Gemini agent, initial architecture & strategy proposal (agent)

## Decisions
- [2026-05-07 — Stateful Upgrade](decisions/2026-05-07-stateful-upgrade.md) — upgrade from stateless MCP to systematic Postgres pipeline
- [2026-05-07 — v2 Implementation Decisions](decisions/2026-05-07-v2-implementation-decisions.md) — Supabase confirmed, Telegram alerts, historical backfill, v1 coexistence, Claude Code as tech team
- [2026-05-07 — Neon over Supabase](decisions/2026-05-07-neon-over-supabase.md) — switched to Neon Postgres (v1's DB); Supabase not necessary for standard Postgres workloads

## Topics
*Areas, products, events, and synthesised concepts. Topics don't make decisions; stakeholders do.*

- [alphatecx](topics/alphatecx.md) — Taiwan AI supply chain analysis & trading system (project overview)
- [alphatecx v1](topics/alphatecx-v1.md) — existing system: APEX TW strategy, TWSE MCP, Telegram alerts
- [Taiwan AI Supply Chain Map](topics/taiwan-ai-supply-chain.md) — 4-pillar strategic map (Semiconductor, Equipment, Infrastructure, Energy)
- [System Architecture (v2)](topics/system-architecture.md) — Neon-centered stateful pipeline, schema, MCP security, daily workflow
- [Historical Data Backfill](topics/historical-backfill.md) — 90-day backfill strategy, rate limits, storage estimates

## Log
- [log.md](log.md) — append-only chronological record
