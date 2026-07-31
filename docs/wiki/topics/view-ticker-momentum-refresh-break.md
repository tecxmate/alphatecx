---
title: view_ticker_momentum refresh is broken by ticker renames
type: topic
slug: view-ticker-momentum-refresh-break
date: 2026-07-31
updated: 2026-07-31
attributed_to: [claude-agent]
belongs_to: [system-architecture]
source: observation
status: active
tags: [bug, database, matview, dashboards]
related: [2026-07-31-migrate-neon-to-zeabur, system-architecture]
---

## Symptom

`REFRESH MATERIALIZED VIEW public.view_ticker_momentum` fails:

```
ERROR: could not create unique index "idx_vtm_ticker"
DETAIL: Key (ticker_id)=(009805) is duplicated.
```

Surfaced during the [Zeabur migration](../decisions/2026-07-31-migrate-neon-to-zeabur.md), because `pg_dump` emits a `REFRESH` for matviews rather than copying their rows. It is **not** a migration artifact — the same refresh fails on Neon today. Neon's copy merely looks healthy because it holds stale rows from before the trigger date.

## Root cause

The matview's final `GROUP BY` includes `f.company_name` and `f.market` alongside `f.ticker_id`, but `idx_vtm_ticker` is unique on `ticker_id` **alone**. Any ticker appearing under two different names inside the 20-day window produces two grouped rows and violates the index.

`company_name` comes from `raw_twse_t86`, which records whatever name TWSE published on that date — so an issuer rename splits one ticker in two:

| ticker_id | company_name | rows | from | to |
|---|---|---|---|---|
| 009805 | 新光美國電力基建 | 71 | 2026-03-05 | 2026-07-09 |
| 009805 | 台新美國電力基建 | 14 | 2026-07-13 | 2026-07-30 |

(Shin Kong → Taishin, effective 2026-07-13. `dim_ticker` has exactly one row for 009805, so the join isn't the problem.)

The break is self-inflicting and self-healing on a rolling basis: it starts the day a rename enters the trailing 20-day window and stops once the old name ages out — which is why it wasn't caught earlier.

## Why it went unnoticed

`daily_harvest.yml` runs the dashboard/refresh chain with `continue-on-error: true`. Failure isolation is deliberate (data is already in the DB, downstream steps are presentation), but it also means this refresh can fail nightly without surfacing.

## Fix — applied 2026-07-31

`sql/002_views.sql` now groups by `f.ticker_id, f.ai_pillar, f.node` (the latter two come from `dim_ticker`, one row per ticker, so they're functionally dependent on the key) and takes the latest spelling:

```sql
(ARRAY_AGG(f.company_name ORDER BY f.date DESC))[1] AS company_name,
(ARRAY_AGG(f.market       ORDER BY f.date DESC))[1] AS market,
```

`dim_ticker` was **not** used as the name source, even though it's already LEFT JOINed: it doesn't classify every ticker, so the join would NULL out names that `raw_twse_t86` always carries.

Applied to both Zeabur and Neon — 10,584 rows each, 009805 resolves to a single row under 台新美國電力基建, zero duplicate `ticker_id`s. The pre-fix Neon copy held 10,376 stale rows.
