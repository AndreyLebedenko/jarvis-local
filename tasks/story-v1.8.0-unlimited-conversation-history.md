# Story v1.8.0: Unlimited conversation history

**Status:** Approved.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.8.0 section).
**Created:** 2026-07-29.
**Supersedes:** the separate v1.7.1 near/far consolidation and v1.7.2
retrieval plan. Their settled storage, auditability, locality, and retention
decisions are preserved here.
**Depends on:** completed and released
`tasks/story-v1.7.3-reasoning-mode-prompts.md`. Its effective system-prompt
composition is the prerequisite for replacing the current message assembly.
Re-read its completed cards and resulting code before opening v1.8.0
implementation work.

## User-facing goal

Jarvis can use the complete history of its conversations with the user
without requiring that history to fit in Ollama's context window.

The normal request sent to Ollama contains a bounded working context:
instructions, current task-relevant recent turns, a small set of relevant
past passages, and the current request. When more history is needed, Jarvis
can search and read the local journal through typed read-only tools during
the current turn.

The amount of retained history is limited by local storage and explicit
retention policy, not by `num_ctx`. Increasing the journal size must not
cause ordinary prompt size or prompt-evaluation work to grow linearly.

## Why this replaces the old two-story split

The old roadmap described two mechanisms:

- consolidation produced a searchable near/far archive but did not let the
  model use it;
- retrieval let the model query the archive but did not bound the live
  `ConversationHistory`.

Neither mechanism independently delivered unlimited conversation history.
The user-facing result requires one architecture with three deliberately
separate layers:

1. an immutable conversation record;
2. rebuildable read and search projections over that record;
3. a finite working context assembled for one Ollama turn.

This is one major architectural output even though it is implemented through
multiple ordered task cards.

## Current system facts

- `JournalStore` writes one append-only `events.jsonl` per session. Raw media
  lives beside the log and events reference it by relative path.
- `JournalEvent` already reserves `transcript`, but current voice events store
  empty text and `transcript=None`.
- `JournalSearchIndex` is a rebuildable SQLite FTS5 projection, but it indexes
  assistant text only.
- Live index maintenance is currently owned by `UiTransportServer`, not by a
  journal-domain component.
- `JournalSearchIndex.update_session()` deletes and rebuilds the whole
  session index on every appended event. Repeating that operation through a
  long session is incompatible with the scale goal of this story.
- `ConversationHistory` is an unbounded in-memory list. Every normal request
  resends all retained text turns.
- Media remains current-turn only and never enters retained conversation
  history.
- `ToolAwareDialog` already supports bounded native tool calls. The current
  default is three calls per turn, shared by builtin and MCP tools.
- Ollama returns `prompt_eval_count`, but the normal `LatencyMetrics` surface
  does not retain it.
- Session fork, explicit blank context, interrupted turns, curated
  `memory.md`/`self.md`, current-turn time context, and reasoning-level
  sampling already have verified contracts that this story must preserve.

## Terms

### Raw journal

The per-session JSONL events and their referenced original media. It is the
authoritative record and remains append-only.

### Derived history corpus

Rebuildable local projections beside the raw journal: event references,
search rows, transcripts, annotations, archive metadata, and an optional
semantic index. Derived data may be corrected or rebuilt without changing
raw events.

### Working context

The finite ordered message set assembled for one Ollama request. It is not a
copy of the journal and is not itself long-term storage.

### Explicit retrieval

A model-initiated read through native Jarvis history tools.

### Automatic retrieval

A small deterministic pre-turn search derived from the current request and
recent working context. It adds only bounded, sufficiently relevant passages
and does not require a separate generative Ollama call.

## Boundaries

In scope:

- Efficient append-time indexing and deterministic full rebuild from the raw
  journal.
- Stable provenance references from every derived or retrieved record back
  to its source event or session.
- Exact and prefix search over user text, assistant text, transcripts, and
  annotations, with session, time, role, and source filters.
- Typed read operations for individual events, surrounding events, ordered
  ranges, sessions, and batches of ranges.
- Current-session events becoming readable and searchable without waiting
  for session close or opening the Journal UI.
- Local voice transcription, auditable session annotations, and explicit
  near/far consolidation.
- A dedicated native history tool provider over the same domain read API.
- A bounded working-context assembler with measured room for the answer,
  reasoning, tool results, and forced-final pass.
- Bounded automatic retrieval plus iterative explicit retrieval.
- Context, prompt-token, retrieval-latency, and index-health observability.
- A measured gate for Russian-language semantic retrieval.

Out of scope:

- An MCP server, MCP adapter, or MCP-specific history API.
- Cloud storage, cloud inference, cloud embeddings, or any other external
  history service.
- A general active-task planner, autonomous initiative, proactive reminders,
  or an agent scheduler.
- Graph memory or a general knowledge-graph store.
- Silent model writes to `memory.md`, `self.md`, transcripts, annotations, or
  raw journal events.
- Treating model-written summaries as authoritative replacements for source
  events.
- Retaining old screenshots, camera frames, attachment payloads, or other
  binary media in the model-facing working context.
- Changing Ollama's verified audio/image transport, reasoning `think` values,
  reasoning-trace isolation, or current-turn time-context semantics.
- Dynamically changing `num_ctx` between ordinary and retrieval turns.
- Background consolidation before Jarvis has a separately designed and
  approved idle-work concept.

## Design decisions

### 1. The raw journal remains immutable

Transcripts, annotations, archive state, and search metadata live in a
derived store beside the JSONL logs. Filling the reserved transcript concept
must not rewrite existing JSONL lines. A complete derived store can be
deleted and rebuilt without losing the conversation record.

### 2. The history domain owns indexing

Index lifecycle and append-time updates move out of `UiTransportServer`.
The UI remains a reader of history state, not the component that makes
history searchable.

Appending one event must incrementally add the corresponding derived rows.
Deleting and re-indexing a whole growing session on every append is removed.
Full rebuild remains an explicit startup/recovery operation.

### 3. Every retrieved item has provenance

The first task card defines one stable `JournalEventRef` contract that works
for existing logs and future events without rewriting old sessions. Search
hits, transcripts, annotations, ranges, tool results, and UI editing paths
use that contract consistently.

If no stable reference can support legacy JSONL, incremental updates, and
derived-data correction without destructive migration, task 1 stops for an
owner decision.

### 4. Derived model text is auditable data

Model-written annotations are size-capped, visible and editable in the
Journal surface, and linked to their source session or events. They help
retrieval but do not replace raw text or transcripts.

Retrieved historical content is presented to the model as delimited data
with role, source, timestamp, and reference. Historical user or assistant
text cannot silently become a new system instruction.

Assistant statements are not promoted to confirmed user facts merely
because retrieval found them.

### 5. Consolidation serves the unlimited-history goal

Near sessions retain original replayable media. Far sessions retain full
textual history, transcripts, annotations, provenance, and explicitly
configured reduced media.

The active session is never archived. Consolidation starts only through an
explicit user or UI command. Audio is not automatically removed until its
transcript has been created successfully. Model, GPU, and turn-latency work
must remain predictable and user-visible.

### 6. Jarvis API is the primary interface

History storage and retrieval are exposed first as typed in-process domain
services. The model-facing tools and authenticated Journal UI endpoints call
those services. Neither business logic nor storage semantics live in a tool
handler or HTTP route.

MCP may wrap the same API in a later story; v1.8.0 does not design or ship
that adapter.

### 7. History tools are a separate provider

A dedicated read-only `HistoryToolProvider` owns model-facing history
operations. `BuiltinToolProvider` keeps reasoning, curated-memory writes, and
camera capture; it does not absorb a second storage/search responsibility.

Common search-and-read operations accept bounded batches. The normal path
must work within the existing three-call safety budget. This story does not
raise the global tool-call default without measured evidence that batching is
insufficient. The shared setting currently lives at
`settings.mcp.max_tool_calls_per_turn`; the section name is historical and
does not make the budget MCP-only.

### 8. Working context is deterministic and bounded

The context assembler receives already-sampled turn inputs and produces one
ordered request:

1. the effective system prompt defined by the reasoning-prompt story;
2. a bounded verbatim tail of recent system/user/assistant turns;
3. a bounded block of automatically retrieved historical passages;
4. the existing current-turn time context;
5. the current user request and its current-turn media.

Oldest whole turns are removed first; turns are not split mid-message.
Interrupted and failed-turn notes retain their existing semantics.

The configured Ollama context is never packed to its limit. The policy
reserves explicit capacity for model reasoning, generation, tool
declarations, tool results, media observations, and a forced-final pass.

The exact counting strategy is the task 3 measurement gate. An exact local
tokenizer may be used if it does not introduce a duplicate model-sized
runtime cost. Otherwise the implementation must use a measured conservative
estimator with a documented safety margin and feedback from
`prompt_eval_count`; an unmeasured character guess is not sufficient.

### 9. Automatic and explicit retrieval are complementary

Automatic retrieval keeps recent references discoverable even when the model
does not know that it should search. It is bounded, skips weak matches, and
uses no additional generative request.

Explicit tools let the model refine a query, inspect surrounding events, and
compare several periods. Tool-returned passages remain inside the current
tool loop and are not copied into long-term history as new facts.

### 10. Exact retrieval ships before semantic retrieval

FTS and typed range reads are mandatory. Before selecting a vector store, a
fixed Russian-language evaluation set measures:

- word-form and prefix variation;
- paraphrases;
- exact names, dates, identifiers, and numbers;
- temporal and session filtering;
- relevant-context recall and irrelevant-result rate.

If exact retrieval meets the story's threshold, v1.8.0 completes without a
semantic runtime dependency. If it does not, a gated task evaluates local
embeddings and storage choices. Qdrant is a candidate, not a predetermined
dependency. The existing `.venv-mcp-qdrant` and configured read-only Qdrant
MCP example prove that the external provider path can run; they are not
evidence that Qdrant is the right integrated history-corpus backend and must
not influence the predeclared gate threshold.

### 11. Deletion reaches every derived layer

Explicit session deletion removes its search rows, transcripts, annotations,
archive metadata, and semantic vectors. It does not retroactively mutate an
already dispatched Ollama request. A rebuild cannot resurrect deleted data
because the source session no longer exists.

### 12. Existing context boundaries remain explicit

Starting a blank context still clears the working tail and resamples the
session prompt. Forking still starts a new session with provenance. Neither
operation deletes or rewrites source history, and both remain independent of
whether the old session is later retrieved.

Curated `memory.md` and `self.md` remain a separate, user-auditable prompt
layer. Retrieval never writes them automatically.

## Scope: ordered task cards

Task cards are opened one at a time. Later cards must not be pulled into an
earlier implementation slice.

1. [Stable journal event references](task-v1.8.0-1-journal-event-references.md)
   define one typed provenance identity without changing raw JSONL.
2. [Ollama prompt-token metrics](task-v1.8.0-2-ollama-prompt-metrics.md)
   expose `prompt_eval_count` through existing completion metrics.
3. [Context token-budget spike](task-v1.8.0-3-context-token-budget-spike.md)
   measure estimators against live Ollama and record the selected policy.
4. [Context budget configuration and pure policy](task-v1.8.0-4-context-budget-core.md)
   implement only the approved estimator, validation, and allocations.
5. [Derived history corpus schema and rebuild](task-v1.8.0-5-derived-corpus-rebuild.md)
   create the disposable normalized projection from raw sessions.
6. [Typed history event and range reads](task-v1.8.0-6-history-read-api.md)
   add bounded event, context, range, session, and batch reads.
7. [Exact and prefix history search](task-v1.8.0-7-exact-history-search.md)
   add FTS over raw text while preserving the current Journal search adapter.
8. [History corpus lifecycle and incremental indexing](task-v1.8.0-8-history-corpus-lifecycle.md)
   move startup, append, deletion, and rebuild ownership out of the UI.
9. [Native read-only history tool provider](task-v1.8.0-9-history-tool-provider.md)
   expose bounded search and batch reads within the existing tool-call budget.
10. [Pure recent-history selection policy](task-v1.8.0-10-recent-history-policy.md)
    select complete recent exchanges without changing orchestration.
11. [Working-context assembler](task-v1.8.0-11-working-context-assembler.md)
    compose one bounded request as pure logic.
12. [Working-context orchestration](task-v1.8.0-12-working-context-orchestration.md)
    replace unbounded live replay while preserving existing dialog semantics.
13. [Automatic retrieval selector](task-v1.8.0-13-automatic-retrieval-selector.md)
    rank, deduplicate, and budget passages without I/O.
14. [Automatic retrieval wiring](task-v1.8.0-14-automatic-retrieval-wiring.md)
    retrieve before request assembly with a recent-context fallback.
15. [Transcript overlay store](task-v1.8.0-15-transcript-overlay-store.md)
    persist editable derived transcripts without rewriting journal events.
16. [Historical transcription service](task-v1.8.0-16-transcription-service.md)
    add explicit, non-dialog Ollama transcription with bounded concurrency.
17. [Transcript API, UI, and consumers](task-v1.8.0-17-transcript-api-ui-and-consumers.md)
    expose safe controls and use effective transcripts in search and forks.
18. [Annotation overlay store](task-v1.8.0-18-annotation-overlay-store.md)
    persist bounded session annotations with source references.
19. [Historical annotation generator](task-v1.8.0-19-annotation-generator.md)
    add explicit, source-grounded, non-dialog Ollama generation.
20. [Annotation API, UI, and search](task-v1.8.0-20-annotation-api-ui-and-search.md)
    expose safe controls and typed annotation search hits.
21. [Historical consolidation planner](task-v1.8.0-21-consolidation-planner.md)
    calculate safe near/far media operations without performing them.
22. [Consolidation executor and control](task-v1.8.0-22-consolidation-executor-and-control.md)
    execute explicit plans with restart recovery, API, and UI control.
23. [Semantic retrieval decision gate](task-v1.8.0-23-semantic-retrieval-gate.md)
    evaluate exact retrieval before approving any new local runtime dependency.
24. [Scale, recovery, and end-to-end verification](task-v1.8.0-24-scale-recovery-and-e2e.md)
    test the integrated design on large synthetic history and failure paths.
25. [Documentation and release verification](task-v1.8.0-25-docs-and-release-verification.md)
    reconcile architecture, configuration, user docs, checks, and manual
    handoff.

Task 23 is a mandatory decision gate, not a placeholder semantic
implementation. If its fixed evaluation fails, implementation stops for an
owner decision. The selected semantic design receives its own task card and
becomes a dependency of tasks 24 and 25. Exact/prefix retrieval remains the
offline fallback in either outcome.

## Acceptance criteria

- [ ] Journal size is independent of the Ollama context window and normal
      prompt size remains bounded as the journal grows.
- [ ] Raw JSONL events are never rewritten by transcription, annotation,
      indexing, retrieval, or consolidation.
- [ ] Current and archived user/assistant text is searchable and readable
      with stable provenance.
- [ ] Voice turns become searchable after explicit local transcription.
- [ ] Appending an event updates the derived corpus incrementally without
      rebuilding its whole session.
- [ ] Index startup, incremental update, deletion, and full rebuild do not
      depend on `UiTransportServer` or the Journal view being open.
- [ ] Jarvis can search, inspect surrounding events, and compare bounded
      ranges through native read-only tools.
- [ ] Common retrieval flows complete within the existing bounded tool loop
      through batch operations.
- [ ] Every Ollama request reserves capacity for reasoning, tool results, and
      final generation; context overflow is prevented before dispatch.
- [ ] Automatic retrieval adds only bounded, relevant, provenance-bearing
      passages and performs no separate generative request.
- [ ] Fork, blank-context, interrupted-turn, time-context, reasoning prompt,
      reasoning-trace isolation, and current-turn media behavior remain
      intact.
- [ ] Annotations remain size-capped, visible, editable, and traceable to raw
      source events.
- [ ] The active session is never archived; audio is never automatically
      deleted before successful transcription.
- [ ] Session deletion removes every corresponding derived record and a
      rebuild cannot restore it.
- [ ] Exact retrieval works when the optional semantic path is absent or
      unavailable.
- [ ] Runtime inference, storage, indexing, and optional embeddings are local
      except for separately enabled external tools unrelated to this story.
- [ ] Pure automated tests, Ruff format/check, and the feature end-to-end fake
      backend test are green; hardware/model-dependent verification is handed
      to the human with exact commands.

## End-to-end feature test

A pure functional test creates a large synthetic journal containing an old
fact outside the recent-tail budget, starts a new turn through the real
context/retrieval orchestration with a fake backend, exercises native search
and range reading, and verifies:

- the old fact reaches the final model pass with provenance;
- unrelated old events do not enter the request;
- the working context remains inside its configured budget;
- no source journal event or curated memory file is modified;
- the final answer completes within the tool-call safety bound.

Live transcription, real retrieval quality, and host-resource checks remain
human-run under the project's hardware testing protocol.

## Stop conditions

- Stop if any implementation path requires rewriting raw journal events or
  mutating a closed session as a side effect.
- Stop if stable event provenance requires a destructive migration of
  existing sessions.
- Stop if incremental indexing cannot be separated from the UI lifecycle
  without a wider journal/runtime redesign.
- Stop if token-budget enforcement cannot be made deterministic enough to
  protect generation headroom for Russian prompts and tool results.
- Stop if the bounded working context cannot preserve fork, blank-context,
  interruption, reasoning-prompt, or time-context contracts.
- Stop if normal retrieval requires increasing the global tool-call limit
  before batch operations have been implemented and measured.
- Stop if transcription or annotation work competes with a live user turn in
  a way that makes Ollama latency or VRAM use unpredictable.
- Stop at the semantic gate if local embedding or index candidates have
  non-obvious quality, dependency, persistence, or host-resource trade-offs.
- Stop if automatic retrieval cannot distinguish weak matches well enough to
  avoid regularly polluting the working context.
- Stop if model-written annotations cannot remain visibly traceable to their
  source material.
- Stop if build, test, lint, or manual-handoff tooling fails for reasons
  outside this story's scope.
