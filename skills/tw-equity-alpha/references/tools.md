# Tool playbook & data caveats

Read before any data pull. These are the MCP tools this workflow relies on, what each gives, the call
quirks that will otherwise waste turns, and the data-staleness traps.

## Board, discovery & realtime tools (use these FIRST for Modes 1 & 4)

These four newer tools automate work that used to be done by hand. They live on the same Alpha MCP
as the datum tools below (same connector as `scan_limit_board` / `q_valuation`); call them by name.
Every response carries `_source` / `_as_of` / `_freshness`.

- **`flow_leaders_scan`** — the **Mode 1 discovery engine**. One market-wide call runs the entire
  Sleeper-Score funnel (accumulation-into-flat + cheap + under-owned + no-froth + revenue inflection)
  and returns ranked hits with a `sleeper_score` (0–100), `sleeper_flags`, and `triage`
  (`sleeper`/`watch`/`chase`). This is the 拓凱-finder — use it *before* hand-screening. Key args:
  `date` (as-of, for post-mortems/backtests), `markets`, `min_turnover_twd`, `include_loss`,
  `limit`. **Don't set `min_foreign_z`** — a multi-week grinder has no closing-day z-spike, so gating
  on z drops the very names you want. Coverage is TWSE-effective (needs a harvested price; most TPEX
  names are unpriced and won't appear) — for a TPEX name, fall back to the by-hand funnel.
- **`scan_limit_board`** — the **Mode 4 board engine**. Fetches the live TWSE/TPEX limit-up/down
  board (EOD) and triages each hit `sleeper`/`watch`/`chase` with the same rubric — automating the
  screenshot read. Args: `direction`, `markets`, `min_pct`, `locked_only`, `min_turnover_twd`,
  `date` (past session post-mortem). EOD only (no intraday).
- **`dividend_calendar(ticker_id, date)`** — the **ex-dividend catalyst / trap check**. Returns the
  most-recent-past and next-upcoming ex date + cash amount, and `already_ex`. **Run before quoting a
  yield or citing an ex-div catalyst:** if `already_ex` is true, a new buyer does NOT get it and the
  yield is historical, not forward. Official TWSE data; never synthesise a forward yield.
- **`session_state(date)`** + **`quote(symbols[])`** — the realtime layer. `session_state` gives the
  live Taipei `phase` and `price_is_indicative` (true during the 08:30–09:00 試撮 auction — the
  displayed price is simulated, not a trade). `quote` returns realtime-ish last/bid/ask + the
  authoritative limit-up/down prices for a **watchlist (≤100 codes)**; a name with no print yet
  returns `last_price: null` (not a fake price). Use these instead of asking for a screenshot when
  you need the current print — but confirm `price_is_indicative` is false before treating it as real.

## Which tool for which datum

**Valuation / identity**
- `Alpha:q_valuation` — P/E, P/B, dividend yield, close, sector/pillar. Primary valuation source.
  ⚠ Covers **TWSE (上市)**; often returns **empty for TPEX (上櫃)** names → fall back to `yf_*`.
- `Alpha:ticker_lookup` — resolve code ↔ company name. Use when unsure of a ticker.
- `yahoo-finance:yf_info` / `yf_quote` — profile, ratios, real-time-ish quote (esp. for TPEX names).

**Institutional flow (the core signal)**
- `Alpha:raw_flow_history(ticker_id, days)` — daily **foreign / trust (投信) / dealer / total** net
  shares. The workhorse for the accumulation-vs-distribution read. Pull ~15–20 sessions. Read the
  *pattern*: net foreign buying into a flat price = accumulation (bullish); foreign selling into a
  rising price = distribution (bearish); foreign-sell + 投信-buy on a ramp = fragile 投信-driven top.
- `Alphatecx:twse_inst_flow` — alternative 三大法人 net-flow source.
- `Alpha:sc_ticker_momentum` / `market_flow_screener` — institutional-flow momentum / market screen
  (AI-supply-chain universe).

**Ownership & leverage**
- `Alphatecx:twse_foreign_holdings(code)` — foreign held shares, **held %**, and **room %**. Low
  held % + high room = under-owned (Sleeper Score #4) and a selloff shield.
- `Alphatecx:twse_margin_balance(code)` — margin (融資) balance vs limit + short (融券) balance. Froth
  check: tiny margin + ~0 short = cash-driven, clean.

**Price / structure**
- `Alphatecx:twse_daily_history(code, days)` — **fresh (T+1)** daily OHLCV; **auto-detects TPEX**.
  Use this for recent trajectory, base-vs-parabola, % move over N weeks, levels.
- ⚠ `Alpha:price_history` — can be **stale (~2 months behind)**. Prefer `twse_daily_history` for
  anything recent.

**Fundamentals / inflection**
- `Alphatecx:monthly_revenue(code)` — latest MOPS monthly revenue: value, **YoY %, MoM %, YTD YoY %**.
  The fastest fundamental-inflection read. Run it on the name **and 2 peers/customers** to
  triangulate. (Files by the ~10th of each month — a recurring near-term catalyst.)
- `yahoo-finance:yf_financials` — income/balance/cash-flow. ⚠ Can throw a Timestamp serialization
  error; if so, fall back to filings / TW-native tools.
- `yf_earnings`, `yf_analyst`, `yf_dividends`, `yf_holders` — EPS history/estimates, targets
  (coverage is thin for mid-caps — low analyst count is itself a re-rating optionality signal),
  dividends, holders.

**News / catalysts / research**
- `Alpha:n_for_ticker` / `n_recent` — ticker news (can be flaky; retry or use web_search).
- `web_search` — macro drivers, ex-dividend dates, corporate actions, competitor/industry structure,
  peer status, and to locate filings. Verify claims across sources.
- `web_fetch` — pull a specific article/filing page the user or a search surfaced.

## Call quirks (don't lose turns to these)
- **Transient errors** — `consuming input failed: SSL connection has been closed unexpectedly` and
  `No approval received` are transient. **Retry the identical call once**; it usually succeeds.
- **`q_screener` scope** — only the **classified AI-supply-chain universe**. It will *not* find
  petrochem/defense/textile/traditional sleepers. For those, screen by hand (valuation → flow →
  ownership per candidate). Don't conclude "no candidates" from an empty q_screener.
- **TPEX (上櫃) coverage** — `q_valuation` and some Alpha feeds skip 上櫃 names (empty result). Use
  `twse_daily_history` (auto-detects) and `yf_*` for those.
- **Ticker code care** — codes are easy to misremember (e.g., 信邦 = 3023, not 3376). Confirm with
  `ticker_lookup` when a result's company name doesn't match what you expected.

## Data-staleness traps (state these to the user)
- **T+1 feeds** (`twse_daily_history`, `raw_flow_history`, `twse_foreign_holdings`, `monthly_revenue`,
  `flow_leaders_scan`) run **through the prior close** — flow/valuation/ownership are as-of the last
  harvested session, not today. For the **live print**, use `quote` (+ `session_state` to confirm the
  price isn't 試撮 pre-open noise); a user screenshot is now a fallback, not the only option. Always
  say which session the analytical data is as-of.
- A memo/dashboard's "current price" is only as fresh as its build date — if today's action gapped,
  the stated entry zones may be stale; re-check the live level against the plan.
- `monthly_revenue` is **top-line only** — it does not reveal margin mix. Use it for direction, not
  earnings quality; the margin read comes from quarterly filings.

## Minimum viable pull (per name)
1. `q_valuation` (or `yf_quote`+`yf_info` for TPEX) — cheap?
2. `raw_flow_history` ~18 sessions — accumulating or distributing?
3. `twse_foreign_holdings` — under-owned?
4. `twse_daily_history` ~20–25 bars — base or parabola? levels?
Then, for conviction: `twse_margin_balance` (froth), `monthly_revenue` on name + 2 peers
(inflection), `web_search` (catalysts, ex-div, competitors).
