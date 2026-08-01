# Task v1.8.0-12: Native read-only history tool provider

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-11.

## Summary

Expose bounded hybrid search and event/range reads to the model through a
dedicated local `HistoryToolProvider`.

## Current boundary

In scope: provider name reservation, declarations, schemas, argument
validation, bounded result serialization, registration, wiring, and dispatch
tests.

Out of scope: automatic retrieval, context assembly, MCP exposure, history
writes, backend selection, and tool-budget changes.

## Requirements

- Add a reserved local provider name that an MCP server cannot claim.
- Add a separate `HistoryToolProvider`; do not add history dependencies to
  `BuiltinToolProvider`.
- Register local `provider_kind="builtin"` tools with `DataBoundary.LOCAL`:
  `search_history`, `read_history`, and `read_history_ranges`.
- Search tools consume the approved hybrid retrieval domain API.
- Every result includes references, role/source/timestamp provenance, plain
  source-grounded text, truncation/count metadata, and a concise summary.
- Validate unknown arguments, invalid references/ranges, and count/token caps
  before repository work.
- Common search, context inspection, and comparison flows fit within the
  existing three-call loop through batching.
- Calls continue through `ToolDispatcher` so audit events, correlation ids,
  cancellation, and locality reporting apply.
- No tool writes transcripts, annotations, curated memory, or raw events.

## Acceptance criteria

- [ ] The registry exposes exactly the three history tools under the reserved
      provider.
- [ ] MCP configuration rejects a colliding provider name.
- [ ] Hybrid search and batch reads return bounded structured provenance.
- [ ] Invalid input produces a tool error without repository mutation.
- [ ] Search -> surrounding read -> final answer fits the existing tool
      budget in a `ToolAwareDialog` test with fakes.
- [ ] Disabling MCP does not remove local history tools.

## Stop conditions

- Stop if adding a second builtin client changes MCP on/off semantics.
- Stop if useful reads require raising the global call limit before batching.
- Stop if result serialization needs type erasure or exposes raw media bytes.
- Stop if tool-specific query logic duplicates the domain API.

## Verification

- New history-provider tests.
- Existing builtin, host, dispatcher, registry, and presentation tests.
- `python -m pytest`
- Ruff checks.
