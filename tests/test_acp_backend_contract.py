"""Contract tests for SkillOpt native ACP adapter (Sleep backend).

These define what SkillOpt must speak over ACP for attempt/replay sessions.
Mock path: in-process MockAcpAgentTransport (no subprocess).
Stdio path: fixture agent over NDJSON JSON-RPC (no paid LLM).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from skillopt_sleep.acp_backend import (
    ACP_PROTOCOL_VERSION,
    AcpBackend,
    AcpBackendError,
    MockAcpAgentTransport,
    StdioAcpTransport,
    build_initialize_params,
    build_session_new_params,
    build_session_prompt_params,
)
from skillopt_sleep.backend import build_backend, get_backend
from skillopt_sleep.types import TaskRecord

FIXTURE_AGENT = Path(__file__).resolve().parent / "fixtures" / "acp_fixture_agent.py"


def _clear_acp_env() -> None:
    os.environ.pop("SKILLOPT_SLEEP_ACP_MOCK", None)
    os.environ.pop("SKILLOPT_SLEEP_ACP_AGENT_CMD", None)


def test_initialize_params_match_acp_v1_required_fields() -> None:
    params = build_initialize_params()
    assert params["protocolVersion"] == ACP_PROTOCOL_VERSION
    assert "clientInfo" in params
    assert params["clientInfo"]["name"] == "skillopt-sleep-acp"


def test_session_new_params_require_cwd_and_mcp_servers() -> None:
    params = build_session_new_params(cwd="/tmp/project")
    assert params["cwd"] == "/tmp/project"
    assert params["mcpServers"] == []


def test_session_prompt_params_use_text_content_blocks() -> None:
    params = build_session_prompt_params(session_id="sess_1", text="hello")
    assert params["sessionId"] == "sess_1"
    assert params["prompt"] == [{"type": "text", "text": "hello"}]


def test_lifecycle_initialize_session_new_session_prompt() -> None:
    transport = MockAcpAgentTransport()
    backend = AcpBackend(transport=transport, project_dir="/tmp/skillopt-acp")
    session = backend.connect()
    assert session.session_id.startswith("sess_")
    assert session.negotiated_version == ACP_PROTOCOL_VERSION

    task = TaskRecord(
        id="t1",
        project="demo",
        intent="say hello",
        context_excerpt="unit test",
        reference_kind="exact",
        reference="hello",
    )
    response = backend.attempt(task, skill="be brief", memory="")
    assert "[mock-acp]" in response

    methods = [m.get("method") for m in transport.transcript if isinstance(m, dict) and "method" in m]
    assert methods.count("initialize") == 1
    assert methods.count("session/new") == 1
    assert methods.count("session/prompt") == 1
    assert "session/update" in methods


def test_get_backend_acp_without_mock_env_has_no_silent_transport() -> None:
    _clear_acp_env()
    be = get_backend("acp")
    assert isinstance(be, AcpBackend)
    assert be.transport is None
    with pytest.raises(AcpBackendError, match="no transport"):
        be.connect()


def test_get_backend_acp_mock_env_enables_in_process_agent(monkeypatch) -> None:
    monkeypatch.delenv("SKILLOPT_SLEEP_ACP_AGENT_CMD", raising=False)
    monkeypatch.setenv("SKILLOPT_SLEEP_ACP_MOCK", "1")
    be = get_backend("acp", project_dir="/tmp/acp-mock")
    assert isinstance(be, AcpBackend)
    assert isinstance(be.transport, MockAcpAgentTransport)
    session = be.connect()
    assert session.session_id


def test_build_backend_lists_acp() -> None:
    _clear_acp_env()
    be = build_backend(backend="acp")
    assert be.name == "acp"


def test_reflect_refuses_so_optimizer_stays_non_acp() -> None:
    be = AcpBackend(transport=MockAcpAgentTransport())
    with pytest.raises(AcpBackendError, match="DualBackend"):
        be.reflect([], [], "skill", "", edit_budget=1, evolve_skill=True, evolve_memory=False)


def test_acp_is_not_claimed_as_official_plugin_yet() -> None:
    """Guardrail: plugins/README must not list ACP until a real product agent is green."""
    from pathlib import Path

    readme = Path(__file__).resolve().parents[1] / "plugins" / "README.md"
    text = readme.read_text(encoding="utf-8")
    # Scaffold folder may exist; official integrations table must not claim ACP yet.
    table = text.split("## Available integrations", 1)[1].split("## Install", 1)[0]
    assert "| **ACP**" not in table
    assert "acp/" not in table.lower()


@pytest.mark.skipif(not FIXTURE_AGENT.is_file(), reason="fixture agent missing")
def test_stdio_transport_lifecycle_with_fixture_agent() -> None:
    """Non-mock contract: StdioAcpTransport ↔ fixture agent over NDJSON stdio."""
    cmd = f"{sys.executable} {FIXTURE_AGENT}"
    transport = StdioAcpTransport(cmd, timeout=15.0)
    try:
        backend = AcpBackend(transport=transport, project_dir="/tmp/skillopt-acp-stdio")
        session = backend.connect()
        assert session.session_id.startswith("sess_")

        task = TaskRecord(
            id="t-stdio",
            project="demo",
            intent="say hello over stdio",
            context_excerpt="fixture agent",
            reference_kind="exact",
            reference="hello",
        )
        response = backend.attempt(task, skill="be brief", memory="")
        assert "[fixture-acp]" in response

        methods = [
            m.get("method")
            for m in transport.transcript
            if isinstance(m, dict) and "method" in m
        ]
        assert methods.count("initialize") == 1
        assert methods.count("session/new") == 1
        assert methods.count("session/prompt") == 1
        assert "session/update" in methods
    finally:
        transport.close()


@pytest.mark.skipif(not FIXTURE_AGENT.is_file(), reason="fixture agent missing")
def test_get_backend_acp_agent_cmd_uses_stdio_transport(monkeypatch) -> None:
    monkeypatch.delenv("SKILLOPT_SLEEP_ACP_MOCK", raising=False)
    monkeypatch.setenv(
        "SKILLOPT_SLEEP_ACP_AGENT_CMD",
        f"{sys.executable} {FIXTURE_AGENT}",
    )
    be = get_backend("acp", project_dir="/tmp/acp-stdio-env")
    assert isinstance(be, AcpBackend)
    assert isinstance(be.transport, StdioAcpTransport)
    try:
        session = be.connect()
        assert session.session_id.startswith("sess_")
    finally:
        be.close()


def test_get_backend_mock_wins_over_agent_cmd(monkeypatch) -> None:
    monkeypatch.setenv("SKILLOPT_SLEEP_ACP_MOCK", "1")
    monkeypatch.setenv("SKILLOPT_SLEEP_ACP_AGENT_CMD", "should-not-spawn")
    be = get_backend("acp")
    assert isinstance(be.transport, MockAcpAgentTransport)
