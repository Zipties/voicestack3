"""Settings service with in-memory cache.

Reads the Settings singleton (id=1) from PostgreSQL and caches it for 60s.
All LLM/Qdrant configuration flows through here.
"""

import hashlib
import os
import time

from db.session import SessionLocal
from db.models import Settings

_cache: dict | None = None
_cache_ts: float = 0
_CACHE_TTL = 60  # seconds

# Default values for fresh installs / missing keys
DEFAULTS = {
    "llm_provider": "none",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "llm_analyze_prompt": "",
    "qdrant_enabled": False,
    "qdrant_url": "",
    "qdrant_api_key": "",
    "qdrant_collection": "vs3-transcripts-bge",
    "embed_url": "",
    "embed_api_key": "",
    "file_watcher_enabled": False,
    "file_watcher_path": "/data/watch",
    "file_watcher_extensions": ".m4a,.mp3,.wav,.ogg,.flac,.opus,.mp4,.webm",
    "file_watcher_min_size_kb": 10,
    "file_watcher_cooldown_seconds": 120,
    "file_watcher_poll_interval_seconds": 30,
    # Whisper model
    "whisper_model": "large-v3",
    "whisper_persistent": True,
    "whisper_prompt": "",
    # Pipeline stages (all enabled by default)
    "pipeline_alignment": True,
    "pipeline_diarization": True,
    "pipeline_emotion": True,
    "pipeline_speaker_matching": True,
    # Auto-summary: "off", "all", "known_speakers_only"
    "auto_summary": "off",
    # OpenClaw
    "openclaw_gateway_url": "",
    "openclaw_gateway_token": "",
    "openclaw_summary_agent": "",
    "openclaw_chat_agent": "",
}


def get_settings() -> dict:
    """Read settings from DB with 60s cache. Returns merged dict of model_config."""
    global _cache, _cache_ts

    if _cache is not None and (time.time() - _cache_ts) < _CACHE_TTL:
        return _cache

    db = SessionLocal()
    try:
        row = db.query(Settings).filter(Settings.id == 1).first()
        if not row:
            _cache = dict(DEFAULTS)
            _cache_ts = time.time()
            return _cache

        config = dict(DEFAULTS)
        if row.model_config:
            config.update(row.model_config)

        # Env var fallbacks for values that are empty in DB
        if not config.get("qdrant_url"):
            config["qdrant_url"] = os.getenv("QDRANT_URL", "")
        if not config.get("embed_url"):
            config["embed_url"] = os.getenv("EMBED_URL", "")
        if not config.get("embed_api_key"):
            config["embed_api_key"] = os.getenv("EMBED_API_KEY", "")

        _cache = config
        _cache_ts = time.time()
        return _cache
    finally:
        db.close()


def save_settings(data: dict) -> dict:
    """Save settings to DB and clear cache."""
    global _cache, _cache_ts

    db = SessionLocal()
    try:
        row = db.query(Settings).filter(Settings.id == 1).first()
        if not row:
            row = Settings(id=1, model_config={})
            db.add(row)

        # Merge with existing config (don't clobber keys not in the update)
        existing = dict(DEFAULTS)
        if row.model_config:
            existing.update(row.model_config)
        existing.update(data)

        row.model_config = existing
        db.commit()

        _cache = None
        _cache_ts = 0
        return get_settings()
    finally:
        db.close()


def clear_cache():
    """Force cache invalidation."""
    global _cache, _cache_ts
    _cache = None
    _cache_ts = 0


def mask_secret(value: str) -> str:
    """Mask a secret string for display: '***...last4'."""
    if not value or len(value) < 8:
        return "***" if value else ""
    return f"***...{value[-4:]}"


def is_masked(value: str) -> bool:
    """Check if a value is a masked placeholder (should not be saved)."""
    return value.startswith("***")


async def get_openai_token() -> str:
    """Return the configured OpenAI API key."""
    settings = get_settings()
    provider = settings.get("llm_provider", "none")

    if provider == "openai_key":
        return settings.get("openai_api_key", "")

    return ""
