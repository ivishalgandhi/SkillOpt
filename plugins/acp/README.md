# SkillOpt ↔ ACP adapter

**Status:** not an official plugin. Cursor and Devin pong proves passed from a
desktop terminal. The Claude preset is blocked (`model_not_found`). Do not
claim SkillOpt officially supports ACP.

## Why this exists

SkillOpt is the **product**. We want **native ACP** so any ACP-capable agent
(editor or coding agent) can participate in SkillOpt-Sleep harvest / train /
replay — broad utilization, not a paid-LLM-only path.

The ACP protocol fork is a **protocol test bed** (schema / session-lifecycle
correctness). It is **not** the product we ship.

## SkillOpt-side pieces

| Piece | Path | Role |
|---|---|---|
| Sleep backend | `skillopt_sleep/acp_backend.py` | ACP *client*: `initialize` → `session/new` → `session/prompt` |
| Agent presets | `skillopt_sleep/acp_agents.py` | Named stdio commands (`cursor`, `devin`, `claude`, `custom`) |
| Stdio transport | `StdioAcpTransport` in the backend module | Spawns the resolved command; NDJSON JSON-RPC |
| Fixture agent | `tests/fixtures/acp_fixture_agent.py` | Minimal stdio agent for contract tests |
| Contract tests | `tests/test_acp_backend_contract.py`, `tests/test_acp_agent_registry.py` | Mock, fixture, preset resolution |
| This folder | `plugins/acp/` | Future installable integration (MCP/CLI wrapper) |

## Presets

| Name | Command | Notes |
|---|---|---|
| `cursor` | `cursor-agent acp` | Desktop login. A locked keychain (typical of a headless SSH shell) can fail the prove. |
| `devin` | `devin acp` | Stdio agent binary on `PATH`. |
| `claude` | `npx -y @agentclientprotocol/claude-agent-acp@0.107.0` | Claude Code **login**, not an API key. SkillOpt never sets or reads an API key for this preset. Do not switch the default to `@zed-industries/claude-code-acp` (that package's README uses an API key). |
| `custom` | — | Requires `SKILLOPT_SLEEP_ACP_AGENT_CMD`. |

`SKILLOPT_SLEEP_ACP_CLAUDE_CMD` replaces the Claude `npx` line with a full shell command (standalone binary or another pin).

## Env vars

| Var | Meaning |
|---|---|
| `SKILLOPT_SLEEP_ACP_MOCK=1` | In-process fake agent |
| `SKILLOPT_SLEEP_ACP_AGENT_CMD` | Explicit shell command (fixture or any stdio agent) |
| `SKILLOPT_SLEEP_ACP_AGENT` | Preset name: `cursor`, `devin`, `claude`, or `custom` |
| `SKILLOPT_SLEEP_ACP_CLAUDE_CMD` | Optional override for the `claude` preset only |
| `SKILLOPT_SLEEP_ACP_TIMEOUT` | Per-request timeout seconds (default 60) |
| `SKILLOPT_SLEEP_ACP_AGENT_CWD` | Optional subprocess cwd (defaults to inherit) |
| `SKILLOPT_SLEEP_ACP_MODEL` | Optional model id. Sent only when the session advertises models (`session/set_model`, or config option id `model`) |

Select with `--backend acp`.

## Precedence

1. `SKILLOPT_SLEEP_ACP_MOCK` wins over every command and preset.
2. A non-empty `SKILLOPT_SLEEP_ACP_AGENT_CMD` wins over `SKILLOPT_SLEEP_ACP_AGENT` (same behavior as before presets).
3. Otherwise `SKILLOPT_SLEEP_ACP_AGENT` resolves to a command. `custom` with no command is an error.
4. If none of those are set, the backend has no transport and `connect()` fails with a clear error.

## Judge and tokens

ACP v1 has no judge RPC. `AcpBackend.judge` scores on the SkillOpt side with `exact_score` and `keyword_soft_score`.

`tokens_used()` is the character length of `agent_message_chunk` text seen during `attempt()`. That is an optimizer proxy, not provider billing. ACP v1 does not report usage.

## Prove note

Cursor and Claude proves need a desktop session where that agent's existing login is already usable (keychain unlocked). Do not inject an API key to make Claude start. If the adapter asks for a fresh login or an API key, stop.

## Reuse from ACP fork

- Session lifecycle shapes: `initialize`, `session/new`, `session/prompt`,
  `session/update` (see fork schema `schema/v1`).
- Framing: newline-delimited JSON-RPC on stdio (`docs/protocol/v1/transports`).

## Upstream later (optional)

1. SkillOpt plugin PR when a real product agent + docs are green.
2. ACP protocol PR only for gaps found while building the adapter.
