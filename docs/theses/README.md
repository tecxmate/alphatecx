# Theses

One MD file per active investment thesis. Output of `skills/decide-on-ticker`
or written manually after a deep session.

## Naming

`YYYY-MM-DD-<ticker>-<short-thesis-name>.md`

Examples:
- `2026-05-08-2330-foundry-cycle.md`
- `2026-05-08-2317-server-odm-acceleration.md`
- `2026-05-08-2308-power-supply-bottleneck.md`

The date is when the thesis was *opened*, not when last updated.

## Required frontmatter

```markdown
---
ticker: 2330
company: TSMC
opened: 2026-05-08
status: active           # active | superseded | closed-win | closed-loss
last_review: 2026-05-08
horizon: 3-6 months      # 1-2 weeks | 1-3 months | 3-6 months | 6-12 months
catalyst: <one line>     # what triggers a move?
invalidation: <one line> # what would prove this wrong?
inputs: [q_indicators, sc_ticker_momentum, ...]
sources_naive: [q_*, sc_*]    # data inputs to the narrative-naive view
sources_aware: [n_*, ...]     # text inputs (after Phase 2 lands)
---
```

## Lifecycle

- **active** — currently held or watched
- **superseded** — replaced by a newer thesis on the same ticker (link forward)
- **closed-win** — played out positively; record outcome and what worked
- **closed-loss** — invalidated; record what was missed and why

Don't delete closed theses. The journal of what didn't work is more
valuable than the next bull case.

## What belongs in a thesis

- Why this ticker, why now (the catalyst)
- Where naive and aware views agree / disagree
- The quant signal stack at thesis-open (snapshot)
- Position sizing rationale (if applicable)
- Invalidation: the specific data point that flips the thesis off

## What does NOT belong

- Daily price commentary — that's the journal
- Generic market commentary — that's a digest
- News re-summarisation without analysis — that's noise
