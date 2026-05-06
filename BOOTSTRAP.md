# Bootstrap checklist — first agent run

Hand this to the agent on the first session in a fresh copy of this template. They follow it top-to-bottom; you only need to answer the framing questions.

---

## Step 0 — Read the contract

1. Read `AGENTS.md`.
2. Read `docs/wiki/llm-wiki-guide.md` end-to-end.
3. Skim `docs/wiki/index.md` and `docs/wiki/log.md` to confirm the wiki is empty (template state).

## Step 1 — Identify the owner

Ask the user (in one message, all together):

1. **Your name (the project owner)** — for the `niko.md`-equivalent stakeholder page.
2. **The project name + one-sentence description** — for the README and the project-overview topic.
3. **Project timezone** (if scheduling matters) — e.g. `Asia/Taipei`, `Europe/Berlin`.
4. **Other stakeholders to seed now** — name + role for anyone you already expect to reference (clients, collaborators, partner orgs, regulators, other AI agents).
5. **Stack constraints I should know on day one** — frameworks, platforms, deployment targets, hard requirements.
6. **Anything you don't want me to write to the wiki by default** — privacy boundaries, confidential clients, etc.

Wait for the answers before continuing. Do not assume.

## Step 2 — Seed the wiki

Once answered:

1. Create `docs/wiki/stakeholders/<owner-slug>.md` with `role: owner`. Use the answers from Step 1.
2. Create `docs/wiki/stakeholders/<your-agent-name>.md` with `role: agent` (e.g. `claude-code.md`). One page per agent identity that operates in this project.
3. For each additional stakeholder named in Step 1, create a stakeholder page. If you don't have enough information yet, write a stub with `status: proposed` and a `## Open questions` section.
4. Create `docs/wiki/topics/<project-slug>.md` describing the product / project — what it is, scope, stack, sub-areas. Link to its sub-area topic pages as you create them.
5. Update `docs/wiki/index.md` so every new page is listed under the right section.
6. Append a `## [YYYY-MM-DD] ingest | Wiki bootstrapped` entry to `docs/wiki/log.md` with `attributed_to: [<owner-slug>]`.

## Step 3 — Verify

Run these mental checks before reporting back:

- [ ] Every page in `stakeholders/` has `type: stakeholder` and a `role` field.
- [ ] Every page in `topics/` has `type: topic`.
- [ ] Every `attributed_to` value is a stakeholder slug that exists.
- [ ] `index.md` lists every page in the wiki.
- [ ] `log.md` has the bootstrap entry.

## Step 4 — Report

Reply with:

- A one-paragraph summary of what was created.
- A bulleted list of the new pages, grouped by section.
- Any open questions the user should answer next.

From here on, the agent operates per `AGENTS.md` — every meaningful turn folds into the wiki without being asked.
