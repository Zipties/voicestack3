-- VoiceStack3 Initial Schema
-- PostgreSQL 16 + pgvector

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Jobs table (pipeline orchestration)
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
    progress INTEGER NOT NULL DEFAULT 0,
    pipeline_stage VARCHAR(50),
    params JSONB NOT NULL DEFAULT '{}',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Assets table (uploaded audio files)
CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    mimetype VARCHAR(100),
    size_bytes BIGINT,
    duration_seconds FLOAT,
    sample_rate INTEGER,
    channels INTEGER,
    input_path VARCHAR(500),
    archival_path VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Speakers table (voice identity profiles)
-- Users rename these from "Speaker 1" to real names like "Alice"
-- Future recordings auto-match via embedding similarity
CREATE TABLE speakers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    is_trusted BOOLEAN NOT NULL DEFAULT FALSE,
    match_confidence FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Transcripts table
CREATE TABLE transcripts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL DEFAULT '',
    title VARCHAR(500),
    summary TEXT,
    language VARCHAR(10),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Segments table (transcript chunks with speaker + emotion)
CREATE TABLE segments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transcript_id UUID NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    start_time FLOAT NOT NULL,
    end_time FLOAT NOT NULL,
    text TEXT NOT NULL,
    word_timings JSONB,
    speaker_id UUID REFERENCES speakers(id) ON DELETE SET NULL,
    original_speaker_label VARCHAR(50),
    -- Emotion detection (emotion2vec+ 9-class)
    emotion VARCHAR(50),
    emotion_confidence FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Speaker voice embeddings (ECAPA-TDNN 768-dim)
-- Proper pgvector column for native cosine similarity search
CREATE TABLE embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    speaker_id UUID NOT NULL REFERENCES speakers(id) ON DELETE CASCADE,
    segment_id UUID REFERENCES segments(id) ON DELETE SET NULL,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    embedding vector(192) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tags table (LLM-generated metadata)
CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transcript_id UUID NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    tag VARCHAR(100) NOT NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'llm',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Settings table (singleton config)
CREATE TABLE settings (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    model_config JSONB NOT NULL DEFAULT '{
        "whisper_model": "large-v2",
        "whisper_compute_type": "float16",
        "whisper_batch_size": 16,
        "speaker_match_threshold": 0.3
    }',
    api_token VARCHAR(255) DEFAULT 'changeme',
    hf_token VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for query performance
CREATE INDEX idx_assets_job ON assets(job_id);
CREATE INDEX idx_transcripts_job ON transcripts(job_id);
CREATE INDEX idx_segments_transcript ON segments(transcript_id);
CREATE INDEX idx_segments_speaker ON segments(speaker_id);
CREATE INDEX idx_segments_time ON segments(start_time, end_time);
CREATE INDEX idx_embeddings_speaker ON embeddings(speaker_id);
CREATE INDEX idx_embeddings_segment ON embeddings(segment_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created ON jobs(created_at DESC);

-- Insert default settings row
INSERT INTO settings (id) VALUES (1);
