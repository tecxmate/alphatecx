---
title: Risk Guard — post-close loss-prevention system
type: topic
slug: risk-guard
date: 2026-07-31
attributed_to: [niko]
belongs_to: [alphatecx]
source: RISK_GUARD_PRD.md
status: active
tags: [risk, stop-loss, telegram, mcp, cron, taiwan-equity]
related: [2026-07-31-risk-guard-phase1, system-architecture, session-state, alphatecx]
---

## What it is

A post-close risk system whose only job is to stop [[niko]] losing money on TWSE/TPEX
swing trades. Specified in `RISK_GUARD_PRD.md` (Chinese, v1.1, 2026-07-31) after the
2026-07 correction — eight sessions, −16% — validated every pain point in it with a
real loss.

The single test any proposed feature has to pass, from PRD §0:

> 這個功能是在「阻止虧錢」還是在「慫恿買進」?前者做,後者不做。

**Hard non-goal:** Risk Guard never emits a buy signal, target price, or forecast. The
entry checklist has exactly two verdicts — 「今天不買。原因:…」 or 「沒有阻止你的理由」.
The second is the *absence of a reason to stop*, not a recommendation. This is asserted
in `tests/test_rg_checklist.py`, not merely documented.

## Modules

| ID | What | Phase | State |
|---|---|---|---|
| M1 | Market risk light 🟢🟡🔴, five subitems | 1 | built |
| M2 | Position stop-loss alerts + entry checklist | 1 | built |
| M2b | T+2 settlement cash check | 1 | built |
| M3 | Sector strength + supply-chain side | 2 | not built |
| M4 | Intraday anomaly watch (Fugle WS) | 2.5 | not built |
| M5 | Foreign intent score | 3 | held_pct snapshot only |
| M6 | MOPS / disposition announcements | 4 | not built |
| M7 | 節律 veto layer | 4 | table + checklist Q5 only |

## Where the code lives

The PRD (§2) pins Risk Guard to a `/riskguard` folder. It is split in two, because
Vercel's Root Directory is `mcp_server/` and a repo-root package is not in the deployed
bundle — an MCP tool cannot import it. See [[system-architecture]].

| Path | Runs on | Contains |
|---|---|---|
| `riskguard/` | GitHub Actions | `sources.py` (TAIFEX + breadth fetchers), `store.py`, `pipeline.py`, `replay.py` |
| `mcp_server/api/rg/` | Vercel + pytest | pure decision functions (`scoring`, `light`, `stops`, `settlement`, `checklist`, `messages`, `config`) + `db.py` read layer |

The purity split is what makes `riskguard.replay` meaningful: the same functions that
decide today's light re-derive any historical day deterministically.

## Interfaces

1. **Telegram bot** (`mcp_server/api/bot.py`) — `/status /pos /setpos /check /trade /balance /notrade`
2. **MCP tools** (`mcp_server/api/index.py`) — `rg_status`, `rg_positions`, `rg_alerts`,
   `rg_checklist`, `rg_journal_add`
3. `/status` dashboard — deferred to v2

All three read the same `rg_*` rows. Nothing recomputes a light, so the phone, the
dashboard and the Claude conversation cannot drift apart.

## Data sources added

| Data | Source | Note |
|---|---|---|
| 漲跌家數 | TWSE `MI_INDEX?type=MS`, table 漲跌證券數合計 | uses the **股票** column, not 整體市場 — the latter counts warrants/ETFs and would swamp the ~1,000 common stocks |
| 外資期貨淨留倉 | TAIFEX `futContractsDateDown` | Big5 CSV; 臺股期貨 × 外資及陸資 × 多空未平倉口數淨額 |
| 全市場融資餘額 | **no new feed** — `SUM(margin_balance)` over existing `raw_twse_margin` | |

## Known limits

- **6/08-type gap-downs are not catchable.** A −3.48% single-session collapse shows no
  advance signal in any of the five subitems. M2 stop-loss is the backstop, by design.
- M1 lands ~16:40 Taipei, not 15:30 — see [[2026-07-31-risk-guard-phase1]].
- Checklist Q2 and Q4 report `skipped` until M3/M6 exist. They are surfaced in
  `warnings`, never silently passed.
