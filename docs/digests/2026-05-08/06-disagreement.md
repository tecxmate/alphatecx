---
date: 2026-05-08
task: 06-disagreement
inputs: [docs/digests/2026-05-08/01-quant.md, n_for_ticker]
generated_by: antigravity-agent (worked example; future runs will be a Claude Scheduled Task)
data_as_of: 2026-05-07 close (Taipei)
news_window: 3 days
---

# 2026-05-08 — Quant ↔ News disagreement scan

For each name flagged by this morning's quant digest, check whether news
narrative agrees, contradicts, or is silent. The silence is itself a
signal: institutional flow without retail/media attention is the
asymmetric setup most worth investigating.

## Convergence (signal + narrative agree)

These names had both quant flags AND visible news that points the same
direction. Lower asymmetric edge — the move is already in the public
narrative.

| Ticker | Quant flag | News evidence |
|---|---|---|
| **2317 Foxconn** | foreign_net_z20 = 2.93, +216M shares 5d | **「三大法人買賣超 – 外資買超(2330)台積電、(2317)鴻海」** — Foreign net buy of TSMC + Foxconn explicitly named in domestic flow report |
| **2301 Lite-On** | foreign_net_z20 = 2.74, RSI 73, at 52w high | **「光寶科續寫歷史新高...外資買超464億元」** — Lite-On at historic high, broader market foreign net buy of 46.4B TWD |
| **2308 Delta** | foreign_net_z20 = 1.19, RSI 77, at 52w high | **DIGITIMES: "Delta Electronics expands Malaysia presence"** — supply-chain expansion narrative supports growth case |

## Silent strength (signal without narrative)

These names showed positive quant flags but **zero news coverage in the
last 3 days**. Foreign capital is acting without the public catching up.
The asymmetric edge candidates.

| Ticker | Quant flag | News in 3d |
|---|---|---|
| **3231 Wistron** | foreign_net_z20 = 1.54, RSI 63 | 0 |
| **2382 Quanta** | foreign_net_z20 = 1.30, RSI 65 | 0 |
| **4958 Zhen Ding** | foreign_net_z20 = 1.36, RSI 79 (overheated) | 0 |
| **6488 GlobalWafers** | RSI 77, at 52w high | 0 |

Worth flagging that all four are sub-tier infrastructure plays — not the
TSMC / Foxconn names that the headline cycle cares about. The
narrative-naive flow scan is finding stocks the narrative-aware reader
would miss.

## Divergence (signal contradicts)

The single sharpest disagreement in today's data:

### 3443 GUC (Global Unichip)
- **Quant**: RSI **87.8** (extreme), MACD histogram **143.2** (extreme),
  at 52-week high, **but** foreign_net_z20 = **−1.82** (foreign selling)
- **News**: **0 mentions in 3 days**
- **Narrative-naive read**: institutional distribution into retail
  momentum euphoria. The technicals are screaming "buy", flow is
  saying "sell", and there's no news catalyst to anchor either side.
- **Interpretation**: classic distribution-into-strength pattern. The
  fact that nobody is writing about it (despite the price action)
  reinforces the read — institutions exit quietly when retail is
  most excited.

This is the highest-leverage candidate for invoking the
`decide-on-ticker` Skill once Phase 2b (entity extraction) lands. Until
then, the human read is: extreme technicals + institutional flow
opposite + zero narrative cover = high-probability distribution event.

## Cross-cutting note: where today's news is concentrated

Of 800 articles ingested this morning across 12 sources, the tickers
explicitly named are heavily concentrated:

- 2330 TSMC: dozens of mentions
- 2317 Foxconn, 2308 Delta, 2301 Lite-On: handful each
- Everything else: 0–2 mentions

Translation: the public narrative is **TSMC-centric**, with a tier-2
cluster around server-ODM/power. The companies our quant tools flag
deeper in the supply chain (Wistron, Quanta, Zhen Ding, GlobalWafers)
operate in a relative news vacuum — which is also why they're where
the asymmetric edge lives if you trust the flow.

## Next steps

1. The four "silent strength" names should drive the next set of
   `decide-on-ticker` invocations once the Skill is wired up.
2. 3443 GUC divergence will be most informative when Phase 2b's entity
   extraction runs — it'll quantify whether the news silence is
   *actually* silent or whether the simple text-match missed coverage
   under different naming.
3. Worth running this scan daily for a week and seeing whether the
   silent-strength names converge on a coverage uplift before they
   reverse — that pattern would be the system's most replicable
   "lean and bold" trade setup.
