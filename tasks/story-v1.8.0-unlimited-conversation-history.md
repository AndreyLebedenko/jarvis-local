# Story v1.8.0: Unlimited conversation history

**Status:** Draft revision for owner review.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.8.0 section).
**Created:** 2026-07-29.
**Revised:** 2026-08-01 after owner review of the exact-first retrieval plan.
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

The search surface must behave like memory, not only like an exact archive
lookup. A user may ask with different Russian word forms, synonyms, or a
paraphrase of an older fact, and Jarvis should still find plausible source
events with provenance. Exact lookup remains available for names, dates,
identifiers, numbers, and recovery when the semantic layer is unavailable.

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
The user-facing result requires one architecture with four deliberately
separate layers:

1. an immutable conversation record;
2. rebuildable typed read projections over that record;
3. rebuildable lexical and semantic retrieval projections over those same
   stable references;
4. a finite working context assembled for one Ollama turn.

This is one major architectural output even though it is implemented through
multiple ordered task cards.

## Revision note: exact-first was the wrong center

The original v1.8.0 plan treated exact/prefix SQLite FTS as the first
retrieval backend and made semantic or hybrid retrieval conditional on a
later quality gate. That framing created architectural tension: SQL/FTS is
excellent for durable storage, provenance reads, filters, and literal lookup,
but it is not the right center for memory-like retrieval in Russian.

The revised story keeps SQLite-backed corpus projections as the audit and
read backbone, but it does not ask lexical FTS to solve semantic memory.
Hybrid retrieval is now a first-class design goal:

- semantic retrieval produces meaning-based candidate references;
- exact/prefix retrieval produces literal candidate references and remains
  the mandatory offline fallback;
- typed range reads hydrate the selected references back into source text;
- ranking, deduplication, budgeting, and provenance presentation happen above
  both candidate generators.

No vector result is treated as authoritative. The vector index is a
rebuildable derived projection, and every model-facing passage must be read
back from the history corpus or another source-grounded derived layer through
stable provenance.

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
- Tasks v1.8.0-1 through v1.8.0-7 have already established stable event
  references, prompt-token metrics, context-budget policy, a normalized
  history corpus, typed reads, and exact/prefix search. The revised story
  preserves those completed outputs and re-centers the remaining work around
  hybrid retrieval before model-facing consumers are wired.

## Terms

### Raw journal

The per-session JSONL events and their referenced original media. It is the
authoritative record and remains append-only.

### Derived history corpus

Rebuildable local projections beside the raw journal: event references,
search rows, semantic passages, embedding metadata, transcripts, annotations,
archive metadata, and projection health. Derived data may be corrected or
rebuilt without changing raw events.

### Lexical retrieval

Exact and prefix search over indexed text, with session, time, role, and
source filters. It is optimized for literal tokens: names, dates,
identifiers, numbers, and known words.

### Semantic retrieval

Local meaning-based retrieval over source-grounded passages. It may use
embeddings or another approved local semantic representation. It returns
candidate references and scores, not authoritative facts.

### Hybrid retrieval

The retrieval surface consumed by history tools, automatic retrieval, and
working-context assembly. It combines semantic candidates, lexical
candidates, filters, ranking, deduplication, score thresholds, and typed
read-back into provenance-bearing passages.

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
- A local semantic retrieval projection over source-grounded text passages,
  with explicit model/configuration, rebuild, deletion, and health semantics.
- A hybrid retrieval domain API that combines semantic and lexical candidates
  and hydrates selected references through typed reads before model exposure.
- Local voice transcription, auditable session annotations, and explicit
  near/far consolidation.
- A dedicated native history tool provider over the same domain read API.
- A bounded working-context assembler with measured room for the answer,
  reasoning, tool results, and forced-final pass.
- Bounded automatic retrieval plus iterative explicit retrieval.
- Context, prompt-token, retrieval-latency, projection-health, and
  retrieval-quality observability.
- An early measured gate for local hybrid retrieval quality before
  retrieval consumers are wired, plus a late regression check after
  transcripts and annotations expand the retrieval text surface.

Out of scope:

- An MCP server, MCP adapter, or MCP-specific history API.
- Cloud storage, cloud inference, cloud embeddings, or any other external
  history service.
- A general active-task planner, autonomous initiative, proactive reminders,
  or an agent scheduler.
- Graph memory or a general knowledge-graph store.
- Silent model writes to `memory.md`, `self.md`, transcripts, annotations, or
  raw journal events.
- Treating model-written summaries, annotations, or vector hits as
  authoritative replacements for source events.
- Retaining old screenshots, camera frames, attachment payloads, or other
  binary media in the model-facing working context.
- Changing Ollama's verified audio/image transport, reasoning `think` values,
  reasoning-trace isolation, or current-turn time-context semantics.
- Dynamically changing `num_ctx` between ordinary and retrieval turns.
- Background consolidation before Jarvis has a separately designed and
  approved idle-work concept.
- External MCP-provider evidence as a substitute for an integrated local
  history-corpus backend decision.

## Design decisions

### 1. The raw journal remains immutable

Transcripts, annotations, archive state, lexical search metadata, and
semantic retrieval metadata live in derived stores beside the JSONL logs.
Filling the reserved transcript concept must not rewrite existing JSONL
lines. A complete derived store can be deleted and rebuilt without losing the
conversation record.

### 2. SQL is the provenance and read backbone, not the memory engine

SQLite-backed corpus storage owns stable event rows, sort keys, filters,
exact reads, ranges, rebuilds, and deletion. It remains the place where a
retrieval candidate becomes source-grounded data.

The semantic layer must not bypass that backbone. It stores derived
candidate-search data and maps every passage back to source references.
Model-facing content is hydrated through typed reads or source-grounded
derived overlays before it enters a tool result or working context.

### 3. The history domain owns projection lifecycle

Index lifecycle and append-time updates move out of `UiTransportServer`.
The UI remains a reader of history state, not the component that makes
history retrievable.

Appending one event must incrementally update the required derived rows and
candidate projections. Deleting and re-indexing a whole growing session on
every append is removed. Full rebuild remains an explicit startup/recovery
operation.

### 4. Every retrieved item has provenance

`JournalEventRef` is the stable identity for source events. Search hits,
semantic passages, transcripts, annotations, ranges, tool results, and UI
editing paths use that contract consistently.

If a semantic backend cannot preserve source references through rebuild,
incremental update, deletion, and correction without destructive migration,
that backend is rejected for this story.

### 5. Derived model text is auditable data

Model-written annotations are size-capped, visible and editable in the
Journal surface, and linked to their source session or events. They help
retrieval but do not replace raw text or transcripts.

Retrieved historical content is presented to the model as delimited data
with role, source, timestamp, and reference. Historical user or assistant
text cannot silently become a new system instruction.

Assistant statements are not promoted to confirmed user facts merely
because retrieval found them.

### 6. Consolidation serves the unlimited-history goal

Near sessions retain original replayable media. Far sessions retain full
textual history, transcripts, annotations, provenance, and explicitly
configured reduced media.

The active session is never archived. Consolidation starts only through an
explicit user or UI command. Audio is not automatically removed until its
transcript has been created successfully. Model, GPU, and turn-latency work
must remain predictable and user-visible.

### 7. Jarvis API is the primary interface

History storage, reads, and hybrid retrieval are exposed first as typed
in-process domain services. The model-facing tools and authenticated Journal
UI endpoints call those services. Neither business logic nor storage
semantics live in a tool handler or HTTP route.

MCP may wrap the same API in a later story; v1.8.0 does not design or ship
that adapter.

### 8. History tools are a separate provider

A dedicated read-only `HistoryToolProvider` owns model-facing history
operations. `BuiltinToolProvider` keeps reasoning, curated-memory writes, and
camera capture; it does not absorb a second storage/search responsibility.

Common search-and-read operations accept bounded batches. The normal path
must work within the existing three-call safety budget. This story does not
raise the global tool-call default without measured evidence that batching is
insufficient. The shared setting currently lives at
`settings.mcp.max_tool_calls_per_turn`; the section name is historical and
does not make the budget MCP-only.

### 9. Working context is deterministic and bounded

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

### 10. Automatic and explicit retrieval are complementary

Automatic retrieval keeps relevant older references discoverable even when
the model does not know that it should search. It is bounded, skips weak
matches, and uses no additional generative request.

Explicit tools let the model refine a query, inspect surrounding events, and
compare several periods. Tool-returned passages remain inside the current
tool loop and are not copied into long-term history as new facts.

Both paths consume the same approved hybrid retrieval surface. They do not
call the lexical or semantic projection stores directly.

### 11. Hybrid retrieval is selected before retrieval consumers

FTS and typed range reads are mandatory but insufficient as the only
retrieval signal. Before model-facing history tools, automatic retrieval, or
working-context wiring consume history search, the story must choose and
measure a local hybrid retrieval design.

The candidate decision must cover:

- semantic passage shape and source-reference granularity;
- embedding or semantic-model choice, installation, and configuration;
- local persistence format and rebuild strategy;
- append-time update and deletion behavior;
- interaction with exact/prefix FTS, filters, ranking, and deduplication;
- latency, disk, RAM, VRAM, and startup behavior on the owner's Windows host;
- deterministic testability without live Ollama, network access, or hardware;
- quality thresholds for Russian exact terms, morphology, paraphrase, names,
  dates, identifiers, numbers, temporal/session filtering, recall, and
  irrelevant-result rate.

Qdrant is a candidate, not a predetermined dependency. The existing
`.venv-mcp-qdrant` and configured read-only Qdrant MCP example prove that an
external provider path can run; they are not evidence that Qdrant is the
right integrated history-corpus backend.

### 12. Deletion reaches every derived layer

Explicit session deletion removes its corpus rows, lexical search rows,
semantic passages/vectors, transcripts, annotations, archive metadata, and
projection-health records. A rebuild cannot resurrect deleted data because
the source session no longer exists.

Deletion does not retroactively mutate an already dispatched Ollama request.

### 13. Existing context boundaries remain explicit

Starting a blank context still clears the working tail and resamples the
session prompt. Forking still starts a new session with provenance. Neither
operation deletes or rewrites source history, and both remain independent of
whether the old session is later retrieved.

Curated `memory.md` and `self.md` remain a separate, user-auditable prompt
layer. Retrieval never writes them automatically.

## Scope: ordered task cards

Task cards are opened one at a time. Later cards must not be pulled into an
earlier implementation slice.

Completed cards 1-7 stay valid and are not reopened by this story rewrite:

1. [Stable journal event references](done/task-v1.8.0-1-journal-event-references.md)
   define one typed provenance identity without changing raw JSONL.
2. [Ollama prompt-token metrics](done/task-v1.8.0-2-ollama-prompt-metrics.md)
   expose `prompt_eval_count` through existing completion metrics.
3. [Context token-budget spike](done/task-v1.8.0-3-context-token-budget-spike.md)
   measure estimators against live Ollama and record the selected policy.
4. [Context budget configuration and pure policy](done/task-v1.8.0-4-context-budget-core.md)
   implement only the approved estimator, validation, and allocations.
5. [Derived history corpus schema and rebuild](done/task-v1.8.0-5-derived-corpus-rebuild.md)
   create the disposable normalized projection from raw sessions.
6. [Typed history event and range reads](done/task-v1.8.0-6-history-read-api.md)
   add bounded event, context, range, session, and batch reads.
7. [Exact and prefix history search](done/task-v1.8.0-7-exact-history-search.md)
   add FTS over raw text while preserving the current Journal search adapter.

Revised remaining sequence:

8. [Local hybrid retrieval design spike](task-v1.8.0-8-hybrid-retrieval-design-spike.md)
   compare candidate local semantic/hybrid backends and choose one with owner
   approval before any retrieval consumer is wired.
9. [History projection lifecycle and incremental indexing](task-v1.8.0-9-history-projection-lifecycle.md)
   move startup, append, deletion, and rebuild ownership for corpus, lexical,
   and semantic projections out of the UI.
10. [Semantic passage and index store](task-v1.8.0-10-semantic-passage-index-store.md)
    persist rebuildable source-grounded semantic passages/vectors for the
    selected backend.
11. [Hybrid retrieval domain API and quality gate](task-v1.8.0-11-hybrid-retrieval-api-quality-gate.md)
    combine semantic and lexical candidates, hydrate references through typed
    reads, and pass the fixed Russian retrieval benchmark.
12. [Native read-only history tool provider](task-v1.8.0-12-history-tool-provider.md)
    expose bounded hybrid search and batch reads within the existing tool-call
    budget.
13. [Pure recent-history selection policy](task-v1.8.0-13-recent-history-policy.md)
    select complete recent exchanges without changing orchestration.
14. [Working-context assembler](task-v1.8.0-14-working-context-assembler.md)
    compose one bounded request as pure logic.
15. [Working-context orchestration](task-v1.8.0-15-working-context-orchestration.md)
    replace unbounded live replay while preserving existing dialog semantics.
16. [Automatic retrieval selector](task-v1.8.0-16-automatic-retrieval-selector.md)
    rank, deduplicate, and budget passages from the approved hybrid retrieval
    surface without I/O.
17. [Automatic retrieval wiring](task-v1.8.0-17-automatic-retrieval-wiring.md)
    retrieve before request assembly with a recent-context fallback.
18. [Transcript overlay store](task-v1.8.0-18-transcript-overlay-store.md)
    persist editable derived transcripts without rewriting journal events.
19. [Historical transcription service](task-v1.8.0-19-transcription-service.md)
    add explicit, non-dialog Ollama transcription with bounded concurrency.
20. [Transcript API, UI, and retrieval consumers](task-v1.8.0-20-transcript-api-ui-and-consumers.md)
    expose safe controls and include effective transcripts in corpus,
    lexical, and semantic projections.
21. [Annotation overlay store](task-v1.8.0-21-annotation-overlay-store.md)
    persist bounded session annotations with source references.
22. [Historical annotation generator](task-v1.8.0-22-annotation-generator.md)
    add explicit, source-grounded, non-dialog Ollama generation.
23. [Annotation API, UI, and retrieval projections](task-v1.8.0-23-annotation-api-ui-and-retrieval.md)
    expose safe controls and include typed annotation text in retrieval.
24. [Historical consolidation planner](task-v1.8.0-24-consolidation-planner.md)
    calculate safe near/far media operations without performing them.
25. [Consolidation executor and control](task-v1.8.0-25-consolidation-executor-and-control.md)
    execute explicit plans with restart recovery, API, and UI control.
26. [Retrieval quality regression](task-v1.8.0-26-retrieval-quality-regression.md)
    rerun the fixed retrieval-quality benchmark after transcripts and
    annotations join the retrieval corpus.
27. [Scale, recovery, and end-to-end verification](task-v1.8.0-27-scale-recovery-and-e2e.md)
    test the integrated design on large synthetic history and failure paths.
28. [Documentation and release verification](task-v1.8.0-28-docs-and-release-verification.md)
    reconcile architecture, configuration, user docs, checks, and manual
    handoff.

The old task 7a exact retrieval quality gate is replaced by task 8 and task
11 in this revision. Exact/prefix retrieval is still tested and preserved,
but it is no longer allowed to decide whether semantic retrieval exists; the
story now requires a local hybrid retrieval surface before downstream
retrieval consumers are designed.

Existing task-card files numbered 8-25 are stale after this story revision.
They must be rewritten or replaced before implementation continues. Do not
start those cards under their old boundaries.

## Acceptance criteria

- [ ] Journal size is independent of the Ollama context window and normal
      prompt size remains bounded as the journal grows.
- [ ] Raw JSONL events are never rewritten by transcription, annotation,
      indexing, retrieval, or consolidation.
- [ ] Current and archived user/assistant text is readable with stable
      provenance.
- [ ] Current and archived user/assistant text is retrievable through the
      approved hybrid retrieval surface.
- [ ] Voice turns become retrievable after explicit local transcription.
- [ ] Appending an event updates derived corpus, lexical, and semantic
      projections incrementally without rebuilding its whole session.
- [ ] Projection startup, incremental update, deletion, and full rebuild do
      not depend on `UiTransportServer` or the Journal view being open.
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
- [ ] Exact retrieval works when the semantic path is absent, unavailable, or
      unsuitable for a literal query.
- [ ] The hybrid retrieval decision is made before model-facing history tools,
      automatic retrieval, and working-context wiring depend on the search
      surface.
- [ ] Runtime inference, storage, indexing, embeddings, and retrieval are
      local except for separately enabled external tools unrelated to this
      story.
- [ ] Pure automated tests, Ruff format/check, and the feature end-to-end fake
      backend test are green; hardware/model-dependent verification is handed
      to the human with exact commands.

## End-to-end feature test

A pure functional test creates a large synthetic journal containing an old
fact outside the recent-tail budget, starts a new turn through the real
context/retrieval orchestration with a fake backend, exercises native hybrid
search and range reading, and verifies:

- the old fact reaches the final model pass with provenance;
- unrelated old events do not enter the request;
- lexical fallback can retrieve exact identifiers without the semantic layer;
- semantic/hybrid retrieval can retrieve a paraphrased older fact in the
  approved deterministic fake or fixture-backed test mode;
- the working context remains inside its configured budget;
- no source journal event or curated memory file is modified;
- the final answer completes within the tool-call safety bound.

Live transcription, real embedding-model quality, and host-resource checks
remain human-run under the project's hardware testing protocol.

## Stop conditions

- Stop if any implementation path requires rewriting raw journal events or
  mutating a closed session as a side effect.
- Stop if stable event provenance requires a destructive migration of
  existing sessions.
- Stop if incremental projection lifecycle cannot be separated from the UI
  without a wider journal/runtime redesign.
- Stop if token-budget enforcement cannot be made deterministic enough to
  protect generation headroom for Russian prompts and tool results.
- Stop if the bounded working context cannot preserve fork, blank-context,
  interruption, reasoning-prompt, or time-context contracts.
- Stop if normal retrieval requires increasing the global tool-call limit
  before batch operations have been implemented and measured.
- Stop if transcription, annotation, or semantic indexing work competes with
  a live user turn in a way that makes Ollama latency, embedding latency, VRAM,
  or RAM use unpredictable.
- Stop at the hybrid retrieval design spike if local embedding or index
  candidates have non-obvious quality, dependency, persistence, resource, or
  lifecycle trade-offs.
- Stop if the selected semantic backend cannot preserve deletion,
  rebuildability, provenance, and offline exact fallback.
- Stop at the early hybrid retrieval quality gate if the selected candidate
  cannot meet the fixed Russian-language benchmark without weakening
  thresholds after seeing results.
- Stop at the late retrieval regression if transcripts or annotations make
  the final retrieval corpus contradict the recorded retrieval decision.
- Stop if automatic retrieval cannot distinguish weak matches well enough to
  avoid regularly polluting the working context.
- Stop if model-written annotations cannot remain visibly traceable to their
  source material.
- Stop if build, test, lint, or manual-handoff tooling fails for reasons
  outside this story's scope.
