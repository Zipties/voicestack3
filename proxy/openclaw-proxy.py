#!/usr/bin/env python3
"""HTTP proxy for OpenClaw gateway — pure Python, no CLI dependency.

Connects to the OpenClaw gateway over WSS and exposes simple REST endpoints
that the VoiceStack3 backend calls.

Config via environment variables:
  OPENCLAW_GATEWAY_URL   — WSS URL of the gateway (e.g. wss://your-gateway.example.com)
  OPENCLAW_GATEWAY_TOKEN — Authentication token for the gateway
  PROXY_PORT             — HTTP listen port (default: 8100)
"""

import json
import os
import time
import traceback
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    from websockets.sync.client import connect as ws_connect
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    from websockets.sync.client import connect as ws_connect

GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "")
GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8100"))
DEFAULT_TIMEOUT = 120


def _connect_and_auth():
    """Open WSS connection and authenticate. Returns open websocket (caller must close)."""
    if not GATEWAY_URL or not GATEWAY_TOKEN:
        raise RuntimeError("OPENCLAW_GATEWAY_URL and OPENCLAW_GATEWAY_TOKEN must be set")

    ws = ws_connect(GATEWAY_URL, ping_interval=None, close_timeout=5)
    try:
        msg = json.loads(ws.recv(timeout=10))
        if msg.get("event") != "connect.challenge":
            raise RuntimeError(f"Expected connect.challenge, got: {msg}")

        ws.send(json.dumps({
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "gateway-client",
                    "version": "1.0.0",
                    "platform": "linux",
                    "mode": "backend"
                },
                "auth": {"token": GATEWAY_TOKEN},
                "role": "operator",
                "scopes": ["operator.read", "operator.write", "operator.admin"]
            }
        }))

        resp = json.loads(ws.recv(timeout=15))
        if not resp.get("ok"):
            error = resp.get("error", {})
            raise RuntimeError(f"Gateway auth failed: {error.get('message', error)}")

        return ws
    except Exception:
        ws.close()
        raise


def _send_and_wait(ws, method: str, params: dict, timeout: float = 30):
    """Send a request and wait for the response. Returns payload."""
    req_id = str(uuid.uuid4())
    ws.send(json.dumps({
        "type": "req",
        "id": req_id,
        "method": method,
        "params": params
    }))

    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            raw = ws.recv(timeout=min(remaining, 5))
            msg = json.loads(raw)
            if msg.get("type") == "res" and msg.get("id") == req_id:
                if not msg.get("ok"):
                    error = msg.get("error", {})
                    raise RuntimeError(error.get("message", str(error)))
                return msg.get("payload", {})
        except TimeoutError:
            continue

    raise TimeoutError(f"Gateway request '{method}' timed out after {timeout}s")


def list_agents() -> list[dict]:
    """Fetch agents from the gateway."""
    ws = _connect_and_auth()
    try:
        payload = _send_and_wait(ws, "agents.list", {})
    finally:
        ws.close()

    agents = []
    for a in payload.get("agents", []):
        identity = a.get("identity", {})
        agents.append({
            "id": a["id"],
            "name": identity.get("name") or a.get("name", a["id"].replace("-", " ").title()),
            "description": f"OpenClaw agent: {a['id']}",
            "model": "unknown",
        })
    return agents


def send_to_agent(agent_id: str, message: str, timeout: int, session_id: str = None) -> dict:
    """Send a message to an agent via chat.send and wait for the streaming response."""
    session_key = session_id or f"agent:{agent_id}:api:{uuid.uuid4()}"

    ws = _connect_and_auth()
    try:
        payload = _send_and_wait(ws, "chat.send", {
            "message": message,
            "sessionKey": session_key,
            "idempotencyKey": str(uuid.uuid4()),
        }, timeout=timeout)

        run_id = payload.get("runId")
        if not run_id:
            return {"text": str(payload), "meta": {}}

        text_parts = []
        final_session_key = session_key
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining = deadline - time.time()
            try:
                raw = ws.recv(timeout=min(remaining, 5))
                msg = json.loads(raw)
                if msg.get("type") == "event" and msg.get("event") == "chat":
                    p = msg.get("payload", {})
                    if p.get("sessionKey") == session_key:
                        # Text is in message.content[].text
                        content = p.get("message", {}).get("content", [])
                        for block in content:
                            if block.get("type") == "text" and block.get("text"):
                                text_parts.append(block["text"])
                        if "sessionKey" in p:
                            final_session_key = p["sessionKey"]
                        if p.get("state") in ("final", "error", "aborted"):
                            break
            except TimeoutError:
                continue

        return {
            "text": text_parts[-1] if text_parts else "",
            "meta": {"runId": run_id, "sessionId": final_session_key}
        }
    finally:
        ws.close()


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
        self.wfile.write(json.dumps(data).encode())

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
    server.serve_forever()
