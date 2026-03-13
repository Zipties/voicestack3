-- Add speech events column for SenseVoice paralinguistic detection
-- Stores array of non-speech events like LAUGHTER, SIGH, APPLAUSE, etc.
ALTER TABLE segments ADD COLUMN IF NOT EXISTS speech_events JSONB;

-- Also add segment_index if missing (used for ordering)
ALTER TABLE segments ADD COLUMN IF NOT EXISTS segment_index INT;
