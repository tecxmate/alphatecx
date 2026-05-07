---
name: decide-on-ticker
description: Dual-agent (narrative-naive + narrative-aware) decision skill for one Taiwan AI supply-chain ticker. Naive pass reasons from quant data only; aware pass adds news + sentiment. Reconciler step compares them. Output is a dated thesis MD in docs/theses/.
mcp_required: alphatecx-v2 (https://alphatecx-v2-mcp.vercel.app)
output_to: docs/theses/YYYY-MM-DD-<ticker>-<thesis-slug>.md
status: naive_pass_operational; aware_pass_pending_phase_2_news
---

# decide-on-ticker

You are running a structured decision skill on a single ticker. The goal
is **a lean, bold thesis**: one specific take, with a named catalyst and a
named invalidation. Not a wishy-washy "looks interesting" summary.

The architecture is **two reasoning passes that must not share context**.
Run them as separate sub-tasks; finish each before starting the next.

## Inputs from the user

- `ticker_id` (required): TWSE/TPEX code, e.g. `2330` for TSMC.
- `thesis_slug` (optional): short name for the thesis, e.g.
  `foundry-cycle`, `server-odm-acceleration`. If omitted, propose one
  in the reconciliation step.
- `horizon` (optional, default `3-6 months`): how far out the thesis runs.

## Step 1 — Read prior context

Before either pass, read existing project files so you don't repeat
work or contradict yourself:

1. **`docs/journals/<ticker>-*.md`** — prior decisions on this ticker
2. **Most-recent `docs/theses/*-<ticker>-*.md`** — open theses (any status)
3. **Last 3 `docs/digests/*/01-quant.md`** — recent quant context

If there's an existing **active** thesis on this ticker, your output
should be one of: a) confirm and append to journal; b) refine the
existing thesis (edit the existing MD, don't create a new one); or
c) close the existing as `superseded` and write a new thesis.

## Step 2 — Naive pass (NO NEWS)

Open a fresh sub-task. The system prompt is just this paragraph.
You have access to the alphatecx-v2 MCP and that is your **only**
source of input. You do not have access to news, sentiment scores,
analyst ratings, social media, or any text-derived signal. You are
reasoning from structured data only.

> You are evaluating ticker `{ticker_id}` from quantitative data only.
> You have no information about news, narrative, or analyst views.
> Reason from prices, flows, indicators, supply-chain position, and
> backtest results. Do not speculate about events you can't observe
> in the data. If a recent move is unexplained, say so plainly.

Required MCP calls:

1. `sc_supply_chain_map(search="<ticker>")` — confirm pillar/node
2. `q_indicators(ticker_id)` — full 14-field indicator stack
3. `sc_ticker_momentum(ticker_id="<ticker>")` — flow context
4. `raw_flow_history(ticker_id="<ticker>", days=30)` — flow time series
5. `sc_sector_momentum(pillar=<this-tickers-pillar>)` — peers
6. **At least two `q_backtest` or `q_backtest_compound` calls** that
   test the specific signal pattern you see on this ticker right now.
   Don't reuse generic backtests — design rules that match what the
   data is doing.

Write a structured naive view to a scratch file
`/tmp/naive-<ticker>-<run-timestamp>.md`:

```markdown
# Naive view — <ticker>

## What the data says
- Indicator stack:
- Flow regime (z-scores, streaks):
- Position vs sector peers:
- Position vs broad market:

## Signal pattern that matches now
- Pattern: <e.g. "RSI<40 inside MACD>0 uptrend">
- Backtest: <hit rate / avg / n> from q_backtest_compound

## Naive verdict
- Direction: bullish | bearish | neutral
- Conviction (1-5): <number>
- Catalyst (data-only): <what would confirm in data?>
- Invalidation (data-only): <what data would flip it?>
- Honest gaps: <what couldn't be answered from data alone?>
```

## Step 3 — Aware pass (data + news)

> ⚠️ **Pending Phase 2.** News pipeline (RSS harvester + sentiment)
> isn't built yet. Until it lands, the aware pass should be skipped
> and the reconciliation step (Step 4) treats the naive view as the
> final view, with a note in the thesis that "aware pass is pending
> news pipeline."

When Phase 2 lands, Step 3 becomes:

Open a separate sub-task. This pass DOES get news context. Use:

- `n_for_ticker(ticker_id="<ticker>", days=14)` — recent news
- `n_sentiment_summary(ticker_id="<ticker>")` — sentiment trend
- All the same `q_*` and `sc_*` calls as Step 2

Write to `/tmp/aware-<ticker>-<run-timestamp>.md`:

```markdown
# Aware view — <ticker>

## Narrative summary
<2-3 paragraphs on what the news + sentiment is saying>

## Aware verdict
- Direction:
- Conviction (1-5):
- Catalyst (narrative-driven):
- Invalidation:
- Honest gaps:

## Where the narrative sources disagree
<if news outlets / analysts diverge, capture that>
```

## Step 4 — Reconcile

Read both `/tmp/naive-*.md` and `/tmp/aware-*.md` (or just naive if
Phase 2 isn't ready). Compare them.

Three possible outcomes:

1. **Agree** — both passes point the same direction with similar
   conviction. The thesis is high-confidence; risk = both are
   reading the same regime.
2. **Disagree on direction** — one bullish, one bearish. **This is
   the most valuable case.** Investigate which side is missing
   something. Does the data see distribution the narrative
   hasn't noticed? Does the narrative see a catalyst the data
   hasn't priced?
3. **Agree on direction, disagree on size** — same direction, very
   different conviction. Worth understanding why one signal is
   weaker.

## Step 5 — Write the thesis

Output: `docs/theses/YYYY-MM-DD-<ticker>-<thesis-slug>.md`.

Required frontmatter (matches `docs/theses/README.md`):

```markdown
---
ticker: <ticker_id>
company: <company_name>
opened: YYYY-MM-DD
status: active
last_review: YYYY-MM-DD
horizon: <user-provided or default>
catalyst: <one line>
invalidation: <one line>
inputs: [<MCP tool list>]
sources_naive: [q_*, sc_*]
sources_aware: [n_*]   # omit if aware pass was skipped
naive_conviction: <1-5>
aware_conviction: <1-5 or "n/a">
disagreement: agree | disagree-direction | disagree-size | n/a
---

# <Company> (<ticker>) — <thesis title>

## TL;DR
<2-3 sentences. The take. No hedging language.>

## What the data sees (naive)
<from Step 2>

## What the narrative sees (aware)
<from Step 3, or "Pending Phase 2 news pipeline.">

## The reconciliation
<from Step 4 — where they agree, where they disagree, what that means>

## Signal stack at thesis open
<copy q_indicators output as a table — historical reference>

## Backtest grounding
<the q_backtest_compound runs that justify the pattern, with hit-rate
and sample size — be honest about thin data>

## Catalyst & invalidation
- **Catalyst**: <specific data point or event that confirms>
- **Invalidation**: <specific data point that flips>
- **Next review**: <ISO date or trigger condition>

## Position sizing
<if user is sizing a position, what fraction of book and why; otherwise
"not sized — analytical only">
```

## Step 6 — Append to journal

Append a one-screen entry to `docs/journals/<ticker>-<slug>.md`:

```markdown
## YYYY-MM-DD — Decided via decide-on-ticker

Thesis: <link to docs/theses/...>
Naive verdict: <direction, conviction>
Aware verdict: <direction, conviction, or "skipped">
Disagreement: <agree | disagree-* | n/a>
Action: <what was decided — hold, enter, exit, watch>
Next review: <date or trigger>
```

## Hard rules

- **NEVER share context between Step 2 and Step 3.** If you accidentally
  read news in the naive sub-task, restart the sub-task. The whole
  point is the isolation.
- **NEVER write a thesis without a backtest.** At minimum one
  `q_backtest_compound` call must justify the pattern you're claiming.
- **NEVER hide the disagreement.** If naive and aware diverge, the
  thesis must surface it; don't paper over it with a bland synthesis.
- **NEVER edit a closed thesis.** Closed theses are historical record.
  Open a new one and link to the closed one's slug.
- **Honest about thin data.** If a backtest has `sample_warning` set,
  include the warning verbatim in the thesis.

## Why this design

Most LLM market analysis is news-contaminated by default — Claude reads
the news first and then "interprets" the data through the news lens.
This skill enforces that the data gets a chance to speak for itself
first, in its own language. The disagreement between the two readings
is where the asymmetric edge lives. If you don't enforce isolation, you
just produce two slightly different paraphrases of the news.
