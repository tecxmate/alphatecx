-- alphatecx v2 — News ingestion (Phase 2a)
-- raw_news stores articles harvested from RSS feeds. Sentiment + entity
-- extraction columns are present but null until Phase 2b lands the LLM
-- classifier. Schema kept stable from day 1 so the classifier can fill
-- columns in place without a migration.

CREATE TABLE IF NOT EXISTS raw_news (
    -- Canonicalised URL is the natural primary key — same article from
    -- two RSS feeds (e.g. DigiTimes + Google News) collapses to one row.
    url             TEXT PRIMARY KEY,

    -- Provenance: which feed first surfaced this article. If the same URL
    -- appears in a second feed later, we don't update source — first wins.
    source          TEXT NOT NULL,         -- short key, e.g. 'digitimes'
    feed_name       TEXT NOT NULL,         -- human-readable, e.g. 'DIGITIMES Asia'
    lang            TEXT NOT NULL,         -- 'en' or 'zh-Hant'

    title           TEXT NOT NULL,
    -- sha256(normalised title) — for cross-source dedup when URLs differ
    -- but the headline is identical (Google News re-points to source).
    title_hash      TEXT NOT NULL,

    raw_summary     TEXT,                  -- description from <description> field

    -- Times: published_at is what the feed claims; fetched_at is when we
    -- ingested. Both timestamps live in UTC.
    published_at    TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Phase 2b: filled by classifier. Until then these are null.
    ticker_mentions TEXT[],                -- e.g. {'2330','2317'}
    pillar_mentions TEXT[],                -- e.g. {'semiconductor','infrastructure'}
    sentiment_score DOUBLE PRECISION,      -- [-1, 1]; null = unclassified
    classified_at   TIMESTAMPTZ
);

-- "Show me recent news" — most common access pattern.
CREATE INDEX IF NOT EXISTS idx_news_published
    ON raw_news (published_at DESC NULLS LAST);

-- "Show me recent news from source X" — debugging + per-feed tuning.
CREATE INDEX IF NOT EXISTS idx_news_source_pub
    ON raw_news (source, published_at DESC NULLS LAST);

-- Cross-source title-dedup lookup.
CREATE INDEX IF NOT EXISTS idx_news_title_hash
    ON raw_news (title_hash);

-- Per-ticker query: "give me articles mentioning 2330" — uses GIN on the array.
CREATE INDEX IF NOT EXISTS idx_news_tickers
    ON raw_news USING GIN (ticker_mentions);

-- Bookkeeping: latest fetched_at per source. Quick "freshness per source"
-- check from sc_data_status without a full table scan.
-- (No matview needed yet; the source+pub index covers it.)
