# Story v1.6.1: Builtin tool provider and delegated control

**Status:** Completed.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.6.1 section; delegation
semantics for `set_reasoning_level` decided 2026-07-18).
**Created:** 2026-07-20.

## User-facing goal

Jarvis gains its first delegated control over its own settings by voice:
"switch to high reasoning" changes the reasoning level through an audited
tool call, and "remember this" writes durable facts into memory.md /
self.md instead of being lost at session end. Both run through the same
tool machinery the user already sees in the Control Center.

## Boundaries

- Exactly three tools: `set_reasoning_level` plus the memory write tools
  for memory.md and self.md. No camera (v1.6.2), no settings beyond the
  reasoning level.
- Cross-cutting rule 9: privacy-relevant controls (microphone sleep,
  visibility mode, MCP module toggles, MCP server enablement) are never
  delegable. The allowlist boundary is recorded in `PROJECT.md` in the
  same change that introduces delegation.
- Cross-cutting rule 7: model-written memory stays size-capped, visible
  and editable in the UI, and flows only through the audited tool path.
  The existing `MemoryFileRepository` caps and UI editing from v1.5.3
  are the enforcement points; this story adds no second write path.
- Builtin tools are never gated by the MCP module switch and never
  conflated with the external MCP capability on the data-source axis:
  `data_boundary = local`, always, and dispatch is an in-process call -
  no subprocess, no network.
- Runtime locality unchanged. Nothing in this story touches the
  network beyond the already-configured local Ollama endpoint.

## Design decisions (proposed here, confirmed by card approval)

- **Builtin tools share the single interception point.** The registry
  (`jarvis.tools.registry.ToolRegistry`) and dispatcher
  (`jarvis.tools.interception.ToolDispatcher`) currently live inside
  `McpHost`, and the dispatcher resolves a provider name to an MCP
  client. The builtin provider registers its tools in the same registry
  under a reserved provider name and satisfies the dispatcher's existing
  client protocol (`call_tool(name, arguments) -> ToolCallResult`) with
  an in-process implementation - same `ToolCallStarted` /
  `ToolCallFinished` audit events, same localized `SystemEvent`s, same
  Control Center tool list, no second dispatch path. How registry and
  dispatcher ownership is untangled from `McpHost`'s lifecycle is
  task-1's core design question; the constraint is that "MCP off" must
  keep meaning "no MCP client objects exist" while builtin tools stay
  available.
- **Availability contract: always-on, per-tool toggleable.** The builtin
  provider has no module switch of its own: it is constructed at startup
  and its tools are registered whenever tool calling is active. The
  existing per-tool enable/disable in the Control Center tool list
  (`ToolRegistry.set_tool_enabled`) applies to builtin tools exactly as
  to MCP tools, which gives the user a kill switch per tool without
  inventing a new module concept. The tool list must still show the
  provider distinctly (builtin vs a named MCP server) so the two
  capabilities are never visually conflated.
- **`set_reasoning_level` semantics (decided 2026-07-18):** the tool
  calls the existing single state owner
  (`ReasoningLevelState.set_level`) with a new source tag (working name
  `TOOL`). The established "sampled at turn start" contract is
  untouched: the change applies from the next accepted turn, and the
  confirming reply ("Done, ready to reason") is an ordinary tool round
  trip within the current turn. Hotkey, UI, and voice paths all mutate
  the same state; the UI stays honest via the existing
  `ReasoningLevelChanged` engine-state event - no new UI wiring.
- **Memory writes go through `MemoryFileRepository`.** Two operations
  per file, exposed in whatever tool shape task-3 finds cleanest
  (proposed: one `remember` tool with a `file` argument plus an
  append/replace mode): append a fact, or replace content, always
  validated against the per-file cap. An over-cap write fails as a
  normal tool error the model can hear and relay ("memory is full") -
  never silent truncation of user-auditable memory (contrast with the
  injection-side truncation, which is read-only and logged). Mid-session
  writes follow v1.5.3's sampling contract: they take effect in the
  system prompt at the next session start, and the tool's result says
  so, so the model does not claim instant recall it does not have.
- **Self-knowledge lands as data, not code:** after
  `set_reasoning_level` exists, self.md (user-editable, and now
  model-appendable) is where "Jarvis knows it has switchable reasoning
  modes" lives. No code path depends on that text.

## Scope (ordered task cards)

- `tasks/done/task-v1.6.1-1-builtin-provider-core.md` - the builtin provider
  concept in the registry/dispatcher, ownership untangling, audit
  parity, Control Center visibility.
- `tasks/done/task-v1.6.1-2-set-reasoning-level-tool.md` - the first builtin
  tool, wired to `ReasoningLevelState`.
- `tasks/done/task-v1.6.1-3-memory-write-tools.md` - append/update within
  memory.md and self.md caps.
- `tasks/done/task-v1.6.1-4-docs-and-release-verification.md` - PROJECT.md
  allowlist boundary, config docs, human-run checklist.

## Acceptance criteria

- [x] A builtin tool call flows through the same interception point as
      MCP calls and produces `ToolCallStarted`/`ToolCallFinished` with
      `data_boundary = local` and a correlated `SystemEvent`.
- [x] Builtin tools appear in the Control Center tool list, visibly
      distinct from MCP tools, and can be individually disabled there;
      the MCP module switch does not affect them.
- [x] "Set reasoning to high" by voice changes the level from the next
      accepted turn; the current turn's confirming reply is a normal
      tool round trip; UI reflects the change through the existing
      engine-state events; hotkey and UI paths still work unchanged.
- [x] "Remember this" appends to memory.md within its cap through the
      audited tool path; an over-cap write returns a clear tool error;
      the file remains editable in the v1.5.3 memory panel.
- [x] `PROJECT.md` records the delegation allowlist boundary
      (cross-cutting rule 9) in the same change that introduces
      delegated control.
- [x] `python -m pytest` and Ruff checks are green; voice-path
      verification is a prepared human-run handoff.

## Implementation outcome

- Builtin tools register under reserved provider `builtin` with
  `provider_kind = "builtin"` and `data_boundary = local`.
- The implemented tools are `set_reasoning_level` and `remember`.
  `remember` has explicit `file`, `mode`, and `content` arguments; it covers
  both `memory.md` and `self.md`. Successful `replace` writes keep one
  previous-version backup as `memory.md.bak` or `self.md.bak` and report that
  backup in the tool result.
- Human-run voice/WebView verification is prepared in
  `tasks/done/task-v1.6.1-4-docs-and-release-verification.md`.
- Review follow-up removed the accidental MCP type import from builtin/host
  code by moving `ToolArguments` to the neutral tool result contract.
- Automated verification: `python -m ruff format --check .`,
  `python -m ruff check .`, and `python -m pytest` are green.

## Stop conditions

- Stop if giving builtin tools a home requires restructuring `McpHost`
  beyond extracting registry/dispatcher ownership - a larger tool-host
  redesign is its own story, not a side effect of this one.
- Stop if the dispatcher's client protocol cannot express an in-process
  call without leaking MCP types (`mcp_client` imports) into the builtin
  provider - that is a boundary problem to surface, not to paper over
  with adapter shims.
- Stop if the model reliably mangles memory-write arguments in practice
  (wrong file, garbled content) - that is a tool-shape design question
  for the human, not something to fix by loosening validation.
