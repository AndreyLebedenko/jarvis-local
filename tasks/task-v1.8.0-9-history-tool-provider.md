# Task v1.8.0-9: Native read-only history tool provider

**Status:** Proposed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** tasks v1.8.0-6 through v1.8.0-8.

## Summary

Expose exact search and bounded event/range reads to the model through a
dedicated local `HistoryToolProvider`.

## Context you need

- `src/jarvis/tools/builtin.py`: current provider pattern.
- `src/jarvis/tools/host.py`: multiple in-process `builtin_clients`.
- `src/jarvis/tools/registry.py`, `results.py`, and `interception.py`.
- `src/jarvis/dialog/tool_presentation.py`: shared three-call budget.
- `src/jarvis/core/config.py`: the shared budget is physically stored as
  `settings.mcp.max_tool_calls_per_turn`.
- Task 6 read API and task 7 search API.
- Existing builtin/dispatcher/tool-presentation tests.

## Current boundary

- In scope: provider name reservation, declarations, argument validation,
  bounded result serialization, registration/wiring, and dispatch tests.
- Out of scope: automatic retrieval, context assembly, MCP exposure,
  semantic search, history writes, and tool-budget changes.

## Requirements

- Add a reserved local provider name that an MCP server cannot claim.
- Add a separate `HistoryToolProvider`; do not add history dependencies to
  `BuiltinToolProvider`.
- Register local `provider_kind="builtin"` tools with
  `DataBoundary.LOCAL`:
  - `search_history`;
  - `read_history`;
  - `read_history_ranges`.
- Schemas expose only supported filters and bounded batch shapes.
- Every result includes references, role/source/timestamp provenance, plain
  text, truncation/count metadata, and a concise model-facing summary.
- Validate unknown arguments, invalid references/ranges, and all count/token
  caps before repository work.
- Common search, context inspection, and comparison of several ranges fit
  within the existing three-call loop through batching.
- Reuse `settings.mcp.max_tool_calls_per_turn`; do not add a separate history
  tool-call budget or interpret the existing section name as MCP-only.
- Calls continue through `ToolDispatcher` so existing audit events,
  correlation ids, cancellation, and locality reporting apply.
- No tool writes transcripts, annotations, curated memory, or raw events.

## Acceptance criteria

- [ ] The registry exposes exactly the three history tools under the reserved
      provider.
- [ ] MCP configuration rejects a colliding provider name.
- [ ] Search and batch reads return bounded structured provenance.
- [ ] Invalid input produces a tool error without repository mutation.
- [ ] A search -> surrounding read -> final answer flow fits the existing
      tool budget in a real `ToolAwareDialog` test with fakes.
- [ ] Disabling MCP does not remove local history tools.

## Stop conditions

- Stop if adding a second builtin client changes MCP on/off semantics.
- Stop if useful reads require raising the global call limit before batching
  is implemented and tested.
- Stop if result serialization needs type erasure or exposes raw media bytes.
- Stop if tool-specific query logic starts duplicating the history domain API.

## Verification

- New history-provider tests.
- Existing builtin, host, dispatcher, registry, and presentation tests.
- Ruff checks.
