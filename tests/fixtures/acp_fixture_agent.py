#!/usr/bin/env python3
"""Minimal ACP agent over stdio NDJSON JSON-RPC (fixture / contract tests).

Speaks the same lifecycle SkillOpt Sleep needs:
  initialize → session/new → session/prompt (+ session/update chunks)

Not a product agent — only for non-mock StdioAcpTransport contract tests.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, Dict, Optional


def _write(msg: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _reply(req_id: Any, result: Dict[str, Any]) -> None:
    _write({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def main() -> int:
    sessions: Dict[str, Dict[str, Any]] = {}
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stderr.write(f"fixture-agent: bad json: {line[:120]!r}\n")
            sys.stderr.flush()
            continue
        if not isinstance(msg, dict):
            continue
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}
        # Notifications from client (no id): ignore.
        if method and req_id is None:
            continue
        if method is None:
            continue

        if method == "initialize":
            _reply(
                req_id,
                {
                    "protocolVersion": int(params.get("protocolVersion", 1)),
                    "agentCapabilities": {"session": {}},
                    "agentInfo": {"name": "skillopt-acp-fixture-agent", "version": "0.0.1"},
                    "authMethods": [],
                },
            )
        elif method == "session/new":
            if "cwd" not in params or "mcpServers" not in params:
                _error(req_id, -32602, "session/new requires cwd and mcpServers")
                continue
            sid = f"sess_{uuid.uuid4().hex[:12]}"
            sessions[sid] = {"cwd": params["cwd"]}
            _reply(req_id, {"sessionId": sid})
        elif method == "session/prompt":
            sid = params.get("sessionId")
            prompt = params.get("prompt")
            if not sid or prompt is None:
                _error(req_id, -32602, "session/prompt requires sessionId and prompt")
                continue
            if sid not in sessions:
                _error(req_id, -32602, f"unknown sessionId: {sid}")
                continue
            text_bits = []
            for block in prompt:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_bits.append(str(block.get("text", "")))
            joined = "\n".join(text_bits)
            # SKILLOPT_ACP_FIXTURE_SPLIT=1: two chunks that concatenate to the
            # same "[fixture-acp] …" body plus the token "pong".
            if os.environ.get("SKILLOPT_ACP_FIXTURE_SPLIT") == "1":
                chunks = ["[fixture-acp] p", f"ong {joined[:500]}"]
            else:
                chunks = [f"[fixture-acp] {joined[:500]}"]
            for text in chunks:
                _write(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": sid,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": text},
                            },
                        },
                    }
                )
            _reply(req_id, {"stopReason": "end_turn"})
        else:
            _error(req_id, -32601, f"Method not found: {method}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
