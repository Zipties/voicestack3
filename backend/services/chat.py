import json
import os
import uuid
import httpx

from services.settings import get_settings, get_openai_token

OPENCLAW_PROXY_URL = os.getenv("OPENCLAW_PROXY_URL", "http://localhost:8100")


async def chat_with_agent(
    agent_id: str,
    message: str,
    transcript_context: str = "",
    session_id: str | None = None,
) -> dict:
    """Send a message to configured LLM. Supports OpenClaw proxy or direct OpenAI-compatible API."""
    settings = get_settings()
    provider = settings.get("llm_provider", "none")

    if provider == "none":
        raise RuntimeError("LLM provider is disabled. Configure it in Settings.")

    if not session_id:
        session_id = str(uuid.uuid4())

    if provider == "openclaw":
        proxy_url = settings.get("openclaw_proxy_url", OPENCLAW_PROXY_URL)
        chat_agent = agent_id or settings.get("openclaw_chat_agent", "")
        if not chat_agent:
            raise RuntimeError("No OpenClaw chat agent configured. Set it in Settings.")

        full_message = message
        if transcript_context:
            full_message = f"Context:\n{transcript_context}\n\nQuestion: {message}"

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{proxy_url}/agent",
                json={
                    "agent": chat_agent,
                    "message": full_message,
                    "timeout": 120,
                    "session_id": session_id,
                },
            )

        if resp.status_code != 200:
            error = resp.json().get("error", resp.text[:500])
            raise RuntimeError(f"OpenClaw chat error ({resp.status_code}): {error}")

        data = resp.json()
        return {
            "response": data["text"],
            "session_id": session_id,
            "agent": chat_agent,
        }

    elif provider == "openai_key":
        token = await get_openai_token()
        if not token:
            raise RuntimeError("No API token configured")

        base_url = settings.get("openai_base_url", "https://api.openai.com/v1")
        model = settings.get("openai_model", "gpt-4o-mini")

        system_prompt = "You are a helpful assistant that answers questions about audio transcripts."
        if transcript_context:
            system_prompt += f"\n\nTranscript:\n{transcript_context}"

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        if resp.status_code != 200:
            raise RuntimeError(f"LLM API error ({resp.status_code}): {resp.text[:500]}")

        response_text = resp.json()["choices"][0]["message"]["content"]
        return {
            "response": response_text,
            "session_id": session_id,
            "agent": agent_id,
        }

    else:
        raise RuntimeError(f"Unknown LLM provider: {provider}")


async def list_agents() -> list[dict]:
    """Fetch available agents. Returns agents from OpenClaw proxy if configured."""
    settings = get_settings()
    if settings.get("llm_provider") != "openclaw":
        return []

    proxy_url = settings.get("openclaw_proxy_url", OPENCLAW_PROXY_URL)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{proxy_url}/agents")
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[chat] Failed to fetch agents from proxy: {e}")

    return []
