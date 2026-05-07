# Per-ticker journals

One rolling MD file per ticker that's been thesis'd or actively watched.
Captures incremental updates, signal changes, and decisions that don't
warrant a full thesis revision.

## Naming

`<ticker>-<company-slug>.md` — one file per ticker, append-only chronologically.

## Format

Append a dated entry per update:

```markdown
## 2026-05-08

- Quant: RSI 69, MACD hist +12.4, BB %B 0.93, foreign_z20 -0.23.
  Price at 52w high but flow turning slightly negative.
- Action: hold; tighten mental stop to SMA-50 (1974).
- Next review: 2026-05-12 or on RSI > 75.
```

Keep entries short. Long analysis goes in the matching thesis file under
`docs/theses/`. The journal is a *trail*; the thesis is the *current view*.

## When to write

- After running the `decide-on-ticker` skill — log the conclusion in one line
- When a signal threshold flips (RSI cross, foreign-flow regime change)
- When a thesis catalyst fires or invalidation triggers
- Before/after acting (size, exit, partial)

## What does NOT belong

- Verbatim digest content (already in `docs/digests/`)
- Generic news (in news digest if anywhere)
- Rationalisation after the fact ("I should have...")
