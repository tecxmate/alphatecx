# Watchlist

The layer between "noticed it" and "have a thesis on it." Names that
the daily/intraday cron has flagged with non-trivial conditions but
that haven't yet been through the `decide-on-ticker` Skill to produce
a structured thesis.

The cron's action-checklist (in pre-market and post-close briefs)
prioritises watchlist names — they sit just below open theses in the
attention hierarchy.

## Layout

```
docs/watchlist/
  README.md       # this file
  active.md       # the current watchlist (table form, one row per ticker)
  archived/       # closed-out watchlist entries (escalated to thesis OR dropped)
    YYYY-MM-DD-<ticker>-<reason>.md
```

## Lifecycle

A name on the watchlist has three possible exits:

1. **→ Thesis.** A `decide-on-ticker` run produces `docs/theses/<...>.md`.
   Remove the row from `active.md`, append to `archived/` with the
   thesis path noted.
2. **→ Dropped.** Conditions that put it on the watchlist resolved
   without a setup. Remove from `active.md`, append to `archived/`
   with reason. Don't rationalise — "z-score returned to normal"
   is enough.
3. **→ Repeat trigger.** Same name lights up a second time within a
   week without escalation. Either thesis it or document why not
   (e.g. portfolio overlap with existing thesis).

Names should not stagnate on the watchlist. Aim to escalate or drop
within ~5 trading days of being added.

## active.md format

A table with required columns. Cron parses it; humans edit it. Keep
the format stable.

```
| ticker | company | pillar/node | added | reason | escalation_trigger |
|---|---|---|---|---|---|
| 6488 | GlobalWafers | equipment/equipment-materials | 2026-05-08 | foreign_z=+4.25 | sustains 3 sessions → thesis |
```

## What does NOT belong here

- Names with an active thesis (those are already escalated)
- "Names I find interesting" with no signal trigger (be specific
  about why something earned a watchlist slot)
- Random retail-favourite tickers outside our 26-name classified
  universe (the system's edge is supply-chain-mapped flow signals;
  watchlist should stay inside that universe)
