-- Add avatar support to speakers
ALTER TABLE speakers ADD COLUMN IF NOT EXISTS avatar_id INTEGER;
ALTER TABLE speakers ADD COLUMN IF NOT EXISTS custom_avatar VARCHAR(500);

-- Assign unique avatars to existing speakers (0-indexed, no duplicates up to 100)
WITH numbered AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) - 1 AS rn
    FROM speakers
    WHERE avatar_id IS NULL
)
UPDATE speakers SET avatar_id = numbered.rn % 100
FROM numbered
WHERE speakers.id = numbered.id;
