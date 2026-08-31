# Task v1.9.1-2: Thread the provenance descriptor through model-facing retrieval

**Status:** Not started.
**Story:** `tasks/story-v1.9.1-provenance-aware-indexing.md`.
**Depends on:** task-v1.9.1-1 (the provenance descriptor module must exist and
be green before this card starts).
**Executor:** Sonnet 5 High. This card makes *existing* candidate provenance
explicit through the task-1 descriptor and surfaces it in `search_history`
output. It adds no new surface and no locator - the spoken derivative is still
absent here. If you find yourself adding an index, reading `event.metadata`, or
touching the corpus schema, you have left this card - stop.

## Summary

Re-express the provenance that retrieval already carries - raw event vs voice
transcript vs derived annotation - through the single `ProvenanceDescriptor`
from task 1, and expose it as one explicit, documented field on each
`search_history` result item. The ad-hoc signals (`HistoryRetrievalCandidateKind`,
`text_is_transcript`, annotation `source`/`target`) remain as the descriptor's
*inputs*, but the serialized model-facing result gains a provenance field the
model reads instead of re-deriving meaning from scattered keys.

## Why this exists

Today a model reading a `search_history` result must infer provenance from a
combination of `kind`, `text_is_transcript`, `role`, and the presence/absence
of `annotation_id`/`target` (see `_serialize_retrieval_candidates` in
`src/jarvis/tools/history.py`). That is exactly the scattered interpretation
task 1 centralized. This card routes the serialization through the descriptor
so "what kind of text is this" is one field, defined once.

## Required reading before implementing

- `tasks/task-v1.9.1-1-provenance-descriptor-and-inventory.md` and the module
  it produced (`src/jarvis/journal/provenance.py`).
- `src/jarvis/journal/retrieval.py` - `HistoryRetrievalCandidate`,
  `_event_candidate`, `_annotation_candidate`, `AnnotationCandidateIdentity`.
- `src/jarvis/tools/history.py` - `_serialize_retrieval_candidates`,
  `_annotation_target_payload`, `_reference_payload`, and the `search_history`
  payload assembly in `_search_history`.
- Existing tests that assert `search_history` output shape (grep tests for
  `search_history`, `text_is_transcript`, `kind`, `source_mode`).

## What to build

1. **Attach the descriptor to each candidate.** In `retrieval.py`, have
   `_event_candidate` and `_annotation_candidate` compute a
   `ProvenanceDescriptor` via the task-1 mapping functions (event: raw vs
   transcript from `event.text_is_transcript`; annotation: from the annotation
   identity). Carry it on `HistoryRetrievalCandidate`. Prefer storing the
   descriptor over storing loose fields; keep `text_is_transcript` only if the
   descriptor cannot fully replace it at the serialization boundary (it should
   be able to - the descriptor encodes source kind).
2. **Serialize one explicit provenance field.** In
   `_serialize_retrieval_candidates`, emit a documented provenance object per
   result item derived from the descriptor, containing at minimum:
   `source_kind` (the enum `.value`), whether the passage is canonical, and its
   target (event ref, or annotation session/range). The existing per-kind
   payload branches (annotation gets `annotation_id`+`target`; event gets
   `reference`+`role`+`text_is_transcript`) stay backward-compatible; the new
   provenance field is additive and authoritative. Do not silently remove keys
   the current tests or the model prompt rely on without confirming; if a key
   becomes redundant, note it for the task-5 cleanup rather than deleting it
   mid-wiring.
3. **Keep the summary line honest.** The `summary` string in `_search_history`
   should not claim provenance it no longer computes ad hoc; if it references
   candidate kinds, source it from the descriptor.

Eligibility is NOT surfaced to the model in this card - `search_history` only
ever returns model-eligible surfaces already, so the eligibility set is an
internal guard, not output. (It becomes load-bearing in task 4 when the locator
surface, which is *not* model-eligible by default, appears.)

## Explicitly out of scope

- No spoken-derivative handling of any kind (task 3-4).
- No new index, no `event.metadata` reads, no corpus schema change.
- No change to ranking, fusion, or which candidates are returned - provenance is
  descriptive, never a filter here.
- No change to `read_history` / `read_history_ranges` event serialization beyond
  what is needed for consistency; if you touch `_serialize_events`, keep it to
  routing through the descriptor, and prefer leaving it for task 5 if it is not
  required for the acceptance criteria.

## Tests

Extend the existing `search_history` / retrieval tool tests (do not fork a
parallel suite):

- A raw user/assistant hit serializes with a provenance field whose
  `source_kind` is `RAW_EVENT` and canonical true.
- A voice-transcript hit (empty raw text, transcript `effective_text`)
  serializes `source_kind` `TRANSCRIPT`, canonical false, target = the event
  ref; the model-facing text is the transcript text, framed as such.
- An annotation hit serializes `source_kind` `ANNOTATION`, canonical false,
  target carrying session and range/whole-session faithfully, alongside the
  existing `annotation_id`.
- The provenance field is present on every result item (no item lacks it).
- A regression test that the set of returned candidates and their order is
  unchanged versus before this card for a fixed fixture (provenance is additive,
  not a filter).

## Acceptance criteria

- [ ] Each `HistoryRetrievalCandidate` carries a `ProvenanceDescriptor` computed
      via the task-1 mapping; retrieval no longer re-derives source kind inline.
- [ ] `search_history` result items include one explicit, documented provenance
      field sourced from the descriptor; raw/transcript/annotation are
      distinguishable from that field alone.
- [ ] No derived or transcript passage is presented as a canonical turn: the
      canonical flag is false for transcript and annotation, true for raw
      events, asserted in tests.
- [ ] Returned-candidate set and order are unchanged for a fixed fixture
      (additive-only change).
- [ ] `python -m pytest`, `python -m ruff check`, `python -m ruff format --check`
      green.

## Notes for the executor

- Backward-compatible-additive is the safe path: add the authoritative
  provenance field, leave now-redundant keys in place, and list them in this
  card's completion notes as cleanup candidates for task 5. Deleting keys while
  four other tasks are still landing is how a regression sneaks in.
