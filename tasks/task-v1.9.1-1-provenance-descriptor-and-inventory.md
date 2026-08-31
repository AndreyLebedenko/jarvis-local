# Task v1.9.1-1: Provenance descriptor module + surface inventory

**Status:** Not started.
**Story:** `tasks/story-v1.9.1-provenance-aware-indexing.md`.
**Executor:** Sonnet 5 High. This card is deliberately closed-ended: it defines
one pure module and rewires nothing. If you find yourself editing a corpus
schema, a projection, or any retrieval output, you have left this card's
boundary - stop (see "Explicitly out of scope").

## Summary

Introduce one typed provenance vocabulary as a pure module and a single total
function that maps every existing text-bearing search surface onto a
descriptor. This is the shared type tasks 2-4 thread through. No consumer is
rewired in this card; nothing changes at runtime. Deliverable is the module,
its tests, and a written surface-inventory table added to this card's
completion notes.

## Why this exists

Provenance is currently carried by scattered signals that each consumer
re-interprets:

- `HistoryCorpusEvent.text_is_transcript` (`src/jarvis/journal/corpus.py`)
  distinguishes a voice transcript overlay from a user's own words.
- `HistoryRetrievalCandidateKind` (`src/jarvis/journal/retrieval.py`)
  distinguishes a raw event from a derived annotation; the annotation carries
  its `AnnotationSource` (`generated`/`edited`) and target.
- The spoken derivative is out-of-band entirely: stored in
  `event.metadata["spoken_derivative"]` and indexed nowhere.

There is no single type that answers, for any passage: what kind of text is
this, what is it derived from, what does it target, and which search surfaces
may see it. This card creates that type. It does not yet make anything use it
beyond its own tests.

## Required reading before implementing

- `tasks/story-v1.9.1-provenance-aware-indexing.md` (design decisions and
  boundaries - especially the eligibility-class axis and the archive-overlay
  note).
- `src/jarvis/journal/corpus.py` - `HistoryCorpusEvent`, `indexed_text`,
  `text_is_transcript`, and how `effective_text` is populated.
- `src/jarvis/journal/retrieval.py` - `HistoryRetrievalCandidateKind`,
  `HistoryRetrievalCandidate`, `AnnotationCandidateIdentity`.
- `src/jarvis/journal/annotation.py` - `AnnotationSource`, `AnnotationTarget`.
- `src/jarvis/journal/archive.py` (module docstring only) - to confirm the
  archive overlay carries no indexable prose.
- `src/jarvis/journal/recorder.py` around `spoken_derivative` - to confirm the
  derivative lives in event metadata and is not text-indexed.

## What to build

A new pure module (proposed `src/jarvis/journal/provenance.py`; confirm no name
clash) exporting:

1. **`ProvenanceSourceKind`** (enum) - what the text *is*:
   `RAW_EVENT`, `TRANSCRIPT`, `ANNOTATION`, `SPOKEN_DERIVATIVE`.
2. **`ProvenanceEligibility`** (enum) - the four search surfaces a source may be
   eligible for: `AUTO_RETRIEVAL`, `MODEL_SEARCH`, `JOURNAL_UI`,
   `LOCATOR_ONLY`. A source maps to a `frozenset` of these.
3. **`ProvenanceTarget`** - the anchor a passage points at: an owning
   `JournalEventRef` for event/transcript/derivative surfaces, or an
   `AnnotationTarget`-shaped session/range for annotations. Reuse the existing
   `JournalEventRef` and `AnnotationTarget` types; do not define a parallel
   range type (contrast `RawTextRange` in `consolidation.py`, which is
   deliberately separate for a different reason). If a single field cannot hold
   both shapes cleanly, model it as two optional fields with a documented
   invariant, mirroring how `AnnotationTarget` already encodes whole-session vs
   range.
4. **`ProvenanceDescriptor`** (frozen dataclass) - `source_kind`,
   `eligibility` (the frozenset), `target`, and a derivation flag distinguishing
   text that IS the canonical turn from text derived from or attached to it
   (proposed boolean `is_canonical` or a small `ProvenanceDerivation` enum -
   pick the simpler that reads clearly at the call sites in task 2). Keep the
   field set minimal: only what tasks 2-4 actually consume. Do not add fields
   "for completeness".
5. **The mapping functions** - total, pure, no I/O:
   - one from a `HistoryCorpusEvent` to a descriptor (raw vs transcript decided
     by `text_is_transcript`), and
   - one from a retrieval annotation identity (`AnnotationCandidateIdentity`)
     to a descriptor, and
   - one that produces the `SPOKEN_DERIVATIVE` descriptor from an owning
     `JournalEventRef` (used by tasks 3-4; defined here so the vocabulary is
     complete, even though no caller exists yet in this card).
   Prefer three small explicit functions over one overloaded one; they have
   different inputs.

Eligibility mapping (this is the contract - encode it, do not re-derive it at
call sites):

- `RAW_EVENT`      -> {AUTO_RETRIEVAL, MODEL_SEARCH, JOURNAL_UI}
- `TRANSCRIPT`     -> {AUTO_RETRIEVAL, MODEL_SEARCH, JOURNAL_UI}
- `ANNOTATION`     -> {AUTO_RETRIEVAL, MODEL_SEARCH, JOURNAL_UI}
- `SPOKEN_DERIVATIVE` -> {LOCATOR_ONLY}

## Explicitly out of scope (do not do these here)

- No change to `corpus.py` schema, tables, or `CURRENT_HISTORY_CORPUS_SCHEMA_VERSION`.
- No new index or FTS table (that is task 3).
- No change to `HistoryRetrievalCandidate`, `_serialize_retrieval_candidates`,
  or any tool output (that is task 2).
- No import of this module by any runtime consumer yet. The only code that
  imports it in this card is its own test. (Wiring is task 2+.)
- No reading of `event.metadata` at runtime, no projection, no lifecycle.

## Tests (pure logic; `python -m pytest`)

New test module (proposed `tests/test_journal_provenance.py`). Cover:

- Each `ProvenanceSourceKind` maps to exactly the eligibility set above.
- A `HistoryCorpusEvent` with non-empty raw `text` -> `RAW_EVENT`, canonical.
- A `HistoryCorpusEvent` whose raw `text` is empty but `effective_text` is a
  transcript (`text_is_transcript` true) -> `TRANSCRIPT`, non-canonical, target
  is the event ref.
- An annotation identity -> `ANNOTATION`, non-canonical, target carries the
  session and (range or whole-session) shape faithfully.
- The derivative-from-ref helper -> `SPOKEN_DERIVATIVE`, `{LOCATOR_ONLY}`,
  non-canonical, target is the owning event ref.
- The functions are total: they never raise on any valid input of their
  declared type. If a helper takes a discriminated input, assert the mapping is
  exhaustive (e.g. a test that iterates all `ProvenanceSourceKind` members
  through the eligibility map).

Each test self-explanatory per the project testing protocol; no shared mutable
fixtures hiding the input under test.

## Acceptance criteria

- [ ] `src/jarvis/journal/provenance.py` exists as a pure module (no sqlite, no
      filesystem, no network, no event-bus imports) exporting the descriptor,
      the two enums, the target type, and the three mapping functions.
- [ ] The eligibility contract above is encoded once, in this module, and unit-
      tested exhaustively.
- [ ] Mapping functions are total and covered for raw/transcript/annotation/
      derivative inputs.
- [ ] Nothing outside the new module and its test changes; `git diff --stat`
      shows only the new module, the new test, and (if needed) an `__init__.py`
      export line.
- [ ] `python -m pytest`, `python -m ruff check`, `python -m ruff format --check`
      all green.
- [ ] This card's completion notes contain the surface-inventory table (below,
      filled in): one row per surface with its source kind, where it is stored
      today, what text is indexed, and its eligibility set - including the
      archive overlay marked non-text / not-indexed.

## Surface inventory (fill in at completion)

| Surface | Stored where | Indexed text today | Source kind | Eligibility |
|---|---|---|---|---|
| Raw user/assistant event | `history_corpus_events.text` / FTS `effective_text` | raw text | RAW_EVENT | auto + model + UI |
| Voice transcript overlay | transcript overlay store -> `effective_text` | transcript when raw empty | TRANSCRIPT | auto + model + UI |
| Annotation (generated/edited) | annotation overlay store + own lexical/semantic index | annotation text | ANNOTATION | auto + model + UI |
| Mode-3 spoken derivative | `event.metadata["spoken_derivative"]` | none today | SPOKEN_DERIVATIVE | locator-only (this story) |
| Archive overlay | `archive_overlays.db` | none (audio-removal outcome metadata, no prose) | n/a (non-text) | not indexed |

## Notes for the executor

- This card ends with a shared type and a green suite, not a feature the user
  can see. That is intended. Resist making it "do something" - its whole value
  is that tasks 2-4 depend on one vocabulary instead of four scattered signals.
- If you believe a fifth text-bearing surface exists that this table misses,
  that is a story-level stop condition: report it, do not extend the module to
  cover it on your own initiative.
