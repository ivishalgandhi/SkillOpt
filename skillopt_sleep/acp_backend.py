"""SkillOpt-Sleep ACP backend (native adapter).

Product goal: SkillOpt speaks Agent Client Protocol so any ACP-capable agent
can drive Sleep/train/replay — not a paid-LLM-only path, and not ACP-as-product.

The ACP GitHub fork (`agent-client-protocol`) is a protocol test bed only.
This module is the SkillOpt-side bridge. Do not claim SkillOpt supports ACP
until a real agent transport is wired and green against a live agent.

Wire contract (ACP v1 JSON-RPC methods SkillOpt must speak as *client*):
  initialize → session/new → session/prompt (+ session/update notifications)

Transport:
  * MockAcpAgentTransport — in-process fake (tests / SKILLOPT_SLEEP_ACP_MOCK=1)
  * StdioAcpTransport — spawn SKILLOPT_SLEEP_ACP_AGENT_CMD; NDJSON JSON-RPC over stdio
"""
from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from skillopt_sleep.backend import Backend, exact_score, keyword_soft_score
from skillopt_sleep.types import EditRecord, ReplayResult, TaskRecord

# Stable protocol version SkillOpt negotiates as an ACP client.
ACP_PROTOCOL_VERSION = 1

CLIENT_INFO = {
    "name": "skillopt-sleep-acp",
    "title": "SkillOpt-Sleep ACP adapter",
    "version": "0.0.1-scaffold",
}

# Default read timeout for one JSON-RPC request/response round-trip (seconds).
DEFAULT_STDIO_TIMEOUT = float(os.environ.get("SKILLOPT_SLEEP_ACP_TIMEOUT", "60") or "60")


class AcpBackendError(RuntimeError):
    """Raised when the ACP transport or agent returns an unusable result."""


@dataclass
class JsonRpcMessage:
    """Minimal JSON-RPC 2.0 envelope used on the ACP wire."""

    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    id: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        msg: Dict[str, Any] = {"jsonrpc": "2.0"}
        if self.method is not None:
            msg["method"] = self.method
        if self.params is not None:
            msg["params"] = self.params
        if self.id is not None:
            msg["id"] = self.id
        if self.result is not None:
            msg["result"] = self.result
        if self.error is not None:
            msg["error"] = self.error
        return msg

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class AcpTransport:
    """Abstract bidirectional ACP JSON-RPC transport (stdio / socket / mock)."""

    transcript: List[Dict[str, Any]]

    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def notify(self, method: str, params: Dict[str, Any]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        """Release resources. Default: no-op."""


class MockAcpAgentTransport(AcpTransport):
    """In-process fake ACP agent for contract tests (no network, no LLM).

    Implements the minimal lifecycle SkillOpt needs:
    initialize → session/new → session/prompt.
    """

    def __init__(self) -> None:
        self._next_id = 1
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.transcript: List[Dict[str, Any]] = []

    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        req = JsonRpcMessage(method=method, params=params, id=req_id).to_dict()
        self.transcript.append(req)

        if method == "initialize":
            result = {
                "protocolVersion": int(params.get("protocolVersion", ACP_PROTOCOL_VERSION)),
                "agentCapabilities": {"session": {}},
                "agentInfo": {"name": "mock-acp-agent", "version": "0.0.0"},
                "authMethods": [],
            }
        elif method == "session/new":
            if "cwd" not in params or "mcpServers" not in params:
                raise AcpBackendError("session/new requires cwd and mcpServers")
            sid = f"sess_{uuid.uuid4().hex[:12]}"
            self.sessions[sid] = {"cwd": params["cwd"], "prompts": []}
            result = {"sessionId": sid}
        elif method == "session/prompt":
            sid = params.get("sessionId")
            prompt = params.get("prompt")
            if not sid or prompt is None:
                raise AcpBackendError("session/prompt requires sessionId and prompt")
            if sid not in self.sessions:
                raise AcpBackendError(f"unknown sessionId: {sid}")
            text_bits = []
            for block in prompt:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_bits.append(str(block.get("text", "")))
            joined = "\n".join(text_bits)
            self.sessions[sid]["prompts"].append(joined)
            self.notify(
                "session/update",
                {
                    "sessionId": sid,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": f"[mock-acp] {joined[:500]}"},
                    },
                },
            )
            result = {"stopReason": "end_turn"}
        else:
            raise AcpBackendError(f"unsupported ACP method: {method}")

        resp = JsonRpcMessage(id=req_id, result=result).to_dict()
        self.transcript.append(resp)
        return result

    def notify(self, method: str, params: Dict[str, Any]) -> None:
        note = JsonRpcMessage(method=method, params=params).to_dict()
        self.transcript.append(note)


def _parse_agent_command(command: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(command, str):
        parts = shlex.split(command)
        if not parts:
            raise AcpBackendError("SKILLOPT_SLEEP_ACP_AGENT_CMD is empty")
        return parts
    parts = [str(c) for c in command]
    if not parts:
        raise AcpBackendError("ACP agent command is empty")
    return parts


class StdioAcpTransport(AcpTransport):
    """Spawn an ACP agent subprocess; exchange NDJSON JSON-RPC on stdio.

    Framing per ACP transports: one JSON-RPC message per line, no embedded
    newlines. Agent may log on stderr (captured, not parsed as protocol).
    """

    def __init__(
        self,
        command: Union[str, Sequence[str]],
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_STDIO_TIMEOUT,
    ) -> None:
        self.command = _parse_agent_command(command)
        self.cwd = cwd
        self.timeout = float(timeout)
        self.transcript: List[Dict[str, Any]] = []
        self._next_id = 1
        self._lock = threading.Lock()
        self._pending: Dict[Any, "queue.Queue[Dict[str, Any]]"] = {}
        self._inbox: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._closed = False
        self._reader_error: Optional[BaseException] = None

        child_env = os.environ.copy()
        if env:
            child_env.update(env)

        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                env=child_env,
                text=True,
                bufsize=1,  # line-buffered text
            )
        except OSError as exc:
            raise AcpBackendError(
                f"failed to spawn ACP agent {self.command!r}: {exc}"
            ) from exc

        if self._proc.stdin is None or self._proc.stdout is None:
            self.close()
            raise AcpBackendError("ACP agent subprocess missing stdin/stdout pipes")

        self._reader = threading.Thread(
            target=self._read_loop, name="acp-stdio-reader", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name="acp-stdio-stderr", daemon=True
        )
        self._reader.start()
        self._stderr_thread.start()
        self.stderr_lines: List[str] = []

    def _drain_stderr(self) -> None:
        assert self._proc.stderr is not None
        try:
            for line in self._proc.stderr:
                self.stderr_lines.append(line.rstrip("\n"))
        except Exception:
            pass

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        try:
            for raw in self._proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._reader_error = AcpBackendError(
                        f"ACP agent emitted non-JSON stdout line: {line[:200]!r} ({exc})"
                    )
                    break
                if not isinstance(msg, dict):
                    self._reader_error = AcpBackendError(
                        f"ACP agent emitted non-object JSON: {type(msg).__name__}"
                    )
                    break
                self._dispatch_incoming(msg)
        except Exception as exc:  # noqa: BLE001 — surface to waiting request()
            self._reader_error = exc
        finally:
            # Unblock any waiters on process death / EOF.
            with self._lock:
                for q in self._pending.values():
                    q.put({"jsonrpc": "2.0", "error": {
                        "code": -32000,
                        "message": "ACP agent stdout closed before response",
                    }})
                self._pending.clear()

    def _dispatch_incoming(self, msg: Dict[str, Any]) -> None:
        # Response to our request?
        if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
            req_id = msg.get("id")
            with self._lock:
                waiter = self._pending.get(req_id)
            if waiter is not None:
                waiter.put(msg)
                return
            # Orphan response — keep in transcript for debugging.
            self.transcript.append(msg)
            return

        # Notification or server→client request: record and (for now) ignore requests.
        self.transcript.append(msg)
        if "id" in msg and "method" in msg:
            # Minimal client: reject unexpected agent→client requests so the agent
            # does not hang waiting. Sleep path only needs session/update notifies.
            try:
                self._write(
                    JsonRpcMessage(
                        id=msg["id"],
                        error={
                            "code": -32601,
                            "message": f"SkillOpt ACP client does not handle method {msg.get('method')!r}",
                        },
                    ).to_dict()
                )
            except AcpBackendError:
                pass

    def _write(self, msg: Dict[str, Any]) -> None:
        if self._closed:
            raise AcpBackendError("StdioAcpTransport is closed")
        assert self._proc.stdin is not None
        line = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
        if "\n" in line:
            raise AcpBackendError("ACP JSON-RPC message must not contain embedded newlines")
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except BrokenPipeError as exc:
            raise AcpBackendError("ACP agent stdin closed (BrokenPipe)") from exc

    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self._reader_error is not None:
            raise AcpBackendError(f"ACP agent reader failed: {self._reader_error}")
        if self._proc.poll() is not None:
            raise AcpBackendError(
                f"ACP agent exited early (code={self._proc.returncode}); "
                f"stderr={self.stderr_lines[-5:]!r}"
            )

        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            waiter: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1)
            self._pending[req_id] = waiter

        req = JsonRpcMessage(method=method, params=params, id=req_id).to_dict()
        self.transcript.append(req)
        try:
            self._write(req)
            try:
                resp = waiter.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise AcpBackendError(
                    f"ACP agent timed out after {self.timeout}s waiting for {method!r} "
                    f"(id={req_id}); stderr={self.stderr_lines[-5:]!r}"
                ) from exc
        finally:
            with self._lock:
                self._pending.pop(req_id, None)

        self.transcript.append(resp)
        if "error" in resp and resp["error"] is not None:
            err = resp["error"]
            raise AcpBackendError(f"ACP agent error on {method}: {err}")
        result = resp.get("result")
        if not isinstance(result, dict):
            raise AcpBackendError(f"ACP agent {method} returned non-object result: {result!r}")
        return result

    def notify(self, method: str, params: Dict[str, Any]) -> None:
        note = JsonRpcMessage(method=method, params=params).to_dict()
        self.transcript.append(note)
        self._write(note)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
            return
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                self._proc.kill()
            except Exception:
                pass

    def __enter__(self) -> "StdioAcpTransport":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover — best-effort cleanup
        try:
            self.close()
        except Exception:
            pass


def build_initialize_params(
    *,
    protocol_version: int = ACP_PROTOCOL_VERSION,
    client_info: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """ACP InitializeRequest params SkillOpt sends as client."""
    return {
        "protocolVersion": protocol_version,
        "clientInfo": dict(client_info or CLIENT_INFO),
        "clientCapabilities": {},
    }


def build_session_new_params(*, cwd: str, mcp_servers: Optional[List[Any]] = None) -> Dict[str, Any]:
    """ACP NewSessionRequest params."""
    return {
        "cwd": cwd,
        "mcpServers": list(mcp_servers if mcp_servers is not None else []),
    }


def build_session_prompt_params(*, session_id: str, text: str) -> Dict[str, Any]:
    """ACP PromptRequest params with a single text content block."""
    return {
        "sessionId": session_id,
        "prompt": [{"type": "text", "text": text}],
    }


@dataclass
class AcpSession:
    session_id: str
    cwd: str
    negotiated_version: int = ACP_PROTOCOL_VERSION


class AcpBackend(Backend):
    """SkillOpt-Sleep backend that drives an ACP agent as the execution target.

    With ``MockAcpAgentTransport`` this is safe for unit tests (no LLM).
    With ``StdioAcpTransport`` SkillOpt spawns ``SKILLOPT_SLEEP_ACP_AGENT_CMD``.
    ``transport=None`` raises clearly so we never silently claim ACP support.
    """

    name = "acp"

    def __init__(
        self,
        *,
        model: str = "",
        project_dir: str = ".",
        transport: Optional[AcpTransport] = None,
    ) -> None:
        self.model = model
        self.project_dir = project_dir or "."
        self.transport = transport
        self._session: Optional[AcpSession] = None
        self._tokens = 0
        # Index into transport.transcript; attempt() resets this before each prompt.
        self._chunk_scan_start = 0
        self.preferences = ""

    def _ensure_transport(self) -> AcpTransport:
        if self.transport is None:
            raise AcpBackendError(
                "AcpBackend has no transport. Set SKILLOPT_SLEEP_ACP_AGENT_CMD to an "
                "ACP agent command, SKILLOPT_SLEEP_ACP_MOCK=1 for the in-process fake, "
                "or pass a transport explicitly."
            )
        return self.transport

    def connect(self) -> AcpSession:
        """initialize + session/new. Idempotent if a session already exists."""
        if self._session is not None:
            return self._session
        t = self._ensure_transport()
        init = t.request("initialize", build_initialize_params())
        version = int(init.get("protocolVersion", ACP_PROTOCOL_VERSION))
        cwd = self.project_dir or "."
        created = t.request("session/new", build_session_new_params(cwd=cwd))
        sid = created["sessionId"]
        self._session = AcpSession(session_id=sid, cwd=cwd, negotiated_version=version)
        return self._session

    def attempt(self, task: TaskRecord, skill: str, memory: str, sample_id: int = 0) -> str:
        session = self.connect()
        t = self._ensure_transport()
        prompt = (
            f"Skill:\n{skill}\n\nMemory:\n{memory}\n\n"
            f"Task intent:\n{task.intent}\n\n"
            f"Context:\n{task.context_excerpt}\n"
        )
        if task.system:
            prompt = f"{task.system}\n\n{prompt}"
        self._chunk_scan_start = len(getattr(t, "transcript", None) or [])
        result = t.request(
            "session/prompt",
            build_session_prompt_params(session_id=session.session_id, text=prompt),
        )
        stop = result.get("stopReason")
        if not stop:
            raise AcpBackendError("session/prompt missing stopReason")
        text, n_chars = self._last_agent_text(t)
        self._tokens += n_chars
        return text or f"[acp:{stop}]"

    def judge(self, task: TaskRecord, response: str) -> Tuple[float, float, str]:
        """Score locally. ACP v1 has no judge RPC; Sleep does not ask the agent to judge."""
        hard = exact_score(task.reference, response) if task.reference_kind == "exact" else 0.0
        soft = keyword_soft_score(task.reference, response) if task.reference else 0.0
        return hard, soft, "acp-local-judge"

    def reflect(
        self,
        failures: List[Tuple[TaskRecord, ReplayResult]],
        successes: List[Tuple[TaskRecord, ReplayResult]],
        skill: str,
        memory: str,
        *,
        edit_budget: int,
        evolve_skill: bool,
        evolve_memory: bool,
    ) -> List[EditRecord]:
        raise AcpBackendError(
            "AcpBackend.reflect is not implemented; use DualBackend with a "
            "non-ACP optimizer_backend (e.g. mock) and target_backend=acp."
        )

    def tokens_used(self) -> int:
        """Sum of agent_message_chunk text lengths seen during attempt().

        Proxy for optimizer accounting, not provider billing. ACP v1 does not
        report token usage.
        """
        return self._tokens

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()

    def _last_agent_text(self, transport: AcpTransport) -> Tuple[str, int]:
        # Agents stream the assistant turn as multiple agent_message_chunk
        # session/update notifications (ACP v1). Concatenate text chunks from
        # this prompt's transcript slice only; taking only the last drops earlier deltas.
        transcript = getattr(transport, "transcript", None) or []
        start = self._chunk_scan_start
        if start < 0 or start > len(transcript):
            start = 0
        parts: List[str] = []
        for msg in transcript[start:]:
            if not isinstance(msg, dict):
                continue
            if msg.get("method") != "session/update":
                continue
            params = msg.get("params") or {}
            update = params.get("update") or {}
            if update.get("sessionUpdate") != "agent_message_chunk":
                continue
            content = update.get("content") or {}
            if isinstance(content, dict) and content.get("type") == "text":
                parts.append(str(content.get("text", "")))
        self._chunk_scan_start = len(transcript)
        text = "".join(parts)
        return text, len(text)


def get_acp_backend(
    *,
    model: str = "",
    project_dir: str = "",
    transport: Optional[AcpTransport] = None,
    use_mock: bool = False,
    agent_cmd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> AcpBackend:
    """Factory used by get_backend / tests.

    Precedence when ``transport`` is None:
      1. ``use_mock`` / SKILLOPT_SLEEP_ACP_MOCK → MockAcpAgentTransport
      2. ``agent_cmd`` argument, else SKILLOPT_SLEEP_ACP_AGENT_CMD
      3. else SKILLOPT_SLEEP_ACP_AGENT via resolve_acp_agent_command
      4. else transport stays None (explicit error on use)
    """
    if transport is None and not use_mock and not agent_cmd:
        agent_cmd = os.environ.get("SKILLOPT_SLEEP_ACP_AGENT_CMD", "").strip() or None
        if not agent_cmd:
            from skillopt_sleep.acp_agents import resolve_acp_agent_command

            agent_cmd = resolve_acp_agent_command(
                agent_name=os.environ.get("SKILLOPT_SLEEP_ACP_AGENT"),
                agent_cmd=None,
                claude_cmd=os.environ.get("SKILLOPT_SLEEP_ACP_CLAUDE_CMD"),
            )
    if transport is None and use_mock:
        transport = MockAcpAgentTransport()
    elif transport is None and agent_cmd:
        # Agent working directory is negotiated via session/new (project_dir),
        # not the subprocess cwd — only honor an explicit spawn cwd env.
        spawn_cwd = os.environ.get("SKILLOPT_SLEEP_ACP_AGENT_CWD", "").strip() or None
        if spawn_cwd and not os.path.isdir(spawn_cwd):
            raise AcpBackendError(
                f"SKILLOPT_SLEEP_ACP_AGENT_CWD is not a directory: {spawn_cwd!r}"
            )
        transport = StdioAcpTransport(
            agent_cmd,
            cwd=spawn_cwd,
            timeout=float(timeout if timeout is not None else DEFAULT_STDIO_TIMEOUT),
        )
    return AcpBackend(
        transport=transport,
        model=model,
        project_dir=project_dir or ".",
    )
