---
last_updated: 2026-05-08
---

# Active watchlist

Names with non-trivial signal triggers that haven't been escalated to a
full `decide-on-ticker` thesis yet. Cron's action-checklist surfaces
these in pre-market and post-close briefs.

| ticker | company | pillar/node | added | reason | escalation_trigger |
|---|---|---|---|---|---|
| 6488 | GlobalWafers | equipment / equipment-materials | 2026-05-08 | foreign_z = +4.25 (5d cum +9.24M shares), at 52w high, RSI 77, BB %B 1.08. **But** total_net_z20 = −4.25 — foreigners buying at extremes while domestic trust+dealer net sells. Mixed institutional read. | If foreign_z stays > 1.5 for 2 more sessions OR if domestic flow flips positive (alignment) → run `decide-on-ticker` |
| 3324 | Auras Technology | infrastructure / thermal-cooling | 2026-05-08 | foreign_z = +4.25 today, but 5d cum is still −2.96M (today was a sharp reversal). RSI 49, 12.3% off 52w high, total_net_z20 = +4.25 (all institutions aligned today). Possible accumulation start after weakness. | Confirmation needed: another foreign net-buy day in next 3 sessions AND price reclaims SMA-50 (1041) → run `decide-on-ticker` |

## Notes on today's adds

Both names lit up the same `foreign_net_z20 = +4.25` flag from 2026-05-08
T86 data, but the underlying setups are opposites:

- **6488** is buying *into* extremes — foreigners accumulating at 52w
  high while domestic institutions distribute. Could be informed
  buyers vs. profit-taking domestics, OR foreign desks still chasing
  while smarter domestic money rotates out. The total_net_z20 = −4.25
  divergence is the key tension to resolve.

- **3324** is buying *after* extended weakness — name is 12% off its
  high, RSI sub-50, and foreigners are stepping in with all
  institutions aligned (total_z = +4.25 too). Cleaner accumulation
  shape *if* it sustains.

Both should resolve within 3–5 sessions one way or the other.

## Format reference

See [README.md](README.md) for column definitions, lifecycle, and
parsing conventions.
