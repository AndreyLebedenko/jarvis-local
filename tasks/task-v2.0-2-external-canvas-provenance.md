# Task v2.0-2: External canvas provenance and journal shape

**Status:** Not started.
**Story:** `tasks/story-v2.0-mcp-voice-guide.md`.
**Depends on:** nothing in code (independent of task 1). Read the story's
design decisions first.
**Executor:** the story's executor profile. This card defines how an external
answer is stored and what every read path may do with it. It adds no queue,
no model call, no server, and no UI. If you find yourself touching
`Orchestrator`, TTS, or `status_console_ui/`, you have left this card - stop.

## Summary

An external canvas is journaled as one event: `role="assistant"`,
`source="mcp_canvas"`, `event.text` = the canvas. This card:

- adds `ProvenanceSourceKind.EXTERNAL_CANVAS` with
  `{MODEL_SEARCH, JOURNAL_UI}`;
- adds a recorder method for the event;
- makes every read path that would treat an assistant event as Jarvis's own
  claim honor the new kind: automatic retrieval, annotations, fork,
  `search_history`, and `read_history`.

## Why this exists

Resolved question 1 (owner, 2026-09-30): an external answer is searchable by
the model and in the Journal, but never fed into automatic retrieval, and the
model must never mistake it for its own past answer. Journal role `assistant`
was chosen (story design decisions) so replay, the derivative locator index,
and Journal rendering work unchanged. The price is that the "not Jarvis's own
claim" identity must come from provenance everywhere it matters.

Facts found while writing this card (verify them before relying on them):

- **Automatic retrieval already excludes the event, but only by accident of a
  default.** `build_automatic_retrieval_request()` defaults
  `sources=("text",)` (`_DEFAULT_SOURCES`,
  `src/jarvis/history/automatic_retrieval.py`), and
  `Orchestrator._resolve_automatic_retrieval()` (`src/jarvis/app.py`) does
  not override it. Both the lexical and the semantic leg honor that filter
  (`corpus.py` `_append_in_filter(..., "source", ...)`, `semantic.py` row
  source check). So `mcp_canvas` events never enter automatic retrieval
  today, but nothing states that as a contract. PROJECT.md records the same
  mechanism for voice ("Voice is retrievable, but only through explicit
  search").
- **Annotations bypass that filter.**
  `HistoryRetrievalService._annotation_lexical_candidates()` and
  `_annotation_semantic_candidates()` (`src/jarvis/journal/retrieval.py`)
  deliberately do not forward `roles`/`sources`. PROJECT.md: "Annotations
  reach automatic retrieval, unlike voice". An annotation of an `--mcp-mode`
  session would carry external text into automatic retrieval one hop removed.
- **Fork copies `event.role` verbatim.** `build_fork_seed()` /
  `_seed_turn()` (`src/jarvis/journal/fork.py`) would seed a forked local
  dialog with Claude's text as the local model's own assistant turns.
  `_is_excluded_event()` already excludes `source == "context"` and counts it
  in `ForkSeedDropReport.excluded_events`.

## Required reading before implementing

- `src/jarvis/journal/provenance.py` (the whole module and its eligibility
  table) and `tasks/done/task-v1.9.1-1-provenance-descriptor-and-inventory.md`.
- `src/jarvis/journal/recorder.py`: `record_assistant()` and its metadata
  comments (why derivative flags are not folded into `outcome`).
- `src/jarvis/journal/retrieval.py`: `HistoryRetrievalService.retrieve()`,
  `_build_annotation_candidate`, `_event_candidate`, `_annotation_candidate`.
- `src/jarvis/history/automatic_retrieval.py`:
  `select_automatic_retrieval_passages()`.
- `src/jarvis/journal/fork.py`.
- `src/jarvis/tools/history.py`: `_serialize_retrieval_candidates`,
  `_serialize_events`, and the `search_history` / `read_history` tool
  descriptions.
- `PROJECT.md`, sections "Architecture v1.9.1 (provenance-aware indexing ...)"
  and the v1.8.0 automatic-retrieval findings quoted above.

## What to build

1. **Provenance kinds.** In `provenance.py`:
   - `EXTERNAL_CANVAS = "external_canvas"` with eligibility
     `{MODEL_SEARCH, JOURNAL_UI}`, `is_canonical=True`. It is the canonical
     text of its event, just not authored by Jarvis;
   - `EXTERNAL_ANNOTATION = "external_annotation"` with the same eligibility,
     for any annotation whose target session contains an `mcp_canvas` event.
     Eligibility is encoded only on the enum (v1.9.1 invariant), so the
     exclusion needs its own kind; it cannot be a flag on `ANNOTATION`;
   - `provenance_descriptor_from_corpus_event()` maps
     `source == "mcp_canvas"` to `EXTERNAL_CANVAS`. The source string is a
     module constant shared with the recorder, not a repeated literal.
2. **Recorder method.** `JournalRecorder.record_external_canvas(...)` writes
   one `role="assistant"`, `source="mcp_canvas"` event. Metadata:
   - `caller`: `{name, version, transport_session_id}` from MCP `clientInfo`
     and the transport session. Every field is nullable; a caller that sends
     none is still recorded;
   - `speech_origin`: `"derivative"` | `"verbatim"` | `"caller"`;
   - `speech_status`: `"spoken"` | `"muted"` | `"interrupted"` | `"skipped"` |
     `"failed"`. `muted` means the speech was produced and stored but not
     played, because the global TTS switch was off (replay can play it later).
     Not folded into `outcome`, for the reason `record_assistant()` already
     documents: the canvas itself is complete regardless of what happened to
     its speech;
   - `guidance` when given;
   - `spoken_derivative` (the reused existing key) for the `derivative` and
     `caller` origins, plus `spoken_derivative_truncated` when the guide pass
     hit its length cap. No derivative for `verbatim` (it would duplicate the
     canonical text in the locator index).

   Use typed values (enums or literals) for origin and status, not free
   strings.
3. **One chokepoint for automatic retrieval.**
   `select_automatic_retrieval_passages()` drops every candidate whose
   `provenance.eligibility` lacks `AUTO_RETRIEVAL`. It does so before
   `candidate_limit` slicing, so excluded candidates do not use up slots, and
   counts them in a new `skipped_ineligible_count`. Keep the `("text",)`
   source default. It is a separate, older decision (voice exclusion) and
   stays a pre-filter; the chokepoint is what makes the contract hold for
   annotations and any future source.
4. **Annotation candidates learn their target's nature.** When building an
   annotation candidate, decide `ANNOTATION` vs `EXTERNAL_ANNOTATION` by
   whether the target session contains an `mcp_canvas` event. Query the
   corpus once per session per `retrieve()` call (cache within the call).
   `--mcp-mode` sessions contain only `mcp_canvas` events and normal sessions
   never do (single instance, one journal session per run), so a
   session-level check is exact.
5. **Fork.** Add `source == "mcp_canvas"` to `_is_excluded_event()` in
   `fork.py`, so such events are counted in `excluded_events` and never seeded
   as the local model's turns. Forking an `--mcp-mode` session therefore
   produces an empty seed with an honest drop report. This reuses the existing
   exclusion mechanism instead of inventing a labeled seed-turn shape. Record
   that reason in the completion notes.
6. **Model-facing labels.** `search_history` result items for
   `EXTERNAL_CANVAS` / `EXTERNAL_ANNOTATION` carry the descriptor's
   `source_kind` (already emitted through the v1.9.1 `provenance` field) and
   the caller name. `read_history` event serialization marks `mcp_canvas`
   events the same way. Update both tool descriptions so the model is told
   that an external answer is another assistant's text the user was shown,
   not its own past answer. The existing `role` value stays; the label is
   additive.

## Explicitly out of scope

- No queue, worker, prompt, or TTS (task 3).
- No new index and no corpus schema change. The corpus already stores
  `source` on both the records table and `history_corpus_event_fts`; if that
  is not enough, see Stop conditions.
- No Journal UI rendering (task 6).
- No change to how `ANNOTATION`, `RAW_EVENT`, `TRANSCRIPT`, or
  `SPOKEN_DERIVATIVE` behave.

## Tests

Extend existing suites; do not fork parallel ones:

- `tests/test_journal_provenance.py`: `source="mcp_canvas"` maps to
  `EXTERNAL_CANVAS`, canonical, eligibility `{MODEL_SEARCH, JOURNAL_UI}`; both
  new kinds lack `AUTO_RETRIEVAL`; the eligibility table stays total over the
  enum.
- `tests/test_journal.py` (or the recorder's existing test home): the recorder
  writes the event shape and metadata for each origin/status combination the
  worker will use; `verbatim` writes no `spoken_derivative`.
- `tests/test_automatic_retrieval.py`: an `EXTERNAL_CANVAS` candidate and an
  `EXTERNAL_ANNOTATION` candidate are dropped and counted; an ineligible
  candidate ahead of eligible ones does not consume `candidate_limit`.
- `tests/test_annotation_retrieval.py` (or `tests/test_history_retrieval.py`):
  an annotation over a session containing an `mcp_canvas` event becomes an
  `EXTERNAL_ANNOTATION` candidate; an annotation over a normal session stays
  `ANNOTATION`. An end-to-end regression mirrors
  `test_annotation_reachable_through_automatic_retrieval_with_typed_framing`:
  the external one does not reach the assembled prompt.
- `tests/test_journal_fork.py`: `mcp_canvas` events are excluded and counted.
- `tests/test_history_tools.py`: `search_history` and `read_history` label
  external items with the kind and the caller; a normal assistant item is
  unchanged.

## Acceptance criteria

- [ ] `EXTERNAL_CANVAS` and `EXTERNAL_ANNOTATION` exist with
      `{MODEL_SEARCH, JOURNAL_UI}` eligibility, encoded only on the enum.
- [ ] The recorder writes one `mcp_canvas` event per call with the metadata
      shape above.
- [ ] Automatic retrieval enforces eligibility at one chokepoint; neither an
      external canvas nor an annotation of one can reach it, asserted end to
      end.
- [ ] Fork never seeds an `mcp_canvas` event as a model turn.
- [ ] `search_history` and `read_history` label external items with the
      caller; the tool descriptions say what they are.
- [ ] Existing retrieval/annotation/fork/tool tests pass unchanged apart from
      additive assertions.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green.

## Stop conditions

- Stop if eligibility cannot be enforced at the single
  `select_automatic_retrieval_passages()` chokepoint (for example, a candidate
  path that reaches the prompt without passing through it). The story's
  fallback is a fourth journal role; that is an architectural change to
  confirm (0.3, 0.4), not to start here.
- Stop if deciding `EXTERNAL_ANNOTATION` needs new persisted data (an
  annotation-store or corpus schema bump) rather than a read-time corpus
  query.
- Stop if the inventory finds another consumer that treats an assistant event
  as Jarvis's own words and is not listed here (grep `role == "assistant"` and
  `"assistant"` role sets under `src/jarvis/`). Report it; do not fold it in
  silently.
