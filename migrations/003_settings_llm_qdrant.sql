-- Add LLM and Qdrant configuration fields
UPDATE settings SET model_config = model_config || '{
    "llm_provider": "none",
    "openai_oauth_token": "",
    "openai_oauth_refresh": "",
    "openai_oauth_expires_at": null,
    "openai_oauth_email": "",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "qdrant_enabled": false,
    "qdrant_url": "",
    "embed_url": "",
    "embed_api_key": ""
}'::jsonb WHERE id = 1;

-- Also update the default for fresh installs (001 creates with defaults)
-- Fresh installs should have LLM disabled and qdrant disabled
ALTER TABLE settings ALTER COLUMN model_config SET DEFAULT '{
    "whisper_model": "large-v2",
    "whisper_compute_type": "float16",
    "whisper_batch_size": 16,
    "speaker_match_threshold": 0.3,
    "llm_provider": "none",
    "openai_oauth_token": "",
    "openai_oauth_refresh": "",
    "openai_oauth_expires_at": null,
    "openai_oauth_email": "",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "qdrant_enabled": false,
    "qdrant_url": "",
    "embed_url": "",
    "embed_api_key": ""
}'::jsonb;
