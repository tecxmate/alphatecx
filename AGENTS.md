# Agent rules for this project

This file is the contract every LLM agent (Claude Code, Codex, OpenCode, Cursor, etc.) operating in this repo must follow. Read it at session start. Re-read after long pauses.

---

## Project wiki — single source of truth

This repo maintains a persistent, LLM-curated wiki at `docs/wiki/`. It captures decisions, stakeholder context, feature notes, and external input across chats — anything we don't want to re-derive on each session.

**You (the agent) own the wiki.** On every meaningful turn — design decisions, scope changes, bug-fix rationales, stakeholder input, environment quirks — you must:

1. Read `docs/wiki/llm-wiki-guide.md` for the schema and frontmatter conventions before writing.
2. Append a one-line entry to `docs/wiki/log.md` with the standard prefix (see guide).
3. Create or update the relevant page(s) under `docs/wiki/decisions/`, `docs/wiki/stakeholders/`, or `docs/wiki/topics/` with proper frontmatter (`attributed_to`, `belongs_to`, `source`, `date`).
4. Update `docs/wiki/index.md` if you added a new page.

**Stakeholders are things that can make decisions** — people, teams, organizations, regulators, LLM agents, automations. They live in `docs/wiki/stakeholders/`. **Topics** (areas of the codebase, products, events, syntheses, concepts) live in `docs/wiki/topics/` and don't make decisions. **Tag every claim** with `attributed_to` (must be a stakeholder slug) and `belongs_to` (stakeholder or topic slug). If a referenced stakeholder is missing, create the page in the same turn.

Don't ask permission to maintain the wiki — treat it like committing code. If the user explicitly says "don't write to the wiki," skip it for that turn only.

---

## What is a "meaningful turn"

A turn is wiki-worthy if any of the following are true:

- A design decision is made, surfaced for the first time, or reversed.
- The scope changed, a feature was deferred, or a commitment was made to an external party.
- A bug was diagnosed and the root cause / fix rationale isn't obvious from the diff.
- Stakeholder input arrived (client, internal, external, vendor, regulator) that constrains future work.
- An environment / infra / vendor quirk was discovered that future-you would re-learn the hard way.
- Ownership or decision rights were clarified.

A turn is **not** wiki-worthy when it's a trivial typo fix, a status request, or throw-away exploration. In those cases just answer the user.

---

## What this is not

- Not a substitute for inline code comments. Decisions go in the wiki; non-obvious code mechanics go in code.
- Not a place to dump chat history. Synthesis only.
- Not a replacement for the user's preferred memory tools. Use both.
