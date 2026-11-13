# SkillOpt ↔ ACP adapter plan

**Host:** m4 (`/Users/vishal/code/…`) — OMB `/data/code/…` is copy source only  
**Product:** SkillOpt with **native ACP** (world-usable)  
**Not the product:** ACP GitHub fork (protocol test bed only)  
**Not a path:** paying an LLM instead of speaking ACP

## Adapter plan

1. SkillOpt-Sleep is an ACP **client**; coding agents are ACP **agents**.
2. Minimum wire for Sleep `attempt` / replay: `initialize` → `session/new` → `session/prompt` (+ `session/update` chunks).
3. Map `TaskRecord` + skill/memory into a single text prompt content block; later add resource links / tools.
4. Keep `reflect` / optimizer on a non-ACP backend (`DualBackend`: `target_backend=acp`, `optimizer_backend=mock|claude|…`).
5. Reuse ACP fork only for schema/session-lifecycle correctness tests — do not ship the fork as a product.
6. Real transport: stdio JSON-RPC (NDJSON) to an ACP agent binary via `SKILLOPT_SLEEP_ACP_AGENT_CMD`.
7. Harvest later: optional ACP session logs → `SessionDigest` (after attempt path works).
8. Plugin packaging (`plugins/acp/`) after a **real** product agent (not just the fixture) is green — then optional SkillOpt upstream PR.
9. Optional ACP upstream PR only for protocol gaps discovered by the adapter.
10. Never claim “SkillOpt supports ACP” until real transport + contract tests pass against a live ACP-capable agent (fixture proves the transport; product claim needs a real agent).

## Status (2026-11-13)

- [x] Scaffold `skillopt_sleep/acp_backend.py` + register `--backend acp`.
- [x] Contract tests with `MockAcpAgentTransport`.
- [x] `StdioAcpTransport` spawning `SKILLOPT_SLEEP_ACP_AGENT_CMD` (NDJSON stdio).
- [x] Fixture agent + non-mock stdio contract tests.
- [x] Real-agent prove: `cursor-agent acp` over stdio — initialize + session/new
      + session/prompt + multi-chunk `agent_message_chunk` assembly + judge
      (exact_score hard=1.0 on "pong"). Keychain was unlocked on m4.
- [ ] Official plugins/README claim + optional upstream PRs (held for Vishal GO;
      guardrail test `test_acp_is_not_claimed_as_official_plugin_yet` stays in
      place until that PR lands).

## Real-agent prove log (2026-11-13, m4)

```
SKILLOPT_SLEEP_ACP_AGENT_CMD="cursor-agent acp"  (no mock)
initialize  -> protocolVersion=1, agentCapabilities.session
session/new -> sessionId=0018c8b7-...
session/prompt (intent: "reply with the single word: pong")
  session/update: agent_message_chunk "p" + "ong"  (streamed)
  -> assembled "pong"
judge: hard=1.0 soft=1.0 (exact_score vs reference "pong")
```

Bug found + fixed during prove: `_last_agent_text` took only the last
`agent_message_chunk` delta; real agents stream multiple. Now concatenates
all chunks in transcript order.

## How to run

```bash
# Mock (in-process):
SKILLOPT_SLEEP_ACP_MOCK=1 skillopt-sleep --backend acp …

# Stdio fixture agent (transport proof, not product support):
SKILLOPT_SLEEP_ACP_AGENT_CMD="python3 tests/fixtures/acp_fixture_agent.py" \
  skillopt-sleep --backend acp …

# Real agent (when available):
SKILLOPT_SLEEP_ACP_AGENT_CMD="/path/to/acp-agent …" skillopt-sleep --backend acp …
```
