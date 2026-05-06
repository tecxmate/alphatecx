# tecxproj — project template

A starter template for any new project that should ship with a persistent, LLM-curated wiki from day one. Copy this folder, rename, point your agent at it, and start working — the structure for capturing decisions, stakeholders, and topics is already in place.

Born from the [tecxwork](../tecxwork) project, where the wiki was retrofitted in mid-stride. The lesson: doing this on day one costs a few minutes and pays back every session afterwards.

---

## What's inside

- **`AGENTS.md`** — the rules every Claude Code / Codex / OpenCode agent reads at session start. Tells them they own the wiki and must maintain it on every meaningful turn.
- **`CLAUDE.md`** — symlinks/aliases `AGENTS.md` so Anthropic's tooling picks it up too.
- **`docs/wiki/`** — the wiki itself.
  - `llm-wiki-guide.md` — the schema and the portable pattern. The agent reads this before writing any wiki page.
  - `index.md` — flat catalog of every page. Updated on every create/rename.
  - `log.md` — append-only chronological log of every meaningful turn.
  - `stakeholders/` — things that can make decisions (people, teams, orgs, regulators, LLM agents, automations).
  - `decisions/` — decision records, one per decision, dated.
  - `topics/` — areas, products, events, syntheses, concepts. Topics don't decide; stakeholders do.
  - `templates/` — fill-in-the-blank starters for new pages.
- **`BOOTSTRAP.md`** — the **first-run checklist** for the next agent. Hand them this and step away.

---

## How to use this template

1. **Copy the folder.** `cp -r tecxproj <new-project-name>`. Or `git init` inside a fresh copy if you want a clean history.
2. **Rename references.** Inside `docs/wiki/llm-wiki-guide.md` and `AGENTS.md`, the language is generic; you usually don't need to edit. Edit `README.md` to describe your project.
3. **Hand it to the agent.** Open the project in Claude Code (or your tool of choice) and say:

   > Read `BOOTSTRAP.md` and follow it.

   The agent will: read the guide, seed the owner stakeholder (you), seed itself as the agent stakeholder, ask 4–6 framing questions, and start filing decisions / topics from your conversation.
4. **Work normally.** Every meaningful turn — decision, stakeholder input, scope change, bug rationale — the agent will file it without being asked. If you ever want it to skip the wiki for a turn, say so.

---

## What makes this different from a generic README + `docs/`

- **Stakeholder tagging.** Every claim is tagged with `attributed_to` (who said it) and `belongs_to` (whose domain it is). You can answer "who decided X?" and "what has the client asked for so far?" without re-reading chats.
- **Decisions as a first-class object.** A `decisions/` folder with dated records is the antidote to "we discussed this six weeks ago, what did we land on?". Decisions get superseded, not deleted.
- **Stakeholder vs topic.** Crisp distinction: stakeholders decide; topics are decided about. This separation prevents the wiki from collapsing into a single bucket of "things".
- **Agent owns the bookkeeping.** The wiki is a compounding artifact maintained by LLMs. Humans curate sources, ask questions, and direct the analysis.

---

## Recommended companions

- **Obsidian** opened on `docs/wiki/` is a fantastic IDE for browsing the wiki the agent writes. Graph view shows orphans and hubs.
- **`grep "^## \[" docs/wiki/log.md | tail -10`** gives you the last ten turns at a glance.

---

## Origin

The pattern is adapted from the public LLM-wiki idea (RAG → persistent compounding wiki). The concrete schema, stakeholder taxonomy, and agent workflow were instantiated for tecxwork in 2026-05 and generalized into this template.
