-- Trigram index for fast ILIKE segment search
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_segments_text_trgm ON segments USING gin (text gin_trgm_ops);
