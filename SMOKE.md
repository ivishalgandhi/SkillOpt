# ACP smoke test

Run from a fresh shell at the repo root of branch `feat/skillopt-native-acp-adapter`.
`PYTHONPATH=.` loads this worktree. Do not export an API key.

Env vars the ACP backend reads:

| Var | Role |
|---|---|
| `SKILLOPT_SLEEP_ACP_MOCK` | `1` / `true` / `yes` / `on` uses the in-process fake. Wins over everything. |
| `SKILLOPT_SLEEP_ACP_AGENT_CMD` | Explicit stdio command. Wins over the preset. |
| `SKILLOPT_SLEEP_ACP_AGENT` | `cursor`, `devin`, `claude`, or `custom`. |
| `SKILLOPT_SLEEP_ACP_CLAUDE_CMD` | Replaces the Claude `npx` command. Ignored unless the preset is `claude` and `AGENT_CMD` is empty. |
| `SKILLOPT_SLEEP_ACP_TIMEOUT` | Seconds for one JSON-RPC round trip. Default `60`. |
| `SKILLOPT_SLEEP_ACP_AGENT_CWD` | Optional subprocess cwd. Must be an existing directory. Default: inherit. |
| `SKILLOPT_SLEEP_ACP_MODEL` | Optional model id. Applied only when the session advertises models: `session/set_model` for `models.availableModels`, or `session/set_config_option` when a config option id is `model`. Aliases match an advertised value (`sonnet` → `sonnet`). Unadvertised sessions keep the agent default. |

`custom` with an empty `SKILLOPT_SLEEP_ACP_AGENT_CMD` raises `AcpBackendError`.

The one-shot below is the command that matches this branch. `skillopt-sleep --backend acp` starts a sleep cycle, not this pong check. A relative `project_dir` is made absolute before `session/new` (`os.path.abspath`). The Claude adapter rejects a relative `cwd`.

```bash
cd /path/to/this/repo
unset SKILLOPT_SLEEP_ACP_MOCK SKILLOPT_SLEEP_ACP_AGENT SKILLOPT_SLEEP_ACP_AGENT_CMD SKILLOPT_SLEEP_ACP_CLAUDE_CMD
# set ONE of the exports in the sections below, then:
PYTHONPATH=. python3 - <<'PY'
import os
from skillopt_sleep.backend import get_backend
from skillopt_sleep.types import TaskRecord
be = get_backend("acp", project_dir=os.getcwd())
task = TaskRecord(
    id="pong",
    project="smoke",
    intent="reply with the single word: pong",
    system="Reply with only the single word requested. No punctuation.",
    reference_kind="exact",
    reference="pong",
)
text = be.attempt(task, skill="", memory="")
hard, soft, _why = be.judge(task, text)
print("session", be._session.session_id)
print("protocol", be._session.negotiated_version)
print("hard", hard, "soft", soft)
print("response", text)
be.close()
PY
```

## Mock

```bash
export SKILLOPT_SLEEP_ACP_MOCK=1
```

Expected: `protocol 1`, `hard 1.0`, `soft 1.0`, `response` starts with `[mock-acp]` and contains the intent text. Session id looks like `sess_` plus 12 hex chars. `hard 1.0` is because that echo includes the word `pong`, not because a model answered.

Checked on this branch: `session sess_0d5855b2249b`, `hard 1.0`, `soft 1.0`.

## Fixture

Leave mock unset.

```bash
export SKILLOPT_SLEEP_ACP_AGENT_CMD="python3 tests/fixtures/acp_fixture_agent.py"
```

Expected: same shape as mock, but the response starts with `[fixture-acp]`. `hard 1.0` for the same echo reason.

Checked: `session sess_e135df6b639a`, `hard 1.0`, `soft 1.0`.

Optional split (two chunks, still one body containing `pong`):

```bash
export SKILLOPT_ACP_FIXTURE_SPLIT=1
export SKILLOPT_SLEEP_ACP_AGENT_CMD="python3 tests/fixtures/acp_fixture_agent.py"
```

## Cursor

Desktop terminal only. Over SSH the login keychain is locked and `cursor-agent acp` can fail. That is not an adapter bug.

```bash
unset SKILLOPT_SLEEP_ACP_MOCK SKILLOPT_SLEEP_ACP_AGENT_CMD
export SKILLOPT_SLEEP_ACP_AGENT=cursor
```

Resolved command: `cursor-agent acp`.

Expected: `protocol 1`, `response` is `pong`, `hard 1.0`, `soft 1.0`.

Checked from a desktop pane: `session f0f286e0-5b8c-4704-bb91-451d96ac51bd`, `response pong`, `hard 1.0`, `soft 1.0`, about 4.3s.

## Devin

SSH or desktop. `devin` must be on `PATH`.

```bash
unset SKILLOPT_SLEEP_ACP_MOCK SKILLOPT_SLEEP_ACP_AGENT_CMD
export SKILLOPT_SLEEP_ACP_AGENT=devin
```

Resolved command: `devin acp`.

Expected: `protocol 1`, `response` is `pong`, `hard 1.0`, `soft 1.0`.

Checked: `session carefree-cobra`, `response pong`, `hard 1.0`, `soft 1.0`, about 2.3s.

## Claude

**Blocked.** Do not treat this preset as proven.

```bash
unset SKILLOPT_SLEEP_ACP_MOCK SKILLOPT_SLEEP_ACP_AGENT_CMD
export SKILLOPT_SLEEP_ACP_AGENT=claude
```

Resolved command: `npx -y @agentclientprotocol/claude-agent-acp@0.107.0`.
There is no `claude` binary on `PATH` here. The adapter still starts via `npx`. Do not point `SKILLOPT_SLEEP_ACP_CLAUDE_CMD` at `@zed-industries/claude-code-acp`.

The adapter advertises config option `model` with values `default`, `opus`, `fable`, `sonnet`, `haiku`. `default` is sent as `claude-opus-5-5`. Set a value before the one-shot:

```bash
export SKILLOPT_SLEEP_ACP_MODEL=sonnet
```

What happened with the API key unset and no login attempt:

1. A relative `project_dir` is now `os.path.abspath`'d before `session/new`. Sending `cwd` `.` without that step fails: `Invalid params: cwd must be an absolute path`.
2. `initialize` and `session/new` succeed. `SKILLOPT_SLEEP_ACP_MODEL` calls `session/set_config_option` (`configId=model`).
3. `session/prompt` still fails. Exact agent errors:

```text
sonnet: Internal error: There's an issue with the selected model (claude-sonnet-5-5). It may not exist or you may not have access to it.
haiku: Internal error: There's an issue with the selected model (claude-haiku-5-5). It may not exist or you may not have access to it.
```

`errorKind` is `model_not_found` for both. Sessions `53993414-bef3-4e9a-a42c-ad8f4f2ca97c` (sonnet) and `7d71655b-a8c6-41bc-9852-28737136ec49` (haiku). No interactive login was started. Stop there. Do not export an API key to get past it.

## Contract tests

```bash
python3 -m pytest -q tests/test_acp_backend_contract.py tests/test_acp_agent_registry.py
```

Expected: `33 passed`.
