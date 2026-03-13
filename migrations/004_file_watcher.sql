-- File watcher: track processed files to avoid re-ingestion
CREATE TABLE IF NOT EXISTS watched_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_path TEXT UNIQUE NOT NULL,
    file_size BIGINT,
    file_mtime TIMESTAMPTZ,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add file watcher settings to existing settings row
UPDATE settings SET model_config = model_config || '{
    "file_watcher_enabled": false,
    "file_watcher_path": "",
    "file_watcher_extensions": ".m4a,.mp3,.wav,.ogg,.flac,.opus,.mp4,.webm",
    "file_watcher_min_size_kb": 10,
    "file_watcher_cooldown_seconds": 120,
    "file_watcher_poll_interval_seconds": 30
}'::jsonb WHERE id = 1;
