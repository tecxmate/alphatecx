<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     Source: scripts/build_tutorial.py
     Rebuild: python scripts/build_tutorial.py
     CI fails (tests/test_tutorial.py) if this file drifts from the code. -->

# alphatecx — how to use it

A Taiwan equity (TWSE/TPEX) supply-chain and flow intelligence system. There are
53 tools; 26 are free. You do not need to learn their names — you
ask in plain words and the assistant picks.

**What this is not:** investment advice. Nothing here will tell you to buy, sell
or hold, by design. It exists so you can understand a decision you make
yourself.

---

## The three surfaces

| Where | What it carries | Why |
|---|---|---|
| **Claude** (MCP connector) | Analysis you talk back to | The only surface with the tools. Ask questions here. |
| **Telegram** | The machine's own voice — stop alerts, briefs, failure notices | Push, not conversation. It tells you when something needs you. |
| **The console** `/d/<token>/` | Dashboards, per-ticker pages, system health | Look at it when you want a picture rather than an answer. |

The split is deliberate: Telegram is for messages that must reach you when you
are not looking; Claude is for anything you would want to reply to.

---

## First five minutes

Just talk. A good opening is one of:

- *"What's the system tracking right now?"* → the assistant calls `start_here`
  and `sc_data_status` so you can see what is fresh before trusting anything.
- *"Tell me about 2330."* → `ticker_lookup` → `beginner_stock_card` →
  `q_valuation`. Every term gets defined the first time it appears.
- *"I'm cautious with money — remember that."* → `set_my_risk_profile`, which
  changes how everything is framed from then on.

**Set your risk profile early.** It is one call, it persists across every future
chat, and it is what makes the rest of the system speak to you rather than at
you.

---

## The two investor characters

Your saved risk profile picks one. They are not different data — they are
different questions asked of the same data.

| Profile | Persona | Horizon | Leads with |
|---|---|---|---|
| `conservative` | **The Steward** | years | What would permanently impair this capital, not what it does this week |
| `balanced` | **The Allocator** | months to years | What is core (held through cycles) versus satellite (held on a thesis) |
| `aggressive` | **The Opportunist** | days to weeks | The stop FIRST — where the idea is proven wrong, before any upside talk |

The Opportunist is the one people expect to be reckless. It is not: it leads
with the stop and the position size *before* any mention of upside, and it
refuses to imply a probability of profit. The numbers bound the **loss**, not
the odds.

Ask for `investing_personas` to see all three in full.

---

## Sizing a position before you take it

`risk_estimate` is the tool most worth knowing about. Give it your account size,
the entry, and how much of the account you are willing to lose on the idea, and
it returns the position size that risks exactly that — plus three things generic
calculators miss:

- **Taiwan's ±10% daily limit means a stop does not fill in a limit-down.** A
  stop further away than one full limit gets gapped straight through.
- **Exit liquidity** in sessions, at 10% of daily volume. A stop you cannot
  trade out of is decoration.
- **What it could not compute**, named out loud. No volume data means
  "liquidity is UNKNOWN", never silence.

Lots round **down**, always. Rounding up would quietly exceed the one number you
asked it to control.

---

## Reading `q_backtest` without fooling yourself

This is the part that matters most, because a backtest is the easiest place in
the system to be lied to — including by yourself.

**Read `verdict` first, then `net_edge_vs_baseline_pct`.** Never quote a bare
hit rate. Four fields decide whether a result means anything:

| Field | Why |
|---|---|
| `baseline` | The same window with no condition applied. A 58% hit rate against a 56% baseline is a **two point** edge, not a 58% one. |
| `net_edge_vs_baseline_pct` | That edge after Taiwan round-trip friction (0.585% — brokerage both ways plus the sell-side transaction tax). Short-horizon rules routinely go negative here while looking profitable gross. |
| `n_effective` | Independent observations, clustered by date. 400 raw triggers may be 25 real ones, because names triggering on the same day share one market. |
| `caveats` | Survivorship and in-sample tuning. Both bias **upward** and neither is corrected. |

Entry defaults to `next_close` — the first price you could actually have traded.
The old default bought at the very close the signal was computed from, which
nobody can do.

**"No edge" is the common result and a useful answer.** A tool that always finds
something is a tool that is fitting noise.

---

## What can be copied from quant funds

| Strategy | Practised by | Status | The catch |
|---|---|---|---|
| Trend following / time-series momentum | Man AHL, Winton | 🔨 buildable | The most robust published anomaly and the most crowded. |
| Cross-sectional momentum (relative strength) | AQR, most quant equity books | ✅ available | Suffers violent reversals at market turning points — momentum crashes are its signature failure and they arrive precisely when the strategy looks best. |
| Factor investing — value, quality, size, low-volatility | AQR, Dimensional | ✅ available | Premia are measured in decades and have gone missing for ten years at a time — value from 2010 to 2020 is the standard example. |
| Volatility targeting / risk parity sizing | Bridgewater, Man AHL | ✅ available | Improves risk-adjusted return, not raw return, and it de-risks into a crash by construction — which is the point, and also why it underperforms in a V-shaped recovery. |
| Pod risk discipline — mechanical loss limits | Millennium, Citadel | ✅ available | THE most transferable idea on this list and the least glamorous. |
| Statistical arbitrage / pairs trading | Renaissance, D.E. Shaw | 🔨 buildable | The daily-bar version is a distant cousin of what Renaissance does, not a small version of it. |
| Index enhancement (指數增強) | the dominant Chinese quant product; AQR-style tilts | 🔨 buildable | The honest framing for most retail 'strategies': the question is not whether you made money, it is whether you beat 0050 after costs and tax. |
| Machine-learning alpha ensembles | Two Sigma, Voleon | 🚫 out of reach | Not a compute problem, a sample-size one. |
| High-frequency market making | Citadel Securities, Jane Street | 🚫 out of reach | You cannot approximate this by trading faster. |

Ask `systematic_strategies` for the full entry on any of these. The
`out of reach` rows are the honest part: they cannot be approximated here, and a
moving-average crossover wearing a famous fund's name would be a worse answer
than saying so.

### Principles systematic investors agree on

**An edge is measured against a baseline, never against zero**  
A 58% win rate means nothing until you know that 56% of all bars rose over the same horizon. Most reported 'strategies' are the market with extra steps.  
*Enforced by: q_backtest returns `baseline` and `net_edge_vs_baseline_pct`*

**Costs decide short-horizon strategies**  
Taiwan round trip is ~0.585% (0.1425% brokerage each way + 0.30% sell-side transaction tax). A 5-day rule averaging +0.4% gross is a losing strategy. Turnover is a cost, not a sign of effort.  
*Enforced by: q_backtest subtracts costs and reports the net figure*

**Diversification across UNCORRELATED bets is the only free lunch**  
Fifteen genuinely independent bets beat one good one. Fifteen Taiwan semiconductor names are approximately ONE bet — the correlation is what counts, not the ticker count.  
*Enforced by: q_pca_decompose and q_lead_lag expose shared factors*

**Size by volatility, not by conviction**  
Conviction is unmeasurable and reliably miscalibrated. Volatility is measurable. Equal-risk sizing beats equal-dollar sizing.  
*Enforced by: risk_estimate sizes to a stated risk budget via ATR*

**Cut losers by rule, not by judgement**  
The stop must be decided before entry, when you have nothing at stake. Millennium's structural advantage is that the rule is not negotiable in the moment.  
*Enforced by: Risk Guard (rg_*), and it never emits a buy signal*

**Capacity decays edge**  
A strategy's returns shrink as money crowds in. Medallion closed to outside capital for exactly this reason. Any public strategy you can read about has already been partly arbitraged away.  
*Enforced by: nothing — it is a reason for humility about any result*

**Out-of-sample, or it is not a result**  
A threshold chosen by looking at the data and then measured on the same data describes that sample. Adding conditions until the numbers improve is fitting noise, and the tell is the effective sample size falling as you add them.  
*Enforced by: q_backtest reports n_effective and names in-sample tuning in `caveats`*


---

## World markets

`q_macro` carries the tape around the Taiwan session.

| Series | Market | Known when |
|---|---|---|
| `sox` (SOX) | us | before the Taipei open |
| `nasdaq` (Nasdaq) | us | before the Taipei open |
| `tsm_adr` (TSM ADR) | us | before the Taipei open |
| `us10y` (US 10Y) | us | before the Taipei open |
| `dxy` (DXY) | fx | before the Taipei open |
| `usdtwd` (USD/TWD) | fx | before the Taipei open |
| `estoxx50` (Euro Stoxx 50) | europe | before the Taipei open |
| `nikkei` (Nikkei) | japan | **trades alongside Taipei** |
| `kospi` (KOSPI) | korea | **trades alongside Taipei** |
| `shanghai` (Shanghai) | china | **trades alongside Taipei** |
| `hangseng` (Hang Seng) | hong_kong | **trades alongside Taipei** |

**The timing column is not decoration.** Tokyo, Seoul, Shanghai and Hong Kong
trade *at the same time as Taipei*, so their stored row is a previous close
while today's move is still happening. Only the `before the Taipei open` rows
are genuinely overnight information.

---

## What arrives when

All times Taipei.

| Time | What | Where |
|---|---|---|
| 08:30 weekdays | Risk Guard pre-market light; macro brief | Telegram |
| 09:00–13:30 | Intraday stop watcher, every ~3 min | Telegram (only if a line breaks) |
| ~15:00 | T86 institutional flow publishes | — |
| 16:30 weekdays | Full harvest → brief → Risk Guard → dashboards | Telegram + console |
| 18:30 | Database backup | — |
| every ~3 min | News poller; watchlist matches pushed | Telegram |

Institutional flow is **structurally end-of-day** — T86 publishes once. No
transport makes it faster. Price against a stop line is the only genuinely
intraday signal here, which is exactly what the stop watcher does.

---

## The tools

You never need to name these. They are here so you know what exists.

### Start here

Orientation, your profile, and what the system currently knows.

| Tool | Plan | What it does |
|---|---|---|
| `start_here` | free | Orientation menu for a new or open-ended question — plain-language asks mapped to the tool that answers each, plus a beginner glossary |
| `sc_capabilities` | free | This map: every tool, what it is for, and the data behind it |
| `session_state` | free | Taipei market phase + trading-calendar status; flags 試撮 pre-open indicative prices so a simulated quote is never read as real |
| `sc_data_status` | free | Pipeline health and data freshness |
| `my_profile` | free | The current user's saved risk profile (conservative/balanced/aggressive) and how to adapt framing to it |
| `set_my_risk_profile` | free | Persist the user's risk tolerance once they state it (writes to DB) |
| `investing_principles` | free | Durable school-neutral investing principles to ground reasoning, emphasised by the user's risk tier |
| `investing_personas` | free | The Steward (conservative) and The Opportunist (aggressive) — how each behaves |
| `systematic_strategies` | free | What quant funds (Renaissance, Citadel, Millennium, AQR, Man AHL, Two Sigma, Chinese quant) actually do and which parts work on THIS data — each marked available / buildable / out_of_reach, plus the principles systematic practitioners converge on |

### Look up one company

The whole beginner path. Everything here is free.

| Tool | Plan | What it does |
|---|---|---|
| `ticker_lookup` | free | Find a ticker id from a company name or partial code — the usual first step |
| `quote` | free | Realtime-ish watchlist quotes (Fugle preferred, TWSE MIS fallback) with authoritative limit-up/down prices; stamps 試撮 indicative prices |
| `price_history` | free | Chart-ready OHLCV history for one ticker |
| `beginner_stock_card` | free | Beginner-friendly factual stock card with grouped numbers and chart-ready points |
| `dividend_calendar` | free | Ex-dividend/ex-rights dates + amounts; answers whether a buyer today still receives the dividend (TWSE 除權除息) |
| `q_valuation` | free | Is a stock cheap or expensive — P/E, P/B and dividend yield per ticker (TWSE BWIBBU) |
| `q_indicators` | free | Latest technical + flow indicators for one ticker |

### Supply chain

Who sells to whom, and where the money is moving inside the chain.

| Tool | Plan | What it does |
|---|---|---|
| `sc_supply_chain_map` | free | Look up ticker → pillar/node/US partner |
| `sc_ticker_momentum` | free | Per-ticker flow with buy streak tracking |
| `sc_sector_momentum` | free | Sector-level flow aggregation by pillar/node |
| `sc_compare_nodes` | **Pro** | Side-by-side node flow comparison |
| `sc_accumulation_screen` | **Pro** | Find tickers with sustained FINI buying |

### Find ideas across the market

Screens over the whole market rather than one name you already have.

| Tool | Plan | What it does |
|---|---|---|
| `flow_leaders_scan` | **Pro** | Market-wide screen for quiet foreign accumulation into a still-cheap, still-flat price (generative sleeper board) |
| `momentum_leaders_scan` | **Pro** | Strong-and-early trend leaders with a mandatory trailing stop; rejects parabolic/retail-pump blow-offs as chases. mode=monitor re-checks held names' stops |
| `market_flow_screener` | **Pro** | Full TWSE/TPEX flow screener across classified and unclassified tickers |
| `scan_limit_board` | **Pro** | Scan the TWSE/TPEX limit-up/limit-down board (EOD) and triage each hit as sleeper vs chase |
| `raw_flow_history` | **Pro** | Daily flow time series for one ticker |
| `u_universe` | free | Unified read: classified-ticker × knowledge × watch-state × signals |

### Quant and evidence

Test an idea before believing it. Read `q_backtest`'s caveats.

| Tool | Plan | What it does |
|---|---|---|
| `q_backtest` | **Pro** | Backtest a single-threshold signal rule |
| `q_backtest_compound` | **Pro** | Backtest multi-condition (AND) compound rules; up to 4 conditions |
| `q_factor_alpha` | **Pro** | Residual alpha after factor exposures are stripped out |
| `q_factor_screen` | **Pro** | Screen by statistical factor exposures (advanced; prefer q_screener for technical setups) |
| `q_quality_score` | **Pro** | Composite fundamental quality score for a ticker |
| `q_screener` | **Pro** | Filter signal-covered tickers by AND-combined indicator conditions |
| `q_regime` | **Pro** | Market regime classification (trend vs chop, risk-on vs risk-off) |
| `q_lead_lag` | **Pro** | Which ticker's move tends to precede another's, and by how many days |
| `q_cointegration_pair` | **Pro** | Test two tickers for a mean-reverting (cointegrated) relationship |
| `q_pca_decompose` | **Pro** | Principal components of the return matrix — what factor is driving the market |
| `q_index_history` | **Pro** | TAIEX / index close history for market context |
| `q_macro` | **Pro** | World markets around the Taiwan session — US (SOX, Nasdaq, TSMC ADR, 10Y), FX (DXY, USD/TWD), Europe (Euro Stoxx 50), and the Asian peers that trade ALONGSIDE Taipei (Nikkei, KOSPI, Shanghai, Hang Seng). Filter with market=; read when_known on each row before calling anything 'overnight' |

### Risk

Sizing before entry, and the stop discipline after it.

| Tool | Plan | What it does |
|---|---|---|
| `risk_estimate` | **Pro** | Position sizing, stop distance, Taiwan limit-down non-fill risk and exit liquidity — what a trade costs if you are wrong |
| `rg_status` | **Pro** | Risk Guard: today's market risk light, its five subitems, and settlement-cash state |
| `rg_positions` | **Pro** | Risk Guard: monitored positions/watch names with warn+exit lines and distance to each |
| `rg_alerts` | **Pro** | Risk Guard: recent alert stream (stop, settlement, light change) — what the operator was already told |
| `rg_checklist` | **Pro** | Risk Guard: six-question entry checklist; blocks or says nothing is stopping you — never recommends a buy |
| `rg_journal_add` | **Pro** | Risk Guard: record a decision made in conversation (writes to DB) |

### News and digests

What was published, and what the system said about it.

| Tool | Plan | What it does |
|---|---|---|
| `n_recent` | free | Recent news articles (RSS + Google News); titles + summaries |
| `n_for_ticker` | free | Articles mentioning a ticker (text-match fallback until Phase 2b entity extraction) |
| `n_source_status` | free | Per-source freshness — verify feeds still updating |
| `d_recent` | **Pro** | Recent cron-generated briefs (pre-market / intraday / post-close) |
| `d_for_date` | **Pro** | All digests for one specific date |

### Watchlist

Free on purpose — the alerts are only useful once this has names in it.

| Tool | Plan | What it does |
|---|---|---|
| `w_add` | free | Add a ticker to the watchlist (writes to DB; same as bot /watch) |
| `w_remove` | free | Archive a watchlist entry (writes to DB; same as bot /unwatch) |
| `w_watchlist` | free | Active watchlist — bot-managed names being monitored |


---

## When something looks wrong

| Symptom | Likely cause |
|---|---|
| `permission denied` on a table | A `mcp_viewer` grant did not land. Run **Actions → DB Migrate (manual)**, type `apply`. |
| `q_macro` returns nothing | `raw_macro` does not exist yet — same migration. |
| No Telegram at all | `TELEGRAM_ENABLED=false`, or a category switch is off. Check the repo variable and the Zeabur service env. |
| Telegram quiet but the run went red | Expected when the kill switch is off: the Actions log is then the only record. |
| The stop watcher never fires | `FUGLE_API_KEY` unset on the Zeabur `worker` service. It logs one line and idles. |
| Data looks stale | Ask for `sc_data_status` — it reports per-table freshness, and the console overview renders the same list. |

---

## For the operator

```bash
.venv/bin/python -m pytest -q        # full suite, no network or DB needed
ruff check .                          # CI enforces this repo-wide
python -m src.harvester.daily         # the nightly pipeline
python -m src.cron.brief --mode post_close
python scripts/build_tutorial.py      # regenerate THIS file
```

The console lives behind `CONSOLE_TOKEN`, which is deliberately **not** the same
secret as `MCP_BEARER_TOKEN` — sharing a dashboard link should not share the API
key. If `CONSOLE_TOKEN` is unset it falls back to the API token, which is the
old behaviour and the reason to set it.

---

## How this page stays true

It is generated from the running system by `scripts/build_tutorial.py`. Tool
names, plans, personas, strategies and macro series are read from the code, not
retyped. `tests/test_tutorial.py` rebuilds it and fails CI if the committed file
differs — so adding a tool without updating this page turns the build red.

Edit the prose in `scripts/build_tutorial.py`, run it, and commit both files.
