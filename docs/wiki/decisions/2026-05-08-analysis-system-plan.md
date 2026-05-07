---
name: V2 analysis system plan
description: Phased plan for extending v2 from a data pipeline into a quantitative + qualitative decision system, structured around Claude Scheduled Tasks and on-demand Skills.
type: decision
attributed_to: [niko, antigravity-agent]
belongs_to: [system-architecture]
source: chat
date: 2026-05-08
related: [2026-05-07-stateful-upgrade, 2026-05-07-v2-implementation-decisions]
---

# V2 analysis system — phased plan

## Context

v2 today is a data pipeline + 7 supply-chain MCP tools. Niko wants to extend it into a decision-making system with five capabilities: quantitative indicators, daily news ingestion, independent qualitative analysis (narrative-naive vs narrative-aware), ML time-series, and IB/whale view tracking. Goal: a "lean and bold" system that surfaces ≤5 high-conviction calls per week, supported by data + signals + reasoning.

## Constraints that shape the design

- **15 free Claude Scheduled Tasks/day.** Each task = one daily routine, can do as much LLM/tool work as it wants inside. Not "15 LLM calls."
- **Output target: project files (MD), not just a database.** Text artifacts go in `docs/digests/`, `docs/theses/`, `docs/journals/`. Synced via git; Drive optional.
- **Dual-agent (narrative-naive vs aware) lives as a Claude Skill, not a cron job.** Manual depth-on-demand in the Claude app with shared project memory. The cron version is a cheap "disagreement scan" that flags where automated quant and news signals diverge — the human reads that and decides whether to invoke the deep skill.
- **Free Neon (512 MB) and Hobby Vercel.** No new paid infra in this phase.
- **Honest about data depth.** ~90 trading days of T86. Backtests will be weak until ≥6 months accumulate.

## System shape (three layers)

| Layer | Job | Storage | Update |
|---|---|---|---|
| **MCP / Neon** | Raw data, materialized views, quant signals, news article index | Postgres tables + views | Harvester crons (no LLM) |
| **Daily digests** | Text snapshots written by 15 scheduled tasks | `docs/digests/YYYY-MM-DD/*.md` | Claude Scheduled Tasks |
| **Skills + project chats** | Manual deep analysis with shared project memory | `docs/theses/`, `docs/journals/`, `skills/*/SKILL.md` | On-demand in Claude app |

## Phasing (sequential, validate each)

### Phase 0 — OHLCV backfill (2–3 days)
Fill `raw_twse_ohlcv` for the same horizon as T86. Required for every technical/valuation indicator. Source already exists in `src/harvester/twse.py` (was just never run); needs to feed the existing OHLCV upsert path.

### Phase 1 — Quant MCP tools + backtest harness (1 week)
**New tools:** `q_indicators` (RSI/MACD/Bollinger/ATR per ticker), `q_screener` (multi-condition filter), `q_relative_strength` (vs sector / vs market), `q_anomalies` (z-score outliers in flow, volume, volatility), `q_backtest(signal, lookback_days)`.

**Backtest harness commitment:** every signal added in this phase or later must produce a hit-rate / drawdown report on existing data before it can appear in a scheduled-task digest. Data depth is thin (~90d), but the *discipline* is what matters — as months of T86 accumulate, the same harness produces stronger validation.

### Phase 2 — News pipeline (1 week)
Lightweight harvester (free RSS: Reuters Asia, FT free articles, central banks, DigiTimes for semis, MOPS announcements). Stores raw articles in `raw_news` (URL, title, source, published_at, raw_text, ticker_mentions[], pillar_mentions[], sentiment_score). Sentiment + entity extraction at write time via Haiku 4.5 (~$0.005/article).

**New MCP tools:** `n_recent`, `n_for_ticker`, `n_sentiment_summary`.

### Phase 3 — First 5 scheduled tasks (1 week)
1. **Pre-market quant digest** — calls `q_*` tools, writes `01-quant.md`
2. **News + sentiment digest** — calls `n_*` tools, writes `02-news.md`
3. **Sector rotation watch** — flow z-scores per pillar, `03-rotation.md`
4. **Anomaly scan** — flagged tickers, `04-anomalies.md`
5. **Disagreement scan** — reads tasks 1+2's output, asks Claude "where do quant and news disagree?", writes `06-disagreement.md`. **The cheap automated version of the dual-agent idea.**

`summary.md` aggregator written last by another scheduled task.

### Phase 4 — First two Skills (0.5 week)
- **`decide-on-ticker`** — full dual-agent skill. Two-pass reasoning: naive agent gets only structured data + supply-chain context (no news), aware agent gets data + news + sentiment. Reconciler step compares. Output to `docs/theses/YYYY-MM-DD-<ticker>-<thesis-name>.md`. Run manually in Claude app on a ticker the disagreement scan flagged.
- **`weekly-review`** — reads the past week's digests + theses, produces `docs/digests/weekly/YYYY-WNN.md` summary.

### Phase 5 — Remaining 10 scheduled task slots (ongoing)
Fill as gaps appear: macro/FX/rates monitor, geopolitics watch, earnings calendar, position health (if positions table populated), per-pillar deep digests, breaking-news triggers.

### Phase 6 — Optional: ML regime + IB tracking
ML re-scoped to *regime classification + anomaly detection*, NOT price prediction. TimesFM or HMM-based. IB/whale tracking last and only if signals from earlier phases are clearly underutilized — 13F is 45-day lagged and central bank speeches are already in news flow, so the marginal edge is small.

## Architectural commitments

- **Provenance everywhere.** Every signal row carries `(_source, _as_of, _inputs)`. Every digest carries the inputs list at the top.
- **Strict prompt isolation in `decide-on-ticker`.** Naive and aware agents run as separate API calls with no shared system prompt or input. The naive prompt explicitly forbids referencing news.
- **Hard cost ceiling per scheduled task.** Track Anthropic spend in a `llm_budget` table; tasks check before invoking.
- **Backtest before promote.** No new quant signal reaches a digest without a hit-rate report from `q_backtest`.
- **Two-tier LLM use.** Haiku 4.5 for extraction/classification at scale; Sonnet/Opus for synthesis at small N.
- **Lean output.** `decide-on-ticker` writes a thesis only when the signals support it. The disagreement scan surfaces ≤3 names per day on average.

## Build order decisions

- **Sequential**, validated each phase before the next.
- **Backtest harness in Phase 1** (not deferred). Adds ~2 days; pays back across all later phases.

## Cost estimate

- Phase 1: $0 (no LLM in quant tools).
- Phase 2: ~$5/day at ~1,000 articles/day with Haiku.
- Phase 3: Sonnet for digests, ~$0.05–0.20 per task × ~5 tasks/day = ~$0.5–1/day.
- Phase 4 skills: per-invocation Sonnet/Opus, only when run manually.
- Total at full build (phases 1-4): **~$200–250/month** if all 15 tasks run daily. Hard ceiling enforced via budget table.

## Open questions (deferred)

- Where to mirror text artifacts beyond git (Drive vs nothing).
- Whether to use Haiku for sentiment or a specialized model (FinBERT) — defer until Phase 2 implementation.
- ML model choice if Phase 6 happens — TimesFM vs Chronos vs simple HMM.

## Why this beats the original sketch

Original: cron a Claude analyst on every ticker every day → expensive noise.
This plan: cron aggregates structured data into text digests; deep reasoning happens manually with full context when something interesting surfaces. The dual-agent idea remains intact but lives where it earns its keep — at decision time, not on a schedule.
