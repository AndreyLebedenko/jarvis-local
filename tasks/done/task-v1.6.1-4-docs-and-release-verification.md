# Task v1.6.1-4: Docs and release verification

**Status:** Completed.
**Story:** `tasks/done/story-v1.6.1-builtin-tools-delegated-control.md`
**Depends on:** tasks v1.6.1-1..3.

## Summary

Record the delegation allowlist boundary and the builtin provider
contract in `PROJECT.md`, update config documentation, and prepare the
human-run release verification checklist for v1.6.1.

## Context you need

- Roadmap cross-cutting rule 9 (the allowlist wording to record) and
  the v1.6.1 boundary (builtin tools never conflated with MCP on the
  data-source axis).
- Story design decisions: always-on availability with per-tool toggle,
  reserved provider name, `TOOL` source tag, memory write semantics.
- `PROJECT.md`: tool registry / MCP host sections that the builtin
  provider revises, and the memory files section from v1.5.3.
- Release verification precedent:
  `tasks/done/task-v1.5.3-7-docs-and-release-verification.md` and
  `tasks/done/task-v1.6.0-10-release-verification.md`.

## Boundary

- Documentation and checklist only; code changes limited to fixes the
  verification itself reveals as in-scope for this story (anything
  larger becomes a bug report per the project protocol).

## Requirements

- `PROJECT.md` records, as settled facts:
  - the builtin provider concept (in-process dispatch, same
    interception point, `data_boundary = local`, always-on with
    per-tool toggle, independence from the MCP module switch);
  - the delegation allowlist: reasoning level and the two memory
    files are delegable; microphone sleep, visibility mode, MCP
    module toggles, and MCP server enablement are never delegable;
  - the memory-write contract (audited tool path, caps, next-session
    injection).
- Config documentation (`config.example.toml` and any config docs)
  covers new settings introduced by tasks 1-3, if any.
- A human-run checklist covering: voice-delegated reasoning change
  (reply, indicator, next-turn effect), "remember this" end to end
  including next-session recall, over-cap refusal behavior, builtin
  tools visible and toggleable in the Control Center with MCP off and
  on, and no builtin regression when the MCP module is toggled during
  a session.

## Acceptance criteria

- [x] `PROJECT.md` and config docs updated as above, in the same
      release as the delegation feature (rule 9's requirement).
- [x] The human-run checklist is prepared and handed off; verified
      outcomes are recorded before the story closes.
- [x] `python -m pytest` and Ruff checks are green.

## Human-run verification checklist

Run from the repository root on the Windows 11 machine with local Ollama
running:

```powershell
python -m jarvis --status-console --no-touchstrip
```

Checklist:

1. Start with `[mcp].enabled = false`. Confirm the Control Center tool list
   shows builtin `set_reasoning_level` and `remember` as available, visibly
   separate from any MCP server provider.
2. Disable builtin `remember` from the tool list, ask by text or voice
   "remember that the release token is V161-BUILTIN", and confirm the tool
   call is rejected as disabled and `memory.md` is unchanged. Re-enable it.
3. Ask by voice: "Set reasoning to high." Confirm Jarvis gives a normal
   spoken confirmation, the Control Center reasoning indicator changes to
   High through the usual engine-state event, and the current confirmation is
   not retroactively affected.
4. Ask a follow-up reasoning-heavy question and confirm the next accepted
   turn uses High reasoning. Then set reasoning back to the preferred level.
5. Ask by voice in Russian: "Запомни, что релизный маркер v1.6.1 -
   V161-BUILTIN." Confirm the `remember` tool call succeeds and the Memory
   panel shows the fact appended to `memory.md`.
6. Create a new context or restart Jarvis, then ask what the v1.6.1 release
   marker is. Confirm Jarvis recalls `V161-BUILTIN` only after the next
   session-start sampling boundary.
7. Temporarily fill `memory.md` near its cap through the Memory panel, then
   ask Jarvis to remember another long fact. Confirm the tool returns a clear
   "memory is full/prune in memory panel" style failure and the file is
   unchanged.
8. Enable MCP from the Control Center. Confirm builtin tools remain listed
   once MCP reaches `ON` or `DEGRADED`; disabling MCP again must not remove or
   duplicate builtin tools.
9. Confirm privacy controls are not offered as delegated tools: there is no
   tool for microphone sleep, Open/Hidden, MCP module toggle, or MCP server
   enablement.

Record human results here before moving the story and task cards to
`tasks/done/`.

## Implementation outcome

`PROJECT.md`, README files, config comments, and architecture diagrams now
record the builtin provider, delegation allowlist, and memory-write contract.

Automated verification: `python -m ruff format --check .`,
`python -m ruff check .`, and `python -m pytest` are green.
