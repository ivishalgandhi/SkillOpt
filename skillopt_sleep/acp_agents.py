"""Named ACP stdio agent presets. No process spawn. No API-key env reads.

Legacy package ``@zed-industries/claude-code-acp`` is deprecated. Do not select it.
"""
from __future__ import annotations

import shlex

# Pinned ACP adapter for the claude preset. Override with claude_cmd.
DEFAULT_CLAUDE_ACP_PACKAGE = "@agentclientprotocol/claude-agent-acp@0.107.0"

ACP_AGENT_PRESETS: dict[str, list[str]] = {
    "cursor": ["cursor-agent", "acp"],
    "devin": ["devin", "acp"],
}

_CLAUDE = "claude"
_CUSTOM = "custom"


def list_acp_agent_names() -> tuple[str, ...]:
    return ("cursor", "devin", _CLAUDE, _CUSTOM)


def resolve_acp_agent_command(
    *,
    agent_name: str | None,
    agent_cmd: str | None,
    claude_cmd: str | None,
) -> str | None:
    """Return a shell command for a preset, or None when nothing is selected.

    Precedence: a non-empty ``agent_cmd`` wins over cursor/devin/claude
    (back-compat). ``custom`` requires ``agent_cmd``. ``claude`` uses
    ``claude_cmd`` or ``npx -y <DEFAULT_CLAUDE_ACP_PACKAGE>``.
    Mock selection is not handled here.
    """
    name = (agent_name or "").strip().lower()
    cmd = (agent_cmd or "").strip()
    claude = (claude_cmd or "").strip()
    if not name:
        return cmd or None
    if name not in list_acp_agent_names():
        from skillopt_sleep.acp_backend import AcpBackendError

        raise AcpBackendError(
            f"Unknown ACP agent {agent_name!r}. Known: {', '.join(list_acp_agent_names())}."
        )
    if name == _CUSTOM:
        if not cmd:
            from skillopt_sleep.acp_backend import AcpBackendError

            raise AcpBackendError(
                "ACP agent 'custom' requires agent_cmd (SKILLOPT_SLEEP_ACP_AGENT_CMD)."
            )
        return cmd
    if cmd:
        return cmd
    if name == _CLAUDE:
        if claude:
            return claude
        return f"npx -y {DEFAULT_CLAUDE_ACP_PACKAGE}"
    return shlex.join(ACP_AGENT_PRESETS[name])
