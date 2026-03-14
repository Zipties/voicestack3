"""Settings API endpoints."""

import os
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.settings import (
    get_settings,
    save_settings,
    mask_secret,
    is_masked,
    get_openai_token,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Keys that contain secrets and should be masked in GET responses
SECRET_KEYS = {
    "openai_api_key",
    "openai_oauth_token",
    "openai_oauth_refresh",
    "qdrant_api_key",
    "embed_api_key",
    "openclaw_gateway_token",
}


@router.get("")
async def get_app_settings():
    """Return current settings with secrets masked."""
    settings = dict(get_settings())
    for key in SECRET_KEYS:
        if key in settings and settings[key]:
            settings[key] = mask_secret(settings[key])
    # Include default analyze prompt so frontend can show it as baseline
    from services.llm import DEFAULT_ANALYZE_PROMPT
    settings["default_analyze_prompt"] = DEFAULT_ANALYZE_PROMPT
    return settings


class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    llm_analyze_prompt: str | None = None
    qdrant_enabled: bool | None = None
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str | None = None
    embed_url: str | None = None
    embed_api_key: str | None = None
    file_watcher_enabled: bool | None = None
    file_watcher_path: str | None = None
    file_watcher_extensions: str | None = None
    file_watcher_min_size_kb: int | None = None
    file_watcher_cooldown_seconds: int | None = None
    file_watcher_poll_interval_seconds: int | None = None
    # Whisper model
    whisper_model: str | None = None
    whisper_persistent: bool | None = None
    whisper_prompt: str | None = None
    # Pipeline stages
    pipeline_alignment: bool | None = None
    pipeline_diarization: bool | None = None
    pipeline_emotion: bool | None = None
    pipeline_speaker_matching: bool | None = None
    # Auto-summary
    auto_summary: str | None = None
    # OpenClaw
    openclaw_gateway_url: str | None = None
    openclaw_gateway_token: str | None = None
    openclaw_summary_agent: str | None = None
    openclaw_chat_agent: str | None = None


@router.put("")
async def update_app_settings(update: SettingsUpdate):
    """Update settings. Masked secret values are ignored (preserves existing)."""
    data = {}
    current = get_settings()

    for key, value in update.model_dump(exclude_none=True).items():
        # Don't overwrite secrets with masked placeholders
        if isinstance(value, str) and is_masked(value):
            continue
        data[key] = value

    if not data:
        return dict(current)

    result = save_settings(data)
    # Mask secrets in response
    for key in SECRET_KEYS:
        if key in result and result[key]:
            result[key] = mask_secret(result[key])
    return result


@router.post("/test-llm")
async def test_llm_connection():
    """Test the LLM connection with a tiny prompt."""
    settings = get_settings()
    provider = settings.get("llm_provider", "none")

    if provider == "none":
        return {"status": "error", "message": "LLM provider is disabled"}

    if provider == "openclaw":
        proxy_url = os.getenv("OPENCLAW_PROXY_URL", "http://openclaw-proxy:8100")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{proxy_url}/agents")
            if resp.status_code == 200:
                agents = resp.json()
                return {"status": "ok", "message": f"OpenClaw proxy connected ({len(agents)} agents)"}
            return {"status": "error", "message": f"Proxy returned {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": f"Cannot reach OpenClaw proxy: {e}"}

    if provider == "openai_key":
        try:
            token = await get_openai_token()
            if not token:
                return {"status": "error", "message": "No API token configured"}

            base_url = settings.get("openai_base_url", "https://api.openai.com/v1")
            model = settings.get("openai_model", "gpt-4o-mini")

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "Say 'ok' and nothing else."}],
                        "max_completion_tokens": 5,
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )

            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                return {"status": "ok", "message": f"Connected. Model responded: {text}"}
            return {"status": "error", "message": f"API returned {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": f"Unknown provider: {provider}"}


@router.get("/models")
async def list_models():
    """Fetch available models from the configured LLM provider."""
    settings = get_settings()
    provider = settings.get("llm_provider", "none")

    if provider == "none":
        return {"models": []}

    if provider == "openclaw":
        return {"models": []}  # OpenClaw manages its own models

    # For openai_key, query the /models endpoint
    if provider != "openai_key":
        return {"models": []}

    try:
        token = await get_openai_token()
        if not token:
            return {"models": []}

        base_url = settings.get("openai_base_url", "https://api.openai.com/v1")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code != 200:
            return {"models": []}

        data = resp.json().get("data", [])
        # Filter to chat-capable models, sort by id
        models = sorted(
            [{"id": m["id"], "owned_by": m.get("owned_by", "")} for m in data],
            key=lambda m: m["id"],
        )
        return {"models": models}
    except Exception:
        return {"models": []}


@router.post("/test-qdrant")
async def test_qdrant_connection():
    """Test the Qdrant connection by checking collection info."""
    settings = get_settings()

    if not settings.get("qdrant_enabled"):
        return {"status": "error", "message": "Qdrant is disabled"}

    qdrant_url = settings.get("qdrant_url", "")
    if not qdrant_url:
        return {"status": "error", "message": "Qdrant URL not configured"}

    collection = settings.get("qdrant_collection", "vs3-transcripts-bge")
    qdrant_headers = {}
    qdrant_key = settings.get("qdrant_api_key", "")
    if qdrant_key and not qdrant_key.startswith("***"):
        qdrant_headers["api-key"] = qdrant_key

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{qdrant_url}/collections/{collection}", headers=qdrant_headers)
        if resp.status_code == 200:
            result = resp.json().get("result", {})
            points = result.get("points_count", 0)
            return {"status": "ok", "message": f"Collection '{collection}': {points} points"}
        elif resp.status_code == 404:
            return {"status": "ok", "message": f"Connected. Collection '{collection}' will be created on first ingest."}
        return {"status": "error", "message": f"Qdrant returned {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": f"Cannot reach Qdrant: {e}"}


@router.get("/watcher/status")
async def watcher_status():
    """Return file watcher status."""
    from services.file_watcher import get_watcher_status
    return get_watcher_status()


@router.post("/watcher/scan")
async def watcher_scan():
    """Force an immediate file watcher scan."""
    from services.file_watcher import force_scan
    ingested = force_scan()
    return {"scanned": True, "ingested": ingested, "count": len(ingested)}
