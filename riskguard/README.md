# Risk Guard

A post-close risk system for TWSE/TPEX swing trading. Its only job is to stop you losing
money. Spec: [`RISK_GUARD_PRD.md`](../RISK_GUARD_PRD.md) (v1.1).

> 這個功能是在「阻止虧錢」還是在「慫恿買進」?前者做,後者不做。 — PRD §0

**Risk Guard never tells you to buy anything.** No signals, no target prices, no forecasts.
The entry checklist has two possible verdicts:

- 「今天不買。原因:…」 — something is stopping you
- 「沒有阻止你的理由」 — nothing is stopping you

The second is *not* a recommendation. It is the absence of a reason to stop, and the
wording is deliberate. `tests/test_rg_checklist.py` asserts that no output ever contains
buy phrasing.

## Status — Phase 1

| Module | What | State |
|---|---|---|
| M1 | Market risk light 🟢🟡🔴 (5 subitems, hysteresis) | ✅ |
| M2 | Stop-loss alerts + 6-question entry checklist | ✅ |
| M2b | T+2 settlement cash check | ✅ |
| M5 | `held_pct` daily snapshot (groundwork only) | ✅ |
| M3 / M4 / M6 / M7 | sector strength / intraday / announcements / rhythm | ⬜ not built |

Checklist Q2 (sector rank) and Q4 (disposition status) depend on M3/M6 and report
`skipped`. They are always listed under `warnings` — never silently passed.

## Layout

Two folders, split by **where the code can run**, not by taste:

| Path | Runs on | Contains |
|---|---|---|
| `riskguard/` | GitHub Actions | fetchers, DB writes, cron entry points, replay |
| `mcp_server/api/rg/` | Vercel + pytest | pure decision functions + the MCP read layer |

Vercel's Root Directory is `mcp_server/`, so a repo-root package is not in the deployed
bundle and an MCP tool cannot import it. The pure half therefore lives beside the server,
following the existing `mcp_server/api/quant/` precedent.

The purity split is load-bearing: `scoring.score_day` and `light.resolve_light` take plain
dicts and touch nothing else, which is what lets `riskguard.replay` re-derive any
historical day deterministically.

## Setup

```bash
python apply_schema.py                 # creates rg_* tables + seeds the watch list
```

Then calibrate M1 against the 2026-06/07 correction:

```bash
python -m riskguard.replay --start 2026-06-01 --end 2026-07-31           # report only
python -m riskguard.replay --start 2026-06-01 --end 2026-07-31 --write   # persist
```

The replay prints one row per session with the per-subitem points and a PASS/FAIL against
the PRD §7 acceptance table. If a row misses, change thresholds in
`mcp_server/api/rg/config.py` and re-run. **Do not special-case a date in `scoring.py`** —
a scorer that recognises 2026-07-24 has learned the answer, not the pattern.

Last run (2026-07-31, range 2026-06-25 → 07-30): **7/7 scorable rows PASS.** Calm and
rising sessions score 0–1 🟢, mild weakness 2–3 🟡, and the seven acceptance sessions plus
6/26 (−3.64%) score 4–8 🔴. 7/31 is unscored — TAIEX for it is not harvested yet.

Two calibration changes came out of that run, both recorded in `config.py`:

- **Subitem 4 scores the *change* in foreign futures net OI, not the level** (a departure
  from PRD §5 #4). Measured across 2026-06/07 the level never left 65k–86k net short — on
  +4.20% days and on the −6.47% crash alike — so the PRD's 20,000 threshold was crossed on
  every single session and the subitem added a constant +2 to every score. That is not a
  signal; it just moved the scale up and made 🟢 reachable only when all four other
  subitems were zero.
- **Bands moved to 0–2 / 3 / ≥4.** With the constant removed every score dropped ~2, so
  the PRD's ≥5 red cutoff moved with it.

## Running

```bash
python -m riskguard.pipeline --mode post_close   # M1 + M2 + M2b + held_pct
python -m riskguard.pipeline --mode pre_market   # restates a red light before the open
```

Scheduled by `.github/workflows/daily_harvest.yml` (16:30 Taipei) and
`.github/workflows/riskguard_premarket.yml` (08:30 Taipei). Both are idempotent — a re-run
recomputes the same light, and the unique index on `rg_alerts (date, kind, dedup_key)`
prevents a second buzz on your phone.

Alerts are **written to `rg_alerts` before they are sent**. If Telegram is down, the row
stays `pushed = false` and both entry points re-send undelivered `critical` alerts from the
last 3 days (PRD §6 補發) — including the pre-market run, so an exit alert stranded by an
overnight outage still reaches you before the 09:00 open.

## Interfaces

**Telegram**

```
/status                                  今日燈號 + 持倉風險總覽
/pos                                     持倉與線位
/setpos 2344 cost=51.5 warn=49 exit=47.8
/check 2344 [買進金額]                    進場 checklist(6題)
/trade buy 2344 51.5 x3                  回報成交(餵 M2b)
/balance 476276                          更新交割戶餘額
/notrade 2026-08-04 <reason>             標記不可執行日
```

**MCP** — `rg_status`, `rg_positions`, `rg_alerts`, `rg_checklist`, `rg_journal_add`.
All read the same rows the Telegram bot reads, so the phone and the conversation cannot
disagree.

## Limits — read this

**0. Foreign futures OI barely helps, and the margin feed silently died.** Two things the
first live replay exposed, both worth knowing before you trust a light:

- Subitem 4 carries little signal at any horizon on this sample. 7/24 (−2.67%) saw
  foreigners *cut* net short by ~9,900 while 6/30 (+2.50%) saw them add ~6,600 — the sign
  is backwards on the days that matter most. It is scored small on purpose. The light
  effectively rests on trend + breadth + the day's move.
- Subitem 3 (margin) was blind for all of July: the nightly harvest recorded
  `status='empty'` with 0 rows on every trading day since ~1 July while T86 ingested 5,000+
  rows a day, and `loader.get_ingested_dates` treats `'empty'` as "confirmed holiday —
  skip forever", so the gap could never self-heal. Repaired by hand (22 sessions, 41,081
  rows) on 2026-07-31. **The underlying harvester bug is not fixed** — it will re-open
  tonight. Even repaired the subitem stays quiet through July, correctly: margin balance
  *fell* 0.2% → 9.7%, so retail was deleveraging, not the "leverage rising into a falling
  tape" the rule looks for.

**1. Gap-down crashes are not catchable.** 2026-06-08 fell −3.48% in one session with no
advance signal in any of the five M1 subitems. The PRD lists it as a known miss. M1 warns
about *conditions*; a single-session collapse out of a calm tape has none. **M2 stop-loss
is the backstop, and it only works if the lines are actually set** — use `/setpos`.

**2. A close-only rule plus a human hand is slow.** The 2026-07 cycle proved it: an exit
line at 28.6 took four days to execute and cost an extra 1.6%. Every `stop_exit` alert
therefore repeats the same instruction — put a 觸價條件單 (觸價=出場線下一檔、市價、長效) at
your broker and let the machine execute. Risk Guard deliberately has **no order API**; you
are the last gate, but the trigger should not be.

**3. Missing data is announced, not smoothed over.** If TAIFEX or TWSE fails, that subitem
scores 0 and the push says `⚠️ 資料缺漏`. A green light carrying a missing-data note is not
the same claim as a green light.

**4. A position with no price data is reported, not skipped silently.** `raw_twse_ohlcv`
is harvested for the classified supply-chain universe plus the benchmark — **not** for
everything in `rg_positions`. Promote an unclassified name (e.g. 8299) to a position and
there is no close to compare against, so you get a `stop_unchecked` warning instead of a
misleading "0 stop alerts". Put a broker-side conditional order on those names.

**5. The settlement check is only as good as what you tell it.** It knows about fills you
report with `/trade` and the balance you report with `/balance`. It cannot see your broker
account. A stale balance produces a confidently wrong answer.

**6. 明牌 / tip-account scams are outside this system.** The 2026-07 pattern — accounts
posting a 進場價 set 5% above the closing price, whose names then fell 21–55% over three
days — is not something Risk Guard detects. The defence is the checklist: a name in a
vertical run fails Q3 regardless of who recommended it.
