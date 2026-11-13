# SkillOpt ↔ ACP adapter

**Status:** stdio transport landed; **not** an official SkillOpt plugin yet.
Do **not** claim SkillOpt supports ACP until a real (non-fixture) ACP agent
is green end-to-end.

## Why this exists

SkillOpt is the **product**. We want **native ACP** so any ACP-capable agent
(editor or coding agent) can participate in SkillOpt-Sleep harvest / train /
replay — broad utilization, not a paid-LLM-only path.

The GitHub ACP fork (`ivishalgandhi/agent-client-protocol`) is a **protocol
test bed** (schema / session-lifecycle correctness). It is **not** the product
we ship.

## SkillOpt-side pieces

| Piece | Path | Role |
|---|---|---|
| Sleep backend | `skillopt_sleep/acp_backend.py` | ACP *client*: `initialize` → `session/new` → `session/prompt` |
| Stdio transport | `StdioAcpTransport` in same module | Spawns `SKILLOPT_SLEEP_ACP_AGENT_CMD`; NDJSON JSON-RPC |
| Fixture agent | `tests/fixtures/acp_fixture_agent.py` | Minimal stdio agent for contract tests |
| Contract tests | `tests/test_acp_backend_contract.py` | Mock + stdio fixture lifecycles |
| This folder | `plugins/acp/` | Future installable integration (MCP/CLI wrapper) |

## Env vars

| Var | Meaning |
|---|---|
| `SKILLOPT_SLEEP_ACP_MOCK=1` | In-process fake agent (wins over agent cmd) |
| `SKILLOPT_SLEEP_ACP_AGENT_CMD` | Shell command for real/fixture ACP agent (stdio) |
| `SKILLOPT_SLEEP_ACP_TIMEOUT` | Per-request timeout seconds (default 60) |
| `SKILLOPT_SLEEP_ACP_AGENT_CWD` | Optional subprocess cwd (defaults to inherit) |

Select with `--backend acp`.

## Reuse from ACP fork

- Session lifecycle shapes: `initialize`, `session/new`, `session/prompt`,
  `session/update` (see fork schema `schema/v1`).
- Framing: newline-delimited JSON-RPC on stdio (`docs/protocol/v1/transports`).

## Upstream later (optional)

1. SkillOpt plugin PR when a real product agent + docs are green.
2. ACP protocol PR only for gaps found while building the adapter.
