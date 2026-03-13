import uuid
import httpx

from services.settings import get_settings, get_openai_token


async def chat_with_agent(
    agent_id: str,
    message: str,
    transcript_context: str = "",
    session_id: str | None = None,
) -> dict:
    """Send a message to the configured OpenAI-compatible LLM with transcript context.

    Each session_id represents a conversation. Only available when LLM provider is 'openai_key'.
    """
    settings = get_settings()
    provider = settings.get("llm_provider", "none")

    if provider != "openai_key":
        raise RuntimeError("Chat requires an OpenAI-compatible API key. Configure LLM provider in Settings.")

    if not session_id:
        session_id = str(uuid.uuid4())

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


async def list_agents() -> list[dict]:
    """Return available agents. No agent discovery needed for direct API integration."""
    return []
