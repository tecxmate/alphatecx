# Skills

On-demand Claude Skills for alphatecx v2. Each skill is a single
`SKILL.md` (with optional helpers) that Claude reads when invoked.
Run them in the Claude app with this project loaded as context — the
project's `docs/` directory is the shared memory across runs.

## Index

| Skill | Purpose | Status |
|---|---|---|
| `decide-on-ticker` | Dual-agent (narrative-naive + narrative-aware) reasoning on one ticker; writes a thesis MD | Naive pass operational; aware pass pending Phase 2 (news) |

## Calling convention

In the Claude app, with the project loaded:

> Use the `decide-on-ticker` skill on ticker 2330 (TSMC).

Claude reads `skills/decide-on-ticker/SKILL.md`, executes the steps,
queries the MCP at `https://alphatecx-v2-mcp.vercel.app` for data,
and writes the output to `docs/theses/`.

## Why skills (and not scheduled tasks)

Scheduled Tasks are good for **producing daily snapshots** (`docs/digests/`)
that future sessions read. They're cheap and run unattended. But they make
shallow conclusions because they have no context across runs.

Skills are good for **deep synthesis on demand** — they get invoked
when a digest flags something interesting (e.g. "RSI<40 + MACD>0
combo just triggered on TSMC"), and they read the full project context:
prior digests, theses, journals. The 15 daily Scheduled Tasks budget
isn't enough to do this for every ticker every day; doing it manually
when there's a reason is the right shape.

## Architectural commitment: prompt isolation

The `decide-on-ticker` skill runs two reasoning passes that **must not
share context**:

- **Naive pass**: gets only structured data via MCP (`q_*`, `sc_*`).
  Has no access to news, sentiment, or text-derived inputs.
- **Aware pass**: gets data + news + sentiment.

The reconciliation step compares them. Where they disagree, that
disagreement *is* the signal — typically a sign that the market is
paying for narrative the data doesn't support, or that the data sees
something the narrative hasn't priced yet.

If you find yourself merging the two passes' contexts to "save time,"
stop. The whole point is the isolation.
