# Story v1.8.0: Unlimited conversation history

**Status:** Approved.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.8.0 section).
**Created:** 2026-07-29.
**Revised:** 2026-08-01 after owner review of the exact-first retrieval plan.
**Reworked:** 2026-08-01. Second pass over the hybrid-retrieval revision: a
morphology-aware lexical baseline is required before embeddings are justified,
per-turn query-embedding cost is budgeted on the live path, and the remaining
implementation and release-boundary cards are grouped into three sequenced
releases.
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

"Hybrid" is not a synonym for "embeddings". The Russian retrieval complaint
splits into two problems with different cheapest solutions. Word-form and
prefix variation are a morphology problem, solved by a deterministic local
lemmatizer or stemmer over the lexical layer (a pymorphy3 or
pymorphy-compatible analyzer, a Snowball stemmer, or another measured local
morphology backend, applied at index and query time) with no model, no VRAM,
and no per-turn inference. The specific backend is chosen by the spike against
the runtime, not fixed here; pymorphy2 in particular is avoided because its
`inspect.getargspec` use is incompatible with Python 3.11. Synonyms and
paraphrase are a meaning problem that no lexical method reaches, and only there
is an embedding layer justified. The spike therefore measures a
morphology-aware lexical baseline first, and the embedding layer must earn its
resource and latency cost by the recall it adds over that baseline on
paraphrase, not by the word-form recall a lemmatizer already delivers. The
cheapest hybrid that clears the fixed benchmark wins; a full vector store is a
candidate outcome, not the assumed one.

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

**Annotation overlay store contract (task v1.8.0-21, owner-approved
2026-08-06).** The concrete storage layer for the above:

- **Storage.** A separate `annotation_overlays.db` (schema version 1) beside
  the raw journal, at the same root as the transcript overlay, owned by
  `AnnotationOverlayRepository`. Raw JSONL bytes are never touched; the store is
  a rebuildable derived projection with its own schema-version health check.
- **Anchor.** `AnnotationTarget` is either a whole session (both positions
  `None`) or an inclusive event range `[start, end]` with `start <= end`; a
  single event is `[n, n]`. Range validity leans on append-only contiguity:
  if `end` exists the whole prefix does, so the resolver checks the endpoints
  against the authoritative raw journal (`JournalStoreEventReferenceResolver`),
  never a derived projection. A whole-session target probes position 0.
- **Identity and fields.** Many annotations per session, each with a generated
  `annotation_id`. Fields: `text`, `author`, `source` (`GENERATED` = model,
  `EDITED` = any human change up to a full rewrite - no separate human-authored
  source), `status` (`ACTIVE` default / `DISMISSED`), `metadata` (JSON), and
  created/updated timestamps.
- **Status semantics.** `ACTIVE` is the normal state; the task-22 generator
  writes `ACTIVE` directly, with no mandatory human-approval gate before an
  annotation is usable. `DISMISSED` lets a later UI hide an annotation without
  deleting it, preserving the audit trail; nothing in these cards transitions
  status automatically.
- **Limits.** text 20000 chars, author 200 chars, at most 200 annotations per
  session, metadata at most 32 keys and 4000 serialized chars. These are
  internal store bounds, tunable, and independent of `num_ctx`.
- **Operations.** `add`, `update` (edit text/status/source/metadata, keeps
  `created_at`), `read` by id, `read_session_annotations` (insertion order),
  `delete` by id, `delete_session`, `rebuild`, `count`. `update` stays in this
  card because editability is part of this decision; UI controls do not.
- **Lifecycle.** `AnnotationHistoryProjection` is registered in
  `HistoryProjectionLifecycle`; its `project_event` is a no-op (annotations are
  written explicitly, not derived from an appended raw event), and session
  deletion fans out to the overlay through `JournalHistoryService`.
- **Out of scope for task 21.** Model generation (task 22); the typed
  retrieval seam that keeps `annotation_id`/target/metadata traceable, API, and
  UI (task 23); consolidation. The store deliberately exposes no
  text-only retrieval resolver, so task 23 can design a provenance-preserving
  retrieval contract rather than inherit a lossy one.

**Annotation generator contract (task v1.8.0-22, owner-approved 2026-08-07).**
Explicit, source-grounded, non-dialog generation over the store above:

- **Service.** `AnnotationGenerationService` mirrors the transcription service
  (task 19): a whole-session or event-range target is read through the history
  read API (`HistoryCorpusRepository`), the model summarizes only the cited
  material, and a `GENERATED` overlay is written anchored to that target. No
  `ResponseToken`; a bounded semaphore keeps it competing predictably with a
  live turn; model/reasoning/options are audited from the real payload and
  stored in the annotation's metadata.
- **Target.** Whole session (its full event span is read, but stored as a
  whole-session target so it stays "the session", not a frozen range) or an
  inclusive event range. Whole session is the natural default for a UI.
- **Structural grounding.** Only the cited events reach the prompt, and the
  stored target is exactly the summarized material - grounding is by
  construction, not just instruction.
- **Bounds (predictable live-turn competition).** `max_source_events` (<=200),
  `max_source_chars` (default 24000; raw event text has no per-event cap, so the
  total source is capped and oversize is rejected *before* the model),
  `max_annotation_chars`. Config `[history.annotation]`.
- **Reasoning.** Configurable via `ReasoningLevel` (off/low/medium/high),
  default **off**. A live A/B (2026-08-07, `gemma4:12b-it-qat`) showed `high`
  added no faithfulness on objective traps at ~5x latency. Reasoning trace is
  never read into the annotation.
- **Attribution is an instruction lever, not a format one.** The default
  instruction is Russian (so Russian conversations summarize in Russian) and
  carries an explicit attribution clause. A 24-cell live A/B showed the
  "assistant claim flattened into a user fact" failure (decision 5) was
  Russian+base-instruction specific; a JSONL source format did not fix it and
  cost more tokens, while the attribution clause did (0/3). `format_source_block`
  therefore keeps its delimited label block. The hard guarantee stays
  downstream: annotations are surfaced as `GENERATED`/author/target-anchored
  derived data, never raw user fact (finalized by task 23).
- **Out of scope for task 22.** Automatic scheduler, UI, retrieval-projection
  integration, and consolidation.

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

Automatic retrieval runs on the live turn, so its added cost is a hot-path
concern, not only an indexing concern. When the approved backend uses
embeddings, the automatic path embeds the current query on every eligible
turn, which is a model forward pass competing with Ollama for VRAM before the
main generation. This cost has a measured per-turn budget defined by the
spike. If a turn's semantic retrieval cannot complete within that budget, the
automatic path degrades to lexical-only retrieval for that turn rather than
delaying generation; degradation is a bounded-time decision, not only a
projection-unavailable decision. Explicit tool retrieval, which the model
invokes deliberately, is not held to the same per-turn budget.

### 11. Hybrid retrieval is selected before retrieval consumers

FTS and typed range reads are mandatory but insufficient as the only
retrieval signal. Before model-facing history tools, automatic retrieval, or
working-context wiring consume history search, the story must choose and
measure a local hybrid retrieval design.

The chosen design is the cheapest one that clears the fixed benchmark. A
morphology-aware lexical baseline (lemmatized or stemmed FTS) is measured
before any embedding layer, and an embedding or vector layer is added only for
the paraphrase and synonym gap it demonstrably closes over that baseline. The
approved "hybrid" may be lemmatized-lexical plus a light semantic reranker
rather than a full vector store, if that clears the threshold. A reranker
counts as semantic hot-path work under the same per-turn latency and VRAM
budget as query embedding, unless it is measured to run offline or at index
time, or within a bounded CPU cost over a small candidate set on the live
path.

The candidate decision must cover:

- a morphology-aware lexical baseline (lemmatizer/stemmer choice) and its
  standalone benchmark result, measured before embeddings;
- semantic passage shape and source-reference granularity;
- embedding or semantic-model choice, installation, and configuration, with
  its incremental benchmark gain over the lexical baseline;
- local persistence format and rebuild strategy;
- append-time update and deletion behavior;
- interaction with exact/prefix FTS, filters, ranking, and deduplication;
- disk, RAM, VRAM, and startup behavior on the owner's Windows host;
- per-turn query-embedding cost on the live path, and whether the embedding
  model is kept resident (VRAM cost) or loaded per query (latency cost);
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

8. [Local hybrid retrieval design spike](done/task-v1.8.0-8-hybrid-retrieval-design-spike.md)
   compare candidate local semantic/hybrid backends and choose one with owner
   approval before any retrieval consumer is wired. Completed: pymorphy3 + e5-large-instruct
   (embeddinggemma fallback) + relative gate; see `PROJECT.md`.
9. [History projection lifecycle and incremental indexing](task-v1.8.0-9-history-projection-lifecycle.md)
   move startup, append, deletion, and rebuild ownership for corpus, lexical,
   and semantic projections out of the UI.
10. [Semantic passage and index store](done/task-v1.8.0-10-semantic-passage-index-store.md)
    persist rebuildable source-grounded semantic passages/vectors for the
    selected backend.
11. [Hybrid retrieval domain API and quality gate](done/task-v1.8.0-11-hybrid-retrieval-api-quality-gate.md)
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
27. [Final integrated scale, recovery, and e2e](task-v1.8.0-27-scale-recovery-and-e2e.md)
    test the fully integrated design (through consolidation) on large synthetic
    history and failure paths. v1.8.2 boundary.
28. [Final documentation and release verification](task-v1.8.0-28-docs-and-release-verification.md)
    reconcile architecture, configuration, user docs, checks, and manual
    handoff over the whole story. v1.8.2 boundary.

Release-boundary cards, out of numeric sequence because committed cards 8-28
are not renumbered (execution order is set by the release phasing section and
each card's dependencies):

29. [v1.8.0 core release verification and docs](task-v1.8.0-29-core-release-verification.md)
    close the v1.8.0 text-history core (cards 8-17) with core-scoped scale,
    recovery, e2e, and docs.
30. [v1.8.1 voice and annotation release verification and docs](task-v1.8.0-30-voice-annotation-release-verification.md)
    close the v1.8.1 slice (cards 18-23, 26) with scoped scale, e2e, and docs.

The old task 7a exact retrieval quality gate is replaced by task 8 and task
11 in this revision. Exact/prefix retrieval is still tested and preserved,
but it is no longer allowed to decide whether semantic retrieval exists; the
story now requires a local hybrid retrieval surface before downstream
retrieval consumers are designed.

## Release phasing

Cards 8-28 define the implementation arc; cards 29-30 close intermediate
releases. Together they are one architecture but not one release. They ship in
three sequenced releases so the headline user-facing result lands and gets
real-journal exposure before the heavier media subsystems are built. Cards are
not renumbered; each is assigned to a release below. The cards keep their
one-at-a-time ordering within a release.

### v1.8.0 - Unlimited text-history core (cards 8-17)

Delivers the core of the goal for text history: prompt cost decoupled from
journal size, plus memory-like hybrid retrieval over existing user and
assistant text. It is the smallest slice that makes the text-history goal
true; the complete conversation history goal is only fully met once voice is
retrievable in v1.8.1. It includes the hybrid design spike, projection
lifecycle, semantic passage store, hybrid API and quality gate, the history
tool provider, recent-history selection, the working-context assembler and
orchestration, and automatic retrieval.

Voice turns remain non-retrievable in this release; that is a preexisting gap
(voice events already store empty text today), not a regression this release
introduces, and it is closed in v1.8.1. This release closes with card 29
(core-scoped scale, recovery, e2e, and docs) over the v1.8.0 criteria group
below.

### v1.8.1 - Voice and annotation retrieval (cards 18-23, 26)

Makes voice turns retrievable through explicit local transcription and adds
auditable, source-grounded session annotations, then reruns the fixed
retrieval-quality benchmark (card 26) against the expanded text surface. This
release closes with card 30 (v1.8.1-scoped scale, e2e, and docs) over the
v1.8.1 criteria group.

### v1.8.2 - Consolidation and media lifecycle (cards 24-25)

Adds explicit near/far consolidation and the reduced-media lifecycle that
resolves the retention-policy report. It is fully separable from retrieval and
carries the most host-resource risk, so it ships last. This release closes
with cards 27 (final integrated scale, recovery, and e2e) and 28 (final docs
and release verification), which cover the whole story.

### Release-boundary verification cards

Each release closes with its own verification card that is completed and moved
to `tasks/done/` at that boundary, per the task-card workflow. No card is run
repeatedly across releases.

- v1.8.0 closes with card 29 (core scale, recovery, e2e, and docs; depends on
  cards 8-17).
- v1.8.1 closes with card 26 (retrieval-quality regression over the expanded
  text surface) and card 30 (scale, e2e, and docs; depends on cards 18-23 and
  26).
- v1.8.2 closes with cards 27 and 28, the final integrated verification and
  docs over the full story (depends on cards 24-25 and 30).

Cards 29 and 30 sit out of numeric sequence because the committed cards 8-28
are not renumbered; execution order is defined by this phasing section and by
each card's declared dependencies, not by card number. When v1.8.0 ships, the
later phases may be promoted to their own story cards if that is cleaner for
tracking; the architecture and decisions above stay shared.

## Acceptance criteria

Criteria are grouped by release. A release is done when its own group and the
shared invariants hold for the code shipped in it.

### Shared invariants (must hold at every release boundary)

- [ ] Raw JSONL events are never rewritten by transcription, annotation,
      indexing, retrieval, or consolidation.
- [ ] Session deletion removes every derived record that exists in the shipped
      release, and a rebuild cannot restore it.
- [ ] Runtime inference, storage, indexing, embeddings, and retrieval are
      local except for separately enabled external tools unrelated to this
      story.
- [ ] Pure automated tests, Ruff format/check, and the release's end-to-end
      fake backend slice are green; hardware/model-dependent verification is
      handed to the human with exact commands.

### v1.8.0 - Unlimited history core (cards 8-17)

- [ ] Journal size is independent of the Ollama context window and normal
      prompt size remains bounded as the journal grows.
- [ ] Current and archived user/assistant text is readable with stable
      provenance.
- [ ] Current and archived user/assistant text is retrievable through the
      approved hybrid retrieval surface.
- [ ] A morphology-aware lexical baseline is measured before embeddings, and
      any embedding layer is justified by its incremental paraphrase and
      synonym gain over that baseline in the recorded benchmark.
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
- [ ] Automatic retrieval's per-turn added latency, including any query
      embedding, has a measured budget and degrades to lexical-only retrieval
      within that budget rather than delaying generation.
- [ ] Exact retrieval works when the semantic path is absent, unavailable, or
      unsuitable for a literal query.
- [ ] The hybrid retrieval decision is made before model-facing history tools,
      automatic retrieval, and working-context wiring depend on the search
      surface.
- [ ] Fork, blank-context, interrupted-turn, time-context, reasoning prompt,
      reasoning-trace isolation, and current-turn media behavior remain
      intact.

### v1.8.1 - Voice and annotation retrieval (cards 18-23, 26)

- [ ] Voice turns become retrievable after explicit local transcription.
- [ ] Annotations remain size-capped, visible, editable, and traceable to raw
      source events.
- [ ] The fixed retrieval-quality benchmark is rerun after transcripts and
      annotations join the corpus and still meets its predeclared thresholds.

### v1.8.2 - Consolidation and media lifecycle (cards 24-25)

- [ ] The active session is never archived; audio is never automatically
      deleted before successful transcription.
- [ ] Near/far consolidation runs only through an explicit command and keeps
      model, GPU, and turn-latency work predictable and user-visible.

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
- Stop at the hybrid retrieval design spike if a morphology-aware lexical
  baseline is not measured before embeddings, so the embedding layer's cost
  cannot be weighed against its incremental gain.
- Stop if the per-turn query-embedding cost on the live path cannot be bounded
  and cannot degrade to lexical-only retrieval within a measured time budget.
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
