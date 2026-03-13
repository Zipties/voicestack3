#!/usr/bin/env python3
"""Tiny HTTP proxy that forwards requests to the OpenClaw CLI.

Runs on the host (not in a container) so it can call `openclaw agent`.
The backend container POSTs to this proxy to get agent responses.

Usage: python3 openclaw-proxy.py
Listens on: http://0.0.0.0:8100
"""

import asyncio
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

OPENCLAW_BIN = os.getenv("OPENCLAW_BIN", "openclaw")
OPENCLAW_CONFIG = os.getenv("OPENCLAW_CONFIG", os.path.expanduser("~/.openclaw/openclaw.json"))
DEFAULT_TIMEOUT = 120


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/agents":
            self.send_error(404)
            return

        try:
            result = asyncio.run(self._list_agents())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

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
            result = asyncio.run(self._run_agent(agent_id, message, timeout, session_id))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    async def _list_agents(self) -> list[dict]:
        """Read agents from openclaw config and return list for chat."""
        with open(OPENCLAW_CONFIG) as f:
            cfg = json.load(f)

        agents = []
        for a in cfg.get("agents", {}).get("list", []):
            aid = a["id"]
            agents.append({
                "id": aid,
                "name": a.get("name", aid.replace("-", " ").title()),
                "description": a.get("description", f"OpenClaw agent: {aid}"),
                "model": a.get("model", "unknown"),
            })
        return agents

    async def _run_agent(self, agent_id: str, message: str, timeout: int, session_id: str = None) -> dict:
        cmd = [
            OPENCLAW_BIN, "agent",
            "--agent", agent_id,
            "--message", message,
            "--json",
            "--timeout", str(timeout),
        ]
        if session_id:
            cmd.extend(["--session-id", session_id])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"openclaw exit {proc.returncode}: {stderr.decode()[:500]}")

        response = json.loads(stdout.decode())
        payload_text = response["result"]["payloads"][0]["text"]
        return {"text": payload_text, "meta": response.get("result", {}).get("meta", {})}

    def log_message(self, format, *args):
        print(f"[openclaw-proxy] {args[0]}")


if __name__ == "__main__":
    port = int(os.getenv("PROXY_PORT", "8100"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"[openclaw-proxy] Listening on :{port}")
    server.serve_forever()
