# Wiki lint checklist

Run when the user says "lint the wiki" or whenever rot accumulates. Walk this list, fix what you can directly, and append a `## [YYYY-MM-DD] lint | <summary>` entry to `log.md` summarising the pass.

## Provenance and attribution
- [ ] Every page in `decisions/`, `stakeholders/`, `topics/` has frontmatter (`title`, `type`, `slug`, `date`, `attributed_to` where applicable, `belongs_to`).
- [ ] Every `attributed_to` value points at an existing stakeholder slug. (Topics are not allowed in `attributed_to`.)
- [ ] Every `belongs_to` value points at an existing stakeholder or topic slug.
- [ ] No stakeholder page has `type: entity` (legacy term — should be `stakeholder`).

## Status hygiene
- [ ] Pages with `status: superseded` link out to the page that replaced them.
- [ ] Decisions older than 90 days with `status: active` — confirm still active or mark superseded.
- [ ] Stakeholders with no contributions in 6+ months — keep but note in their page.

## Connectivity
- [ ] No orphan pages (no inbound links from `index.md` or any other wiki page). Either link them in or archive.
- [ ] `index.md` lists every page that exists; no listings reference deleted files.
- [ ] Every concept mentioned often (3+ pages) has its own topic page.

## Consistency
- [ ] No two pages contradict each other. If they do, flag in `log.md` and either reconcile or mark one as superseded.
- [ ] Date format is `YYYY-MM-DD` everywhere.
- [ ] Slugs are kebab-case, lowercase, no spaces.

## Coverage gaps
- [ ] Are there decision-shaped events in recent commit messages or chat that are not yet in `decisions/`?
- [ ] Are there stakeholders mentioned in recent decisions but lacking their own page?
- [ ] Are any topics missing an `## Open questions` section despite obvious unknowns?
