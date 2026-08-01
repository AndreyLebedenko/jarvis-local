# Task v1.8.0-8: Local hybrid retrieval design spike

**Status:** Draft revision for owner review.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** completed tasks v1.8.0-1 through v1.8.0-7.

## Summary

Choose the local semantic or hybrid retrieval architecture before any
model-facing history consumer is wired.

This is a decision spike, not implementation. It exists because exact/prefix
FTS is the lexical fallback and provenance aid, not the memory engine.

## Current boundary

In scope: compare candidate local retrieval backends, passage shape,
embedding/model options, persistence, lifecycle, resource use, quality gates,
and owner decision.

Out of scope: production vector storage, tool provider, automatic retrieval,
working context, transcripts, annotations, consolidation, and UI.

## Requirements

- Evaluate at least two local semantic/hybrid options, including whether a
  no-server embedded store is sufficient and whether Qdrant is justified.
- Treat the existing `.venv-mcp-qdrant` and read-only Qdrant MCP example as
  provider-path evidence only, not as backend selection evidence.
- Define passage granularity and how each passage maps back to
  `JournalEventRef` or bounded event ranges.
- Define how lexical FTS and semantic candidates combine with filters,
  ranking, deduplication, and read-back.
- Define installation and configuration requirements for the embedding model
  and index store.
- Estimate disk, RAM, VRAM, startup, rebuild, append, and query costs on the
  owner's Windows host.
- Define deterministic pure tests and human-run measurement commands.
- Define the fixed early hybrid retrieval quality benchmark and thresholds
  before implementation sees results.
- Record the selected design and rejected alternatives in `PROJECT.md`.

## Acceptance criteria

- [ ] The owner-approved backend is named explicitly.
- [ ] Exact/prefix retrieval remains the offline literal fallback.
- [ ] Every semantic candidate has stable source provenance.
- [ ] The design covers rebuild, append, deletion, and unavailable-backend
      behavior.
- [ ] Quality thresholds and labels are predeclared.
- [ ] Resource and locality trade-offs are explicit.

## Stop conditions

- Stop if backend candidates have non-obvious quality, dependency,
  persistence, or host-resource trade-offs requiring owner choice.
- Stop if a candidate requires network access at runtime.
- Stop if a candidate cannot preserve deletion and rebuild semantics.
- Stop if the semantic layer would expose vector hits as facts without typed
  read-back.

## Verification

- Spike notes in `PROJECT.md`.
- Any small pure probes needed for candidate inspection.
- Human-run commands for host-resource measurements when needed.
