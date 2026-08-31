# Task v1.9.1-5: Refactoring and optimization sweep (code and tests)

**Status:** Completed. (2026-08-31; see completion notes below.)
**Story:** `tasks/story-v1.9.1-provenance-aware-indexing.md`.
**Depends on:** tasks 1-4 all landed. This card runs after the feature is
complete and green, before docs/release (task 6).
**Executor:** Sonnet 5 High. This is a strictly behavior-preserving cleanup of
*this story's own* code and tests. No new capability, no contract change, no
acceptance-criterion movement. If a change alters observable behavior or a
result shape, it does not belong here.

## Summary

Consolidate the tails that tasks 1-4 necessarily leave behind so they do not
accumulate: fold every provenance signal now expressed two ways into the single
task-1 descriptor, delete transitional shims and now-redundant keys that earlier
cards deliberately left in place, de-duplicate the projection-lifecycle and
search-serialization code the locator surface shares with the canonical one, and
tighten the tests added across the story into shared helpers without losing
coverage. The suite stays green throughout with no acceptance-criterion
regression.

## Why this exists

Tasks 2-4 were told to prefer additive, backward-compatible changes and to
*defer* deletions and de-duplication to avoid regressions while multiple cards
were still landing. Those cards record their cleanup candidates in their
completion notes. Without a dedicated closing pass, that debt (redundant
serialization keys, parallel projection code, near-duplicate test setup) becomes
permanent. This card pays it down once, deliberately, at the end.

## Inputs to collect first

Before changing anything, gather the deferred-cleanup notes:

- Read the "cleanup candidates" / completion notes at the end of the task 2, 3,
  and 4 cards (`tasks/done/task-v1.9.1-2-*`, `-3-*`, `-4-*`).
- Grep for the provenance signals to find remaining double-expression:
  `text_is_transcript`, `HistoryRetrievalCandidateKind`, `source_mode`, the
  task-1 descriptor type, and the derivative-FTS helpers.
- Run `python -m pytest` first and record the green baseline (count) so you can
  prove no test was silently dropped rather than consolidated.

## What to do (only where it applies - none of these is mandatory busywork)

1. **Collapse duplicated provenance.** If any consumer still reads
   `text_is_transcript` or a candidate kind directly where the task-1 descriptor
   now carries the same fact, route it through the descriptor and remove the
   redundant field/branch. The descriptor is the single source; loose signals
   that were only its inputs and are no longer read elsewhere go away.
2. **Remove transitional shims and redundant keys.** Delete the now-redundant
   `search_history` result keys that task 2 left in place for compatibility,
   *if and only if* nothing (tests, the model prompt/system text, the UI) still
   depends on them - verify by grep before deleting. Update the tests that
   asserted the transitional shape to assert the consolidated shape.
3. **De-duplicate projection lifecycle.** If the canonical and derivative FTS
   projection/delete paths in `corpus.py` share structure (delete-then-insert
   per event, per-session clear, rebuild iteration), factor the shared shape so
   the two tables cannot drift out of sync through a future one-sided edit. Do
   not change what is projected - only how the two paths share code.
4. **De-duplicate search serialization.** If the locator query path (task 4) and
   the canonical `search`/serialization repeat query-building or hit-shaping,
   share the common piece. Keep the physical separation of the two FTS tables
   intact - shared code must not become a shared index.
5. **Tighten tests.** Consolidate the repeated projection setup and
   candidate-building fixtures the story's tests introduced into shared helpers.
   Remove assertions that merely re-pin what a task-1 unit test already
   guarantees (do not remove the task-1 unit tests themselves). Every behavior
   an acceptance criterion names must still be asserted somewhere after
   consolidation - map each criterion to its surviving test in the completion
   notes.

## Explicitly out of scope

- Any behavior change, result-shape change, or new capability.
- Refactoring modules this story did not touch. If you spot unrelated debt,
  write a bug/issue report per `CLAUDE.md` "How to report an issue" - do not fix
  it here.
- Corpus schema changes, new indexes, new eligibility rules.
- Performance work beyond removing duplicated work already on the path;
  no new caching layers, no algorithmic redesign (that would be behavior/risk,
  not cleanup).

## Tests

- The full suite is green before and after, with the test count accounted for:
  any drop is a consolidation you can point to, never a silent loss of coverage.
- Each story acceptance criterion (1-4) maps to a still-present assertion after
  the sweep; record the mapping in completion notes.
- `python -m ruff check` and `python -m ruff format --check` green.

## Acceptance criteria

- [x] No provenance fact is expressed two ways: consumers read the task-1
      descriptor; loose signals that were only its inputs and are no longer read
      are gone.
- [x] Transitional shims and redundant `search_history` keys from tasks 2-4 are
      removed where provably unused, with their tests updated to the
      consolidated shape.
- [x] Canonical and derivative projection-lifecycle paths share their common
      structure so the two FTS tables cannot silently drift; physical index
      separation is preserved.
- [x] Story tests are consolidated into shared helpers with a criterion->test
      map showing no coverage lost.
- [x] Behavior is unchanged: no story acceptance criterion regresses; result
      shapes change only by the deliberate removal of documented-redundant keys.
- [x] `python -m pytest`, `python -m ruff check`, `python -m ruff format --check`
      green.

## Completion notes (2026-08-31)

Baseline: 2366 passed + 1 skipped before the sweep; 2366 passed + 1 skipped
after (same count, consolidation replaced assertions in place - zero tests
dropped).

What was collapsed:

- `HistoryRetrievalCandidate.text_is_transcript` removed (field, builder
  arguments in `_event_candidate`/`_annotation_candidate`). The one non-test
  consumer, `automatic_retrieval._to_retrieved_history_passage`, now derives
  `RetrievedHistoryPassage.text_is_transcript` from
  `candidate.provenance.source_kind is ProvenanceSourceKind.TRANSCRIPT`.
  The model-facing working-context `"text_is_transcript"` key STAYS (the
  model payload is unchanged - only its source became the descriptor).
- `search_history` event items no longer emit the redundant
  `"text_is_transcript"` key (provenance.source_kind == "transcript" is the
  single signal); annotation items no longer emit the duplicate `target`
  payload (the session/range shape lives only in
  `provenance.target.annotation`); `_annotation_target_payload` removed.
- `journal/__init__.py` exports the task-4 locator types
  (`HistoryLocatorRequest`/`HistoryLocatorHit`/`HistoryLocatorResult`).
- Projection lifecycle: insert and both delete paths in `corpus.py` kept
  as-is (comment only). Codex review concurred: a mechanical helper around
  two intentionally distinct tables would add indirection without reducing
  drift risk; delete-then-insert parity is already enforced by shared
  structure (both FTS deletes sit adjacent to the events delete with
  identical predicates).
- Search serialization: locator helpers already reuse
  `_to_prefix_match_query`, `_append_date_filter`, `_append_in_filter` -
  no further duplication found.
- Test consolidation: per-file fixtures (`_locator_corpus` in
  test_history_corpus.py, `_locator_fixture` in test_journal_search.py)
  already serve all locator tests in their file; assertions that pinned
  `text_is_transcript` were rewritten to predicate on the descriptor (the
  transcript e2e tests in test_consolidation_release_e2e.py and
  test_voice_annotation_release_e2e.py now assert
  `provenance.source_kind is TRANSCRIPT` + `is_canonical is False`);
  `_StaticRetrievalService` kept local to test_journal_search.py (single
  use).

Criterion -> surviving assertion map (story acceptance criteria 1-4):

1. Descriptor + total mapping + inventory (task 1):
   `tests/test_journal_provenance.py` (unchanged task-1 unit tests).
2. `search_history` provenance field distinguishes raw/transcript/annotation:
   `test_search_history_serializes_provenance_for_raw_event` /
   `_for_transcript_event` / `_for_annotation` (test_history_tools.py);
   every-item presence: `test_search_history_provenance_field_is_present_on_
   every_item`.
3. No derived/transcript text presented as canonical:
   `test_search_history_provenance_follows_descriptor_over_legacy_fields`
   (sentinel) + `test_retrieval_returns_transcript_text_source_framed`
   (test_transcript_consumers.py) + `test_locator_query_returns_owning_ref_...`
   (is_canonical False asserted).
4. Locator index physically separate + lifecycle parity (task 3):
   test_history_corpus.py - `test_derivative_only_phrase_is_not_matchable_
   through_canonical_fts`, `test_delete_session_projection_removes_only_...
   derivatives`, `test_project_event_reprojects_derivative_without_duplicates`,
   `test_locator_fts_table_exists_without_schema_version_bump`,
   `test_derivative_projection_keeps_canonical_fts_byte_identical`.
5. Locator query + hydration + UI surfacing (task 4):
   `test_journal_locator_search_returns_labeled_hits_with_canonical_text`,
   `test_journal_search_endpoint_labels_locator_hits_distinctly` (transport).
6. No auto-promotion: `test_derivative_phrase_never_enters_hybrid_retrieval_
   candidates` (test_history_corpus.py) +
   `test_search_history_returns_no_locator_content_for_derivative_phrase`
   (test_journal_search.py).
7. No schema-version bump: `test_locator_fts_table_exists_without_schema_
   version_bump`.

Codex review of the sweep diff: "No findings ... LGTM" (2026-08-31).

## Notes for the executor

- The discipline here is subtraction, not addition. If a change adds code or
  capability, it is probably not this card's work. The win is that the next
  person reads one descriptor and one projection path, not the sediment of four
  incremental cards.
- "Provably unused" means you grepped and looked, not that it seemed unused.
  A removed key that the system prompt or a UI string still references is a
  regression this card exists to prevent, not cause.
