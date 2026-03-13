import json
import httpx

from services.settings import get_settings, get_openai_token

_SYSTEM_PROMPT = """\
You are a transcript analysis assistant. You analyze audio transcripts and return structured JSON metadata. You must identify the correct content type and match your analysis style to the actual content — never force a transcript into an ill-fitting category. If there are no action items, return an empty array. If the content is entertainment or comedy, analyze it as such."""

DEFAULT_ANALYZE_PROMPT = """\
Analyze this transcript and return a JSON object with these fields:

1. **title**: A structured title that matches the content type. Use one of these schemas:
   - "Voice Note: <YYYY-MM-DD> - <topic>" — quick notes, reminders, short recordings
   - "Journal Entry: <YYYY-MM-DD> - <title>" — personal reflections, daily logs, voice memos
   - "Conversation: <YYYY-MM-DD> - <topic>" — casual multi-speaker discussions
   - "Meeting: <YYYY-MM-DD> - <topic>" — professional meetings, standups, planning
   - "Interview: <YYYY-MM-DD> - <subject>" — interviews, Q&A sessions
   - "Phone Call: <YYYY-MM-DD> - <with whom or topic>" — phone conversations
   - "Lecture: <YYYY-MM-DD> - <topic>" — educational content, presentations
   - "Podcast: <YYYY-MM-DD> - <show/topic>" — podcast episodes, radio shows
   - "Comedy: <YYYY-MM-DD> - <performer/bit>" — stand-up, sketches, comedy shows
   - "Music: <YYYY-MM-DD> - <artist/song>" — music recordings, jam sessions
   Pick the schema that ACTUALLY fits. Do NOT force content into a wrong category.
   If nothing fits well, use "Recording: <YYYY-MM-DD> - <topic>".
   Always include the recording date in YYYY-MM-DD format.

2. **summary**: 2-4 sentence overview. Match the tone to the content — a comedy clip
   should be described as comedy, not as a "discussion" or "meeting".

3. **tags**: Array of 3-8 lowercase keyword tags for searchability. Include:
   - Content type (e.g., "comedy", "meeting", "journal", "podcast")
   - Topic tags (e.g., "relationships", "work", "health", "self-improvement")
   - People mentioned by name
   - Emotional tags if prominent (e.g., "funny", "emotional", "frustrated")

4. **action_items**: Array of strings for any tasks or follow-ups explicitly mentioned.
   Return an EMPTY array if the content has no real action items (most recordings won't).

5. **outline**: Array of objects with "heading" and "content" keys summarizing the structure.
   For short recordings (< 5 segments), a single-item outline is fine.

Return ONLY valid JSON, no markdown fencing."""


def _get_analyze_prompt() -> str:
    """Return the analysis prompt — user-customized or default."""
    settings = get_settings()
    custom = settings.get("llm_analyze_prompt", "")
    return custom if custom.strip() else DEFAULT_ANALYZE_PROMPT


async def _call_openai_compatible(message: str, base_url: str, token: str, model: str) -> str:
    """Call an OpenAI-compatible chat completions endpoint."""
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI API error ({resp.status_code}): {resp.text[:500]}")

    return resp.json()["choices"][0]["message"]["content"]


def _parse_llm_response(payload_text: str) -> dict:
    """Parse LLM response text into structured overview dict."""
    try:
        text = payload_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {
            "title": "Voice Note: Untitled",
            "summary": payload_text[:500],
            "tags": [],
            "action_items": [],
            "outline": [],
        }

    # Normalize outline format
    outline = result.get("outline", [])
    if outline and isinstance(outline[0], str):
        outline = [{"heading": item, "content": ""} for item in outline]

    # Normalize tags to lowercase
    tags = [t.lower().strip() for t in result.get("tags", []) if t.strip()]

    return {
        "title": result.get("title", "Voice Note: Untitled"),
        "summary": result.get("summary", ""),
        "tags": tags,
        "action_items": result.get("action_items", []),
        "outline": outline,
    }


async def generate_overview(raw_text: str, recorded_at: str | None = None) -> dict:
    """Generate title, summary, tags, action items, and outline via configured LLM.

    Supports providers: openai_key, none.
    Returns dict with keys: title, summary, tags, action_items, outline.
    """
    settings = get_settings()
    provider = settings.get("llm_provider", "none")

    if provider == "none":
        return {
            "title": "Voice Note: Untitled",
            "summary": "",
            "tags": [],
            "action_items": [],
            "outline": [],
        }

    # Build the prompt
    analyze_prompt = _get_analyze_prompt()
    truncated = raw_text[:48000]
    date_line = f"\nRecording date: {recorded_at}\n" if recorded_at else "\n"
    message = f"{analyze_prompt}{date_line}\nTranscript:\n{truncated}"

    if provider == "openai_key":
        token = await get_openai_token()
        if not token:
            raise RuntimeError("No API token configured")
        base_url = settings.get("openai_base_url", "https://api.openai.com/v1")
        model = settings.get("openai_model", "gpt-4o-mini")
        payload_text = await _call_openai_compatible(message, base_url, token, model)
    else:
        raise RuntimeError(f"Unknown LLM provider: {provider}")

    return _parse_llm_response(payload_text)
