#!/usr/bin/env python3
"""HTTP proxy for OpenClaw gateway — pure Python, no external dependencies.

Connects to the OpenClaw gateway via its OpenAI-compatible HTTP API
(/v1/chat/completions) and exposes simple REST endpoints that the
VoiceStack3 backend calls.

Config via environment variables:
  OPENCLAW_GATEWAY_URL   — Base HTTPS URL of the gateway (e.g. https://chad.mcd.so)
  OPENCLAW_GATEWAY_TOKEN — Authentication token for the gateway
  PROXY_PORT             — HTTP listen port (default: 8100)
  SUMMARY_AGENT          — Agent ID for summaries (default: vs3-summarizer)
  CHAT_AGENT             — Agent ID for chat (default: vs3-chat)
"""

import json
import os
import ssl
import traceback
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "").rstrip("/")
GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8100"))
SUMMARY_AGENT = os.getenv("SUMMARY_AGENT", "vs3-summarizer")
CHAT_AGENT = os.getenv("CHAT_AGENT", "vs3-chat")
DEFAULT_TIMEOUT = 120

# Allow self-signed certs for LAN gateway access
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _gateway_api_url() -> str:
    """Resolve the HTTP API base URL from the configured gateway URL."""
    url = GATEWAY_URL
    if not url:
        raise RuntimeError("OPENCLAW_GATEWAY_URL not set")
    # Convert wss:// to https:// if user still has the WSS URL configured
    if url.startswith("wss://"):
        url = "https://" + url[6:]
    elif url.startswith("ws://"):
        url = "http://" + url[5:]
    return url


def _chat_completions(model: str, messages: list[dict], timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Call the OpenAI-compatible chat completions endpoint."""
    api_url = f"{_gateway_api_url()}/v1/chat/completions"
    model_id = model if model.startswith("openclaw/") or model == "openclaw" else f"openclaw/{model}"
    body = json.dumps({
        "model": model_id,
        "messages": messages,
    }).encode()

    req = Request(api_url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {GATEWAY_TOKEN}")
    req.add_header("x-openclaw-scopes", "operator.read,operator.write")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=timeout, context=_ssl_ctx) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gateway HTTP {e.code}: {error_body}") from e
    except URLError as e:
        raise RuntimeError(f"Gateway connection error: {e.reason}") from e


def list_agents() -> list[dict]:
    """Return configured agents (no gateway call needed)."""
    agents = []
    for agent_id, description in [
        (SUMMARY_AGENT, "Summarize and tag transcriptions"),
        (CHAT_AGENT, "Chat about transcriptions"),
    ]:
        agents.append({
            "id": agent_id,
            "name": agent_id.replace("-", " ").title(),
            "description": description,
            "model": "unknown",
        })
    return agents


def send_to_agent(agent_id: str, message: str, timeout: int, session_id: str = None) -> dict:
    """Send a message to an agent via the chat completions API."""
    messages = [{"role": "user", "content": message}]

    result = _chat_completions(model=agent_id, messages=messages, timeout=timeout)

    # Extract the response text from the OpenAI-compatible response
    choices = result.get("choices", [])
    text = ""
    if choices:
        text = choices[0].get("message", {}).get("content", "")

    return {
        "text": text,
        "meta": {
            "model": result.get("model", agent_id),
            "id": result.get("id", ""),
        },
    }


def test_connection() -> dict:
    """Quick connectivity test — send a minimal request to the gateway."""
    try:
        result = _chat_completions(
            model=SUMMARY_AGENT,
            messages=[{"role": "user", "content": "ping"}],
            timeout=15,
        )
        return {
            "status": "ok",
            "gateway": GATEWAY_URL,
            "model": result.get("model", "unknown"),
        }
    except Exception as e:
        return {
            "status": "error",
            "gateway": GATEWAY_URL,
            "error": str(e),
        }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/agents":
            try:
                agents = list_agents()
                self._json_response(200, agents)
            except Exception as e:
                traceback.print_exc()
                self._json_response(503, {"error": str(e)})
        elif self.path == "/health":
            self._json_response(200, {"status": "ok", "gateway": GATEWAY_URL or "not configured"})
        elif self.path == "/test":
            result = test_connection()
            status = 200 if result.get("status") == "ok" else 503
            self._json_response(status, result)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/agent":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}

        agent_id = body.get("agent", "")
        message = body.get("message", "")
        timeout = body.get("timeout", DEFAULT_TIMEOUT)
        session_id = body.get("session_id")

        if not message:
            self.send_error(400, "Missing 'message' field")
            return
        if not agent_id:
            self.send_error(400, "Missing 'agent' field")
            return

        try:
            result = send_to_agent(agent_id, message, timeout, session_id)
            self._json_response(200, result)
        except Exception as e:
            traceback.print_exc()
            self._json_response(503, {"error": str(e)})

    def _json_response(self, status: int, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(json.dumps(data).encode())
        except BrokenPipeError:
            pass

    def log_message(self, format, *args):
        print(f"[openclaw-proxy] {args[0]}")


if __name__ == "__main__":
    if not GATEWAY_URL:
        print("[openclaw-proxy] WARNING: OPENCLAW_GATEWAY_URL not set.")
    if not GATEWAY_TOKEN:
        print("[openclaw-proxy] WARNING: OPENCLAW_GATEWAY_TOKEN not set.")

    server = HTTPServer(("0.0.0.0", PROXY_PORT), Handler)
    print(f"[openclaw-proxy] Listening on :{PROXY_PORT}")
    if GATEWAY_URL:
        print(f"[openclaw-proxy] Gateway: {GATEWAY_URL}")
    print(f"[openclaw-proxy] Agents: {SUMMARY_AGENT}, {CHAT_AGENT}")
    print(f"[openclaw-proxy] Mode: HTTP API (v1/chat/completions)")
    server.serve_forever()
