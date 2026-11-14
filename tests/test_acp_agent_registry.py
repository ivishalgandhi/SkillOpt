"""Pure tests for ACP agent preset resolution. No subprocess."""
from __future__ import annotations

import os

import pytest

from skillopt_sleep.acp_agents import (
    DEFAULT_CLAUDE_ACP_PACKAGE,
    list_acp_agent_names,
    resolve_acp_agent_command,
)
from skillopt_sleep.acp_backend import AcpBackendError


def test_list_names_covers_presets() -> None:
    assert list_acp_agent_names() == ("cursor", "devin", "claude", "custom")


def test_empty_selection_is_none() -> None:
    assert resolve_acp_agent_command(agent_name=None, agent_cmd=None, claude_cmd=None) is None
    assert resolve_acp_agent_command(agent_name="  ", agent_cmd="", claude_cmd=None) is None


def test_cursor_and_devin_commands() -> None:
    assert resolve_acp_agent_command(agent_name="cursor", agent_cmd=None, claude_cmd=None) == "cursor-agent acp"
    assert resolve_acp_agent_command(agent_name="Devin", agent_cmd=None, claude_cmd=None) == "devin acp"


def test_claude_default_and_override() -> None:
    default = resolve_acp_agent_command(agent_name="claude", agent_cmd=None, claude_cmd=None)
    assert default == f"npx -y {DEFAULT_CLAUDE_ACP_PACKAGE}"
    assert "@zed-industries/claude-code-acp" not in default
    override = resolve_acp_agent_command(
        agent_name="claude", agent_cmd=None, claude_cmd="claude-agent-acp"
    )
    assert override == "claude-agent-acp"


def test_claude_preset_spawn_command_ignores_api_key_env(monkeypatch) -> None:
    """AGENT=claude yields a command string and does not write an API key env."""
    from skillopt_sleep.acp_backend import StdioAcpTransport
    from skillopt_sleep.backend import get_backend

    monkeypatch.delenv("SKILLOPT_SLEEP_ACP_MOCK", raising=False)
    monkeypatch.delenv("SKILLOPT_SLEEP_ACP_AGENT_CMD", raising=False)
    monkeypatch.setenv("SKILLOPT_SLEEP_ACP_AGENT", "claude")
    monkeypatch.setenv("SKILLOPT_SLEEP_ACP_CLAUDE_CMD", "echo claude-acp")
    key = "ANTHROPIC_API_KEY"
    before = os.environ.get(key)
    captured: dict[str, str] = {}

    class _Capture(StdioAcpTransport):
        def __init__(self, command: str, **kwargs: object) -> None:
            captured["command"] = command

    monkeypatch.setattr("skillopt_sleep.acp_backend.StdioAcpTransport", _Capture)
    get_backend("acp")
    assert captured["command"] == "echo claude-acp"
    assert os.environ.get(key) == before
    assert key not in captured["command"]


def test_explicit_cmd_wins_over_preset() -> None:
    got = resolve_acp_agent_command(
        agent_name="cursor", agent_cmd="my-agent acp", claude_cmd="ignored"
    )
    assert got == "my-agent acp"


def test_custom_requires_cmd() -> None:
    with pytest.raises(AcpBackendError, match="custom"):
        resolve_acp_agent_command(agent_name="custom", agent_cmd=None, claude_cmd=None)
    assert (
        resolve_acp_agent_command(agent_name="custom", agent_cmd="echo hi", claude_cmd=None)
        == "echo hi"
    )


def test_unknown_preset_raises() -> None:
    with pytest.raises(AcpBackendError, match="Unknown ACP agent"):
        resolve_acp_agent_command(agent_name="copilot", agent_cmd="x", claude_cmd=None)
