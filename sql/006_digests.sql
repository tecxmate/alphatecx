-- alphatecx v2 — Daily/intraday digests (Phase 3 cron output)
--
-- Cron-generated digests live here, served via MCP `d_*` tools.
-- One row per (digest_date, kind) so a given day can have multiple
-- views: pre_market, intraday_alert, post_close, thesis_status.
--
-- Decision rationale: keep this in DB rather than committing MD back to
-- the repo. Cron stays simple (no git push step), MCP queries are
-- straightforward, the user reads in Claude app sessions via MCP.

CREATE TABLE IF NOT EXISTS daily_digest (
    digest_date     DATE NOT NULL,
    kind            TEXT NOT NULL,          -- 'pre_market', 'intraday_alert',
                                            -- 'post_close', 'thesis_status'
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,          -- markdown
    -- Inputs feed the provenance stamp on the MCP response.
    source_inputs   TEXT[],                 -- e.g. {'q_screener','n_recent'}
    -- Alert metadata: digest may contain N alert items, each describing
    -- a candidate ticker and trigger reason. Optional.
    alerts          JSONB,                  -- e.g. [{"ticker":"3443","reason":"rsi>85","value":87.8}, ...]
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    telegram_sent_at TIMESTAMPTZ,           -- nullable; null = not sent

    PRIMARY KEY (digest_date, kind)
);

-- "Show me today's digests" — most common query.
CREATE INDEX IF NOT EXISTS idx_digest_date
    ON daily_digest (digest_date DESC, kind);

-- "Catch up — what alert digests fired this week" — secondary access pattern.
CREATE INDEX IF NOT EXISTS idx_digest_kind_date
    ON daily_digest (kind, digest_date DESC);
