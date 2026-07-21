# Handoff — new Alpha MCP tools for Claude Desktop (tw-equity-alpha)

Four new tools are live on the Alpha MCP server. They need no client config change —
Claude Desktop discovers them via `tools/list` on connect. **After the Vercel redeploy of the
latest `main`, restart Claude Desktop (or toggle the connector off/on) so it re-reads the tool
list.** Verify with `sc_capabilities` (the four appear in its `tools` array) or `sc_data_status`.

All responses keep the house envelope: `_source`, `_as_of`, `_freshness`. Nothing here places
orders or gives advice — they are data tools.

---

## 1. `flow_leaders_scan` — the generative sleeper board ★

**Use when:** "Who is being quietly accumulated right now while still cheap and flat?" — finding
candidates *before* they move, not triaging what already moved.

Market-wide screen for sustained foreign net buying into a still-cheap, still-flat price (the
拓凱 signature). Returns hits with a `sleeper_score` (0–100), `sleeper_flags`, and `triage`
(`sleeper` / `watch` / `chase`).

- Key args: `window_days=20`, `min_buy_day_ratio=0.65`, `max_price_move_pct=8.0`, `max_pe=20`,
  `min_turnover_twd=10_000_000`, `markets=["TWSE","TPEX"]`, `include_loss=false`,
  `sort_by="sleeper_score"`, `date=None` (as-of; defaults to latest harvested session),
  `limit=50`.
- Read `triage` first: **`sleeper`** = cheap + accumulating + flat, no anti-flag; **`chase`** =
  any anti-flag (no earnings, story premium, distributing, already ran); **`watch`** = neither.
- `accumulation_into_flat` is the boolean signature; `sleeper_score` is the ranking.
- **Do not raise `min_foreign_z` to gate** — it's off by default on purpose. A multi-week
  grinder has no closing-day z-spike, so gating on z drops exactly the names you want.
- Coverage: needs a harvested price, so effectively TWSE (~1.1k names). Most TPEX names are
  unpriced and won't appear. Flatness is median-anchored (robust to a corrupt print).
- Example: `flow_leaders_scan(markets=["TWSE"], limit=30)` then read the `sleeper` rows.
- Validated: 拓凱 4536 ranks in the top 10 as of 2026-06-30; 日馳 1526 is `chase` as of 2026-07-17.

## 2. `session_state` — "is this price real?" ★

**Use before quoting any intraday price**, or to answer "is the market open / is this pre-open
noise?".

Returns the live Taipei `phase` (`pre_open_auction` / `regular` / `after_hours` / `closed`),
`is_trading_day`, and `price_is_indicative`. During **08:30–09:00** the price is a 試撮
(simulated auction) — `price_is_indicative: true` with a `warning`. **If indicative, never
present the number as a real trade or a fill.**

- Arg: `date="YYYY-MM-DD"` to check a specific day's trading status (holiday/weekend). Omit for
  live now.
- `calendar_source: "calendar"` means the holiday table answered; `"weekend_only"` means it
  couldn't be read (weekends only — treat holiday status as unknown).
- `closed_reason` names the holiday when shut.

## 3. `quote` — realtime-ish watchlist

**Use for a watchlist** (≤100 codes), not for scanning the market (use the two scanners for
breadth).

`quote(symbols=["2330","4536","6488"], source="auto")` → per-symbol last/prev/open/high/low, best
bid/ask, and the **authoritative limit-up/limit-down prices** (`limit_up_price`/`limit_down_price`,
tick-rounded). Draws from **Fugle** (keyed realtime, preferred) or **TWSE MIS** (fallback);
`source="auto"` picks Fugle when the key is configured, and `_quote_source` reports which answered.
Response carries the session `phase` + `price_is_indicative`.

- A symbol with no trade yet returns `last_price: null` — that is correct, not an error; do not
  substitute prev close as if it were a trade.
- `is_at_limit` / `limit_direction` come straight from TWSE's `u`/`w`.
- Unknown codes come back in `missing`.
- Source is delayed/closed outside 09:00–13:30 (`_freshness` says which). Pair with
  `session_state` when the number could be pre-open noise.

## 4. `dividend_calendar` — "does a buyer today get the dividend?"

**Use before quoting a dividend yield** or discussing income — the check that stops presenting an
already-ex yield as if it were forward.

`dividend_calendar(ticker_id="2357", date=None)` →
- `most_recent`: `{ ex_dividend_date, ex_type (息/權/權息), cash_dividend, pre_ex_close,
  reference_price, already_ex }`.
- `upcoming`: the next ex event (if any), and `buyer_today_receives_upcoming`.

If `most_recent.already_ex` is true, a **new buyer does not receive that dividend** — its yield is
historical, not forward. Values are official TWSE data. **No forward/consensus estimate is ever
synthesised** — if you need a forward yield, label it `source: manual`/`web`, never present a
computed one as data. Coverage is TWSE-listed names.

- Validated: 華碩 2357 as of 2026-07-10 → ex 2026-07-01, cash 42.0, `already_ex: true`.

---

## How these map to the board-triage / research loop

| Question | Tool |
|---|---|
| Who's being quietly accumulated while cheap and flat? | `flow_leaders_scan` |
| Why did the board go limit-up, and which are real? | `scan_limit_board` (existing) + this rubric |
| Is this price real, or pre-open 試撮 noise? | `session_state` (+ `quote`) |
| Live prices + limit levels for my watchlist? | `quote` |
| Does a buyer today still get the dividend? | `dividend_calendar` |

## Still missing (don't fabricate)
- **Consensus forward estimates / forward P/E-PEG**: no free source wired. Label `source:
  manual`/`web`; never synthesise one and present it as data.
- **TPEX valuation (上櫃 P/E gap)** and **financial-statements deep-dive**: not yet adopted
  (needs a FinMind token). `flow_leaders_scan` is TWSE-effective until then.
- **Positions / order fills**: not built (broker isn't 永豐). The agent analyses; the human trades.
