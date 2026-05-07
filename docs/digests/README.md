# Daily digests

This is where Claude Scheduled Tasks write their daily output. One folder per
ISO date, one MD file per task. The folder is the queryable record of what the
system saw and thought on a given day; later sessions read these as project
context.

## Layout

```
docs/digests/
  YYYY-MM-DD/
    01-quant.md          # Quant snapshot: top movers, screener hits, signal stack
    02-news.md           # Recent news + sentiment (after Phase 2 lands)
    03-rotation.md       # Sector rotation watch, flow z-scores by pillar
    04-anomalies.md      # Outlier flags from q_screener / flow z-scores
    05-macro.md          # Rates / FX / semi-cycle indicators
    06-disagreement.md   # Where quant + news disagree (after Phase 2)
    summary.md           # Aggregator, written last
  weekly/
    YYYY-WNN.md          # Weekly review summarising the daily digests
```

## File conventions

Every digest MD starts with frontmatter so future sessions can grep by
inputs / dependencies:

```markdown
---
date: 2026-05-08
task: 01-quant
inputs: [q_screener, q_indicators, q_backtest, sc_sector_momentum]
generated_by: claude-scheduled-task
---

# 2026-05-08 — Quant snapshot

## Highlights
- ...
```

## What goes here vs. theses

- **Digests** are time-snapshots: "this is what the data looked like on
  this date." Append-only. Don't edit history.
- **Theses** (in `docs/theses/`) are takes on a specific ticker / setup.
  Mutable. Update when the thesis changes, not when the data does.
- **Journals** (in `docs/journals/`) are per-ticker rolling notes —
  what was decided, what changed.
