# Tool Spec — `scan_limit_board`

A programmatic scanner for the Taiwan limit-up / limit-down board (漲停/跌停), to add to the Alpha
MCP server. Replaces manual screenshot-reading with a real scan that returns *who's at the limit*
**and** enriches each hit with the flow/valuation/ownership signals already in the Alpha/Alphatecx
stack — so the output is directly usable for the `tw-equity-alpha` board-triage mode ("who's
limit-up AND still a sleeper vs. who's a chase").

---

## 1. Tool signature

```
scan_limit_board(
  direction:        "up" | "down" | "both"   = "up",
  mode:             "realtime" | "eod"        = auto,   # auto: realtime during session, else eod
  markets:          ["TWSE","TPEX"]           = both,
  min_pct:          float                     = 9.5,    # |pct_change| threshold to include
  locked_only:      bool                      = false,  # only one-sided-book locks
  min_turnover_twd: int                       = 0,      # liquidity floor
  enrich:           bool                      = true,   # join flow/valuation/ownership
  date:             "YYYY-MM-DD"              = today,  # for eod historical scans
  limit:            int                       = 200
)
```

`mode=auto`: use `realtime` when Asia/Taipei time is within the regular session (09:00–13:30 on a
trading day); otherwise `eod` for `date` (defaults to the last close).

---

## 2. Data sources / endpoints

### 2a. Realtime — TWSE MIS (authoritative limit prices)
`GET https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=<list>&json=1&delay=0`

- `ex_ch` is a `|`-delimited list of `tse_<code>.tw` (上市) / `otc_<code>.tw` (上櫃). Batch **~50 per
  request** (URL-length + rate limits); paginate the universe.
- Session: hit `https://mis.twse.com.tw/stock/index.jsp` once to obtain the cookie before querying.
- Response `msgArray[]` fields used:

  | Field | Meaning |
  |---|---|
  | `c` | ticker code |
  | `n` | name |
  | `z` | last trade price (成交價) — may be `-` pre-first-print → fall back to `o`/`y` |
  | `y` | prev close (昨收) |
  | `u` | **limit-up price (漲停價)** — authoritative, already tick-rounded |
  | `w` | **limit-down price (跌停價)** — authoritative |
  | `o`,`h`,`l` | open / high / low |
  | `v` | cumulative volume (張) |
  | `tv` | last-trade volume |
  | `a` / `f` | 5-level ask prices / ask volumes |
  | `b` / `g` | 5-level bid prices / bid volumes |
  | `t`,`d` | time / date |

  **Use `u`/`w` directly** — do not recompute the limit price in realtime. TWSE has already applied
  the tick rule (§3), including band-boundary edge cases.

### 2b. End-of-day — official OpenAPI (no auth)
- TWSE all-stocks close: `GET https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`
  (or `https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date=YYYYMMDD&type=ALLBUT0999`
  which includes 漲跌(+/-) and 漲跌價差, easing change computation).
- TPEX mainboard close: `GET https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`.
- EOD payloads give close + change but **not** an explicit limit flag → compute the limit price via
  §3 from `prev_close`, or infer limit-hit when `close == computed_limit_price` (exact tick match)
  **or** `round(pct_change, 2) ∈ {+9.9…+10.0}` within one tick.

### 2c. Universe list
Reuse the existing `dim_ticker`. For a fresh pull: ISIN list
`https://isin.twse.com.tw/isin/C_public.jsp?strMode=2` (上市) / `strMode=4` (上櫃).
**Exclude** 興櫃 (emerging board — *no* price limit), ETFs/ETNs when `markets` is equities-only,
warrants (權證), first-trading-day IPOs (no/expanded limit), and halted (暫停交易) names.

---

## 3. Limit-price computation + tick rounding (EOD fallback)

Daily limit is **±10%** of prev close. The limit price is snapped to a valid tick:

- **漲停價 (limit-up)** = the **highest** tick-valid price **≤** `prev_close × 1.10` → *floor to tick*.
- **跌停價 (limit-down)** = the **lowest** tick-valid price **≥** `prev_close × 0.90` → *ceil to tick*.

### Tick-size table (TWSE/TPEX equities)

| Price band P (NT$) | Tick |
|---|---|
| P < 10 | 0.01 |
| 10 ≤ P < 50 | 0.05 |
| 50 ≤ P < 100 | 0.10 |
| 100 ≤ P < 500 | 0.50 |
| 500 ≤ P < 1000 | 1.00 |
| P ≥ 1000 | 5.00 |

**Critical detail:** the tick is chosen by the band of the *candidate limit price*, not the prev
close — a name can straddle a boundary (e.g. prev_close 96 → ×1.1 = 105.6, which lands in the
100–500 band → 0.5 tick → limit-up 105.5).

```python
TICKS = [(10,0.01),(50,0.05),(100,0.10),(500,0.50),(1000,1.00),(float('inf'),5.00)]

def tick_of(price):
    for hi, t in TICKS:
        if price < hi:
            return t
    return 5.00

def limit_up(prev_close):
    raw = prev_close * 1.10
    t = tick_of(raw)
    # floor to tick; use integer cents to avoid float drift
    return round((raw // t) * t + 1e-9, 2)

def limit_down(prev_close):
    raw = prev_close * 0.90
    t = tick_of(raw)
    import math
    return round(math.ceil(round(raw / t, 6)) * t, 2)
```

Rare double-boundary cases exist; in realtime always prefer MIS `u`/`w`, and reconcile the EOD
computation against MIS at least once per session to validate the table.

---

## 4. Lock / at-limit detection

```
at_limit_up   = last_price >= u        # (>= to tolerate float)
at_limit_down = last_price <= w
```

**Locked** = at the limit *with a one-sided book* (the 漲停鎖住 state):

```
locked_up   = at_limit_up   AND sum(ask_vols[0:5]) == 0 AND bid_vol_at(u) > 0
locked_down = at_limit_down AND sum(bid_vols[0:5]) == 0 AND ask_vol_at(w) > 0
```

Realtime only: track `lock_time` = first timestamp `at_limit` became true (persist per ticker per
day). `bid_vol_at_limit` (up) / `ask_vol_at_limit` (down) = queued size at the limit price — a proxy
for lock strength.

EOD: `locked` is unknowable from close-only data → set `is_locked = null`, report `is_at_limit`.

---

## 5. Enrichment join

For each hit, left-join by `ticker_id` to the existing Alpha/Alphatecx sources (batch these; don't
N+1 per name):

| Enriched field(s) | Source table / tool |
|---|---|
| `name`, `market`, `industry` | `dim_ticker` |
| `pe_ratio`, `pb_ratio`, `dividend_yield` | `raw_twse_valuation` (`q_valuation`) — **empty for many TPEX; fall back to yf** |
| `foreign_net_5d`, `foreign_net_z20`, `trust_net_5d`, `dealer_net_5d` | `raw_flow_history` / `twse_inst_flow` |
| `foreign_held_pct`, `foreign_room_pct` | `twse_foreign_holdings` |
| `margin_pct_of_limit`, `short_balance` | `twse_margin_balance` |
| `rsi_14`, `sma_50`, `sma_200`, `rs_vs_market_60`, `pct_below_52w_high` | `view_latest_signals` (`q_indicators`) |
| `revenue_yoy_pct`, `revenue_mom_pct` | `monthly_revenue` |

Set enriched fields to `null` on miss (TPEX valuation gaps, thin-flow names) — never drop the hit.

---

## 6. `sleeper_flags` / triage score (applies the tw-equity-alpha rubric)

Compute per hit so the scanner outputs board-triage, not just a list:

```
flags = []
if pe_ratio not null and 0 < pe_ratio < 20:            flags += "cheap"
if dividend_yield >= 3:                                 flags += "yield"
if foreign_held_pct not null and foreign_held_pct < 20: flags += "under_owned"
if foreign_net_z20 not null and foreign_net_z20 > 1:    flags += "accumulating"
if pct_below_52w_high not null and pct_below_52w_high < -25: flags += "off_highs"   # correction, not virgin
if margin_pct_of_limit not null and margin_pct_of_limit < 5: flags += "no_froth"

# anti-flags (chase / trap signals)
if pe_ratio is null:                                    flags += "no_earnings"      # loss / cyclical trough
if pe_ratio not null and pe_ratio > 40:                 flags += "story_premium"
if foreign_net_5d not null and foreign_net_5d < 0 and is_at_limit: flags += "distributing_into_pop"
```

`triage = "sleeper"` if `{cheap, accumulating}` ⊆ flags and no anti-flag; `"chase"` if any
anti-flag; else `"watch"`. (Mirrors `references/screening.md`.)

---

## 7. Response schema

```json
{
  "_source": "twse_mis",
  "_mode": "realtime",
  "_as_of": "2026-07-16T13:24:00+08:00",
  "direction": "up",
  "count": 2,
  "hits": [
    {
      "ticker_id": "9921",
      "name": "巨大",
      "market": "TWSE",
      "industry": "運動休閒",
      "prev_close": 80.0,
      "limit_price": 88.0,
      "last_price": 88.0,
      "pct_change": 10.0,
      "is_at_limit": true,
      "is_locked": true,
      "lock_time": "13:05:12",
      "bid_vol_at_limit": 3227,
      "ask_vol": 0,
      "volume_shares": 3227000,
      "turnover_twd": 283000000,
      "pe_ratio": 41.4, "pb_ratio": 3.2, "dividend_yield": 1.1,
      "foreign_net_5d": 1250000, "foreign_net_z20": 1.8,
      "foreign_held_pct": 22.3, "foreign_room_pct": 55.0,
      "margin_pct_of_limit": 4.1, "short_balance": 0,
      "rsi_14": 71.2, "pct_below_52w_high": -8.5,
      "revenue_yoy_pct": 16.0, "revenue_mom_pct": 7.5,
      "sleeper_flags": ["under_owned"],
      "triage": "chase"
    },
    {
      "ticker_id": "XXXX",
      "name": "…",
      "...": "…",
      "sleeper_flags": ["cheap","yield","under_owned","accumulating","no_froth"],
      "triage": "sleeper"
    }
  ],
  "errors": []
}
```

EOD scans: `is_locked`, `lock_time`, `bid_vol_at_limit`, `ask_vol` → `null`.

---

## 8. Implementation notes / gotchas

- **MIS batching + rate limits:** ~50 symbols/request; stagger 3–5 s between batches; cache the
  universe; a full-market realtime sweep is ~40–60 batched calls → budget ~3–4 min, or maintain a
  persistent poller and serve from cache.
- **Prefer `u`/`w` over computed limits in realtime** — TWSE is authoritative on tick edge cases.
- **Reconcile the tick table** against MIS `u`/`w` once per session; alert on drift (rules can change).
- **`z` can be `-`** before the first print (pre-open / thin names) → treat as no-trade, use `y`/`o`,
  and don't emit a false limit hit off a 試撮 (pre-open simulated) price. Only scan 09:00–13:30.
- **No-limit / special securities:** exclude 興櫃 (no limit), first-day IPOs and certain reissues
  (expanded/again no limit), full-delivery (全額交割) oddities, and halted names.
- **TPEX valuation gaps:** `raw_twse_valuation` returns empty for many 上櫃 names → yf fallback or
  leave null (do not drop the hit — 上櫃 is where a lot of the limit-up action is).
- **Time zone:** Asia/Taipei throughout; a trading-calendar check is required (typhoon closures,
  e.g. 2026-07-10, and holidays — TWSE publishes the calendar).
- **Idempotent EOD:** cache by `(date, market)` so historical scans are cheap and repeatable.

---

## 9. Example calls

```
# live board, sleepers only
scan_limit_board(direction="up", locked_only=true, min_turnover_twd=20_000_000)
  → filter client-side on triage == "sleeper"

# EOD post-mortem of a past session (e.g., the bike-rotation day)
scan_limit_board(direction="up", mode="eod", date="2026-07-16")

# limit-DOWN washout scan during a selloff, TWSE only
scan_limit_board(direction="down", markets=["TWSE"], min_pct=9.0)
```

---

*Built to feed `tw-equity-alpha` Mode 4 (board triage). The scanner answers "who's at the limit";
the `triage`/`sleeper_flags` answer "and which of them is a base-breakout vs. a chase" — automating
the screenshot-reading loop. Not investment advice; a data tool.*
