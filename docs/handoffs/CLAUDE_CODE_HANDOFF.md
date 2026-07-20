# Handoff — TW Equity Research Data Layer

**Goal:** upgrade the Alpha/Alphatecx MCP stack so a Claude agent running the `tw-equity-alpha`
skill can (a) stop making avoidable errors, and (b) *generate* candidates rather than only confirm
ones the user points at.

**Guiding principle: adopt before building.** Research (2026-07) found most needed data already
exists free and official. Only two genuinely new things need building — both are *computation*
layers, not data layers.

---

## 0. Why — the concrete failures this fixes

Real errors from two weeks of live use:

| Failure | Root cause | Fixed by |
|---|---|---|
| Told user "you're filled at 171.5" when nothing filled | No order/position visibility | M4 (positions) |
| Escalated a 拓凱 "limit-down, no bid" that was a 試撮 artifact | No session-state awareness | M3 (session state) |
| Presented 華碩's 6% yield as forward when it went ex 7/1 | No corporate-action calendar | M1 (FinMind/TWSE) |
| 5 of 8 limit-up names returned empty valuation | TPEX gap in `q_valuation` | M1 (FinMind PER/PBR) |
| Deep-dive financials assembled by hand | `yf_financials` throws Timestamp error | M1 (FinMind statements) |
| Found 拓凱's 7-week accumulation *by luck, reactively* | No market-wide flow screen | **M2 (flow-leaders)** |

M2 is the one that changes what the agent can *do*, not just how accurately it does it.

---

## 1. Architecture — three layers

```
┌─ ADOPT ──────────────────────────────────────────────┐
│ FinMind MCP  ·  TWSE/TPEX OpenAPI                    │  ← near-zero build
│ fundamentals, corporate actions, chips, TPEX valn    │
└──────────────────────────────────────────────────────┘
┌─ BUILD ──────────────────────────────────────────────┐
│ flow_leaders_scan   ·   scan_limit_board             │  ← the custom edge
│ (generative)            (board triage)               │
└──────────────────────────────────────────────────────┘
┌─ WIRE ───────────────────────────────────────────────┐
│ session_state + realtime quote wrapper               │  ← error elimination
│ MIS poller → optional Fugle/Shioaji upgrade          │
└──────────────────────────────────────────────────────┘
```

---

## 2. Milestone 1 — ADOPT (do this first, highest value/effort ratio)

### 2a. FinMind
- Docs: `https://finmind.github.io/` · llms.txt + Agent Skill + **official MCP server** already exist.
- Free tier ≈ **600 requests/hour** (registered). Respect it; cache aggressively.
- **No realtime** (removed by FinMind upstream) — realtime comes from M3.

Datasets to wire (FinMind dataset names):

| Need | Dataset |
|---|---|
| Dividends / ex-div | `TaiwanStockDividend`, `TaiwanStockDividendResult` |
| Financial statements | `TaiwanStockFinancialStatements`, `TaiwanStockBalanceSheet`, `TaiwanStockCashFlowsStatement` |
| **TPEX-inclusive valuation** | `TaiwanStockPER` (PER/PBR/yield, 上市+上櫃) |
| Institutional flow | `TaiwanStockInstitutionalInvestorsBuySell` |
| Foreign holdings | `TaiwanStockShareholding` |
| Margin/short | `TaiwanStockMarginPurchaseShortSale` |
| Holder dispersion | `TaiwanStockHoldingSharesPer` |
| Monthly revenue | `TaiwanStockMonthRevenue` |
| Price (adj + raw) | `TaiwanStockPrice`, `TaiwanStockPriceAdj` |
| News | `TaiwanStockNews` |

**Decision:** run FinMind's MCP directly *or* proxy through Alpha. Recommend **proxy through
Alpha** so enrichment joins (M2) can hit one local store rather than N remote calls. Nightly ETL
into the existing Postgres, keyed `(ticker_id, date)`.

### 2b. TWSE / TPEX OpenAPI (official cross-check)
- `https://openapi.twse.com.tw/v1` — **previous-day/month only**, no same-day.
- `https://www.twse.com.tw/...` — same-day EOD (e.g. `exchangeReport/MI_INDEX`, `fund/T86` for 三大法人).
- TPEX: `https://www.tpex.org.tw/openapi/v1/...`
- Key endpoint: `/opendata/t187ap45_L` — 上市公司股利分派情形 (board resolution date, shareholder
  meeting date, dividend year, amounts). Use to **validate** FinMind dividend data.

**Acceptance:** query 華碩 (2357) as of 2026-07-10 and the layer must return
`ex_dividend_date = 2026-07-01, cash_dividend = 42.0, status = already_ex` — i.e. a new buyer does
NOT receive it. This is the exact error that must become impossible.

---

## 3. Milestone 2 — BUILD (the custom edge)

### 3a. `flow_leaders_scan` ★ highest-value new tool

**Purpose:** find accumulation-into-a-flat-price across the whole market — the 拓凱 signature —
*before* the price moves. This is the tool that makes the agent generative.

```
flow_leaders_scan(
  window_days:        int   = 20,     # flow lookback
  min_foreign_z:      float = 1.0,    # accumulation strength
  min_buy_day_ratio:  float = 0.65,   # % of sessions with net foreign buying
  max_price_move_pct: float = 8.0,    # |move| over window — "still flat"
  max_pe:             float = 20.0,   # null-PE excluded unless include_loss=true
  max_foreign_held:   float = 25.0,   # under-owned
  min_turnover_twd:   int   = 10_000_000,
  markets:            list  = ["TWSE","TPEX"],
  include_loss:       bool  = false,
  sort_by:            enum  = "sleeper_score",
  limit:              int   = 50
)
```

**Core computation per ticker:**

```python
# flow
foreign_net_z20    = (foreign_net_today - mean(foreign_net_20d)) / std(foreign_net_20d)
foreign_net_sum_N  = sum(foreign_net over window)
buy_day_ratio      = count(days foreign_net > 0) / window_days
foreign_streak     = current consecutive net-buy sessions

# price flatness — the other half of the signature
price_move_pct     = (close_today / close_N_ago - 1) * 100
price_range_pct    = (max(high_N) - min(low_N)) / mean(close_N) * 100
is_flat            = abs(price_move_pct) <= max_price_move_pct

# the signature
accumulation_into_flat = (foreign_net_sum_N > 0) and (buy_day_ratio >= min_buy_day_ratio) and is_flat
```

**Sleeper score (0–100)** — weight the two make-or-break signals hardest:

| Component | Weight |
|---|---|
| accumulation strength (z + buy_day_ratio + streak) | 35 |
| price flatness / not-yet-run | 25 |
| valuation (PE, PB, yield) | 20 |
| under-owned (low foreign_held_pct, high room) | 10 |
| no leverage froth (margin, short ≈ 0) | 5 |
| revenue inflection (monthly YoY turning +) | 5 |

Anti-flags force `triage="chase"` regardless of score: `pe is null`, `pe > 40`,
`foreign_net_sum_N < 0`, `price_move_pct > 30`, `turnover < min`.

**Acceptance test (non-negotiable):** run with `as_of = 2026-06-30`. **拓凱 (4536) must appear in
the top 20.** Ground truth: ~7 consecutive weeks of foreign net buying (~+800k shares) while price
sat flat at 163–167, PE ~12.8, foreign held 12.68%, margin ~0. If the scan misses it, the weights
are wrong.

**Second acceptance:** run `as_of = 2026-07-17`. **日馳 (1526) must NOT appear as a sleeper** — it
was limit-up ×2 with foreign *selling* (−172k) and revenue −24% YoY. Must classify `chase`.

### 3b. `scan_limit_board`
Full spec already written — see `scan_limit_board_spec.md` (endpoints, tick-rounding table,
lock detection, enrichment join, response schema, gotchas). Build after 3a; it shares the same
enrichment layer.

**Shared enrichment module:** both scanners join to the same `enrich(ticker_ids[]) -> rows`
function. Build once, batch-query, never N+1.

---

## 4. Milestone 3 — WIRE (realtime + session state)

### 4a. `session_state()` — build this even before realtime
Returns the current Taipei market phase. **This alone prevents a whole error class.**

```json
{
  "taipei_time": "2026-07-20T08:47:12+08:00",
  "is_trading_day": true,
  "phase": "pre_open_auction",
  "phases_today": {
    "pre_open_auction": "08:30-09:00",
    "regular":          "09:00-13:30",
    "odd_lot_intraday": "09:00-13:30",
    "after_hours_odd":  "13:40-14:30 (single call auction at 14:30)",
    "after_hours_fixed":"14:00-14:30"
  },
  "price_is_indicative": true,
  "warning": "試撮 — simulated price, may swing violently on a thin book; not a trade"
}
```

- **Trading calendar required** — TWSE publishes holidays; typhoon closures are ad-hoc (2026-07-10
  was closed by Typhoon Bavi). Store an override table; allow manual insert.
- Any quote tool MUST stamp `price_is_indicative` when phase is `pre_open_auction`.

### 4b. `quote(symbols[])` — realtime
Tiered by what the user has:

| Source | Latency | Constraint | Use |
|---|---|---|---|
| **TWSE MIS** `mis.twse.com.tw/stock/api/getStockInfo.jsp` | ~5s | **3 req / 5 sec** or ban; ~50 symbols/req; needs session cookie from `index.jsp` | Default. Watchlist poller only — cannot sweep market. |
| Yahoo | ~5 min | free, easy | Fallback / context |
| Fugle 行情 | realtime | API key, tiered rate limits, REST + WebSocket | Upgrade |
| Shioaji (永豐) | realtime | free w/ SinoPac account; WS tick+bidask; 200 symbols; `snapshot()`, `scanner()` | Best, if broker matches |

**MIS fields to surface:** `z` last (may be `-` pre-first-print → fall back to `y`/`o`, do NOT emit
a false price), `y` prev close, **`u` limit-up / `w` limit-down (authoritative, pre-tick-rounded)**,
`o/h/l`, `v` volume, `a/f` ask 5-level, `b/g` bid 5-level, `t` time.

**Architecture:** persistent poller writing to cache; tools read cache. A market-wide MIS sweep is
~40–60 batched calls (~3–4 min) — never do it on-demand.

---

## 5. Milestone 4 — OPTIONAL (positions)

`portfolio_positions()` / `order_status()` — read-only.
- **Shioaji** exposes balance, positions, orders, fills in real time; requires 電子憑證 (certificate)
  auth on top of API key. Only works if the account is 永豐.
- If the broker differs, skip — do **not** scrape a brokerage web session.
- **Read-only. No order placement.** The agent analyses; the human trades.

---

## 6. Known gaps — document, don't fake

- **Consensus forward estimates: no free source found.** Every forward P/E / PEG must be labelled
  `source: manual` or `source: web`. Never synthesise one and present it as data.
- Segment-level financials often need the annual report (MOPS PDF) — not in any API. Keep the
  "confirmed vs open" discipline in the memo template.
- FinMind adj-price endpoint is paid-tier on some plans; verify before relying on it.

---

## 7. Build order

1. **M1 FinMind + TWSE OpenAPI ETL** → kills 4 error classes, unblocks everything else.
2. **M3a `session_state()`** → tiny, prevents the 試撮 error class immediately.
3. **M2a `flow_leaders_scan`** → the generative edge; validate against the two acceptance tests.
4. **M2b `scan_limit_board`** → reuses M2's enrichment module.
5. **M3b realtime `quote()`** → MIS poller first, Fugle/Shioaji if upgrading.
6. **M4 positions** → only if broker = 永豐.

---

## 8. Cross-cutting requirements

- **Every response carries `_source`, `_as_of`, `_freshness`** (existing Alpha convention — keep it).
- **Never silently drop a ticker** on an enrichment miss — return `null` fields. TPEX gaps and
  thin-flow names must still appear.
- **Timezone:** Asia/Taipei everywhere. The user operates from Vietnam (UTC+7, one hour behind) —
  return explicit TZ offsets so the agent never miscomputes session timing.
- **Rate limits:** FinMind ~600/hr; TWSE MIS 3 req/5s. Central limiter + cache; fail soft with a
  clear `errors[]` entry rather than a hard exception.
- **Idempotent EOD caching** keyed `(date, market)` so historical/backtest scans are cheap.

---

## 9. Definition of done

The agent can answer, with no screenshots and no manual web search:

1. "Who is being quietly accumulated right now while still cheap and flat?" → `flow_leaders_scan`
2. "Why did the board go limit-up today, and which are real?" → `scan_limit_board` w/ triage
3. "Is this price real, or pre-open noise?" → `session_state` + `quote`
4. "Does a buyer today get the dividend?" → corporate-action calendar
5. "What are this company's segment margins and quarterly trough?" → financial statements
6. "Did my order fill?" → positions (if M4)
