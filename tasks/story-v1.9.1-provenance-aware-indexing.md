# Story v1.9.1: Provenance-aware indexing and search surfaces

**Status:** Done (2026-08-31 - all six task cards landed and verified; the
human-run mode-3 + locator-search handoff,
`tasks/v1.9.1-release-verification-handoff.md`, was owner-executed green
same day: canonical hits render unchanged, derivative-only matches appear
in the separate "Найдено по фразе, которую вы слышали" group with the
"совпадение по услышанной фразе" tag and the canonical line
"Было показано на экране").
**Created:** 2026-08-31
**Updated:** 2026-08-31
**Roadmap:** `tasks/roadmap-v1.9-v2.0.md` (section "v1.9.1 - Provenance-aware
indexing and search surfaces").
**Predecessor:** `story-v1.9.0-response-modes.md` (done) shipped the mode-3
spoken derivative, persisted additively in its assistant event's metadata and
deliberately excluded from the retrieval/memory corpus. This story is where
that exclusion stops being an all-or-nothing silence and becomes a typed,
locator-only surface.
**Executor profile:** task cards in this story are written to be executed by a
Sonnet 5 High agent. They therefore name files, precedents, and boundaries
literally and prefer "mirror this existing pattern" over open-ended design.
Each card states, up front, what it must NOT touch.

## Origin

The v1.8.x arc made the Journal a durable, searchable substrate; v1.9.0 added a
second kind of text - the mode-3 spoken derivative - that lives inside an
assistant event but is not the event's canonical answer. Today the retrieval
and search layers carry provenance only *partially and implicitly*:

- `HistoryCorpusEvent.text_is_transcript` distinguishes a voice turn's
  transcript overlay from the user's own words (corpus schema v2,
  `effective_text`).
- `HistoryRetrievalCandidateKind` distinguishes a raw event from a derived
  annotation, and an annotation carries its `source` (generated/edited) and
  `target`.
- The spoken derivative is excluded by construction: it is written only to
  `event.metadata["spoken_derivative"]`, and the corpus indexes
  `effective_text` (raw or transcript) only, never metadata.

There is no single typed descriptor that says, for any retrievable passage,
*what kind of text this is, what it is derived from, what it targets, and which
search surfaces may see it*. The distinctions exist as scattered booleans and
enums that each consumer re-interprets. And one real surface - the mode-3
derivative - is reachable by neither the model nor the user's own "I remember
hearing that phrase" search, because the only two states available today are
"indexed as ordinary memory" and "invisible".

## User-facing goal

Two outcomes, one visible to the model and one visible to the user:

- **The model can tell what a retrieved passage is.** When `search_history`
  returns a passage, the result says whether it is a raw user/assistant turn, a
  voice transcript, a derived annotation, or a locator match - not just text.
  The model never mistakes derived or heard text for a canonical turn.
- **The user can find a turn by a phrase they heard.** A Journal search for
  words that only ever existed in the spoken derivative of a mode-3 answer
  locates the owning assistant turn and shows the canonical on-screen text as
  the authoritative content. The heard phrase is a *locator*, never promoted
  into the model's memory of what was said.

Nothing about mode-3 generation changes. This story is entirely about the
indexing/search read side plus the metadata already stored.

## Design decisions (proposed here, confirmed by card approval)

- **Provenance becomes one typed descriptor, not scattered flags.** Task 1
  defines a single provenance vocabulary (source kind, derivation, target,
  eligibility class) as a pure module and maps every existing surface onto it.
  The existing `text_is_transcript` / candidate-kind / annotation-source
  signals are re-expressed through it, not duplicated. This is a
  centralization, not a new parallel system.
- **Eligibility is an explicit axis with four classes.** A surface is eligible
  for some subset of: automatic retrieval (the hybrid corpus feed), explicit
  model-facing search (`search_history`), UI-only Journal search, and
  locator-only search. Today these are implied by *where* a surface is indexed;
  this story makes the class a named property the code reads. Raw events and
  transcripts: auto + model-search + UI. Annotations: auto + model-search + UI
  (as today). Spoken derivative: locator-only.
- **The spoken-derivative locator index is lexical-only and physically
  separate from the canonical FTS.** A locator match must never be able to
  surface through the same `MATCH` that returns canonical text, or the
  exclusion becomes a leak. The recommended shape (task 3 confirms it) is a
  second FTS5 table in the existing `history_corpus.db`, keyed to the owning
  assistant `JournalEventRef`, mirroring `history_corpus_event_fts` - kept
  beside the append-only journal as rebuildable derived data (cross-cutting
  rule 5). No embedding/semantic index of the derivative: a semantic index is
  exactly the "promote heard phrasing into memory" move the roadmap forbids.
- **A locator hit returns the owning event and hydrates canonical text.** The
  search result for a locator match is the assistant `JournalEventRef` and the
  canonical `event.text` (the on-screen canvas), tagged as a locator match. The
  derivative text itself may appear only as the matched-phrase snippet for the
  human to recognize what they heard - never as the passage the model is asked
  to treat as fact.
- **Locator search is UI-first; model-facing exposure is a bounded, separate
  decision.** Per cross-cutting rule 3, the Journal UI gets locator search;
  whether `search_history` exposes locator matches to the model is decided in
  task 4 and, if taken, is a distinct result class the model is told is a
  locator, never blended into the ranked memory candidates. If a clean
  model-facing contract is not obvious, task 4 ships UI-only and records the
  deferral - it does not invent one.
- **No cross-surface ranking blend in this story.** Locator matches are a
  separate result group, not merged into the hybrid lexical+semantic ranking of
  canonical/annotation candidates. Blending a locator score against a
  canonical-text score (roadmap open question 3) implies equal epistemic status
  and is deferred; if it turns out to be trivial and clean, task 4 may note it,
  but it is not in scope.
- **Prefer computed-at-read provenance over a schema migration.** The
  descriptor for raw/transcript/annotation surfaces is derivable from data the
  corpus already stores (role, `effective_text`, `text_is_transcript`,
  candidate kind). Task 1/2 compute it at read time and avoid bumping
  `CURRENT_HISTORY_CORPUS_SCHEMA_VERSION`. The only new persisted structure this
  story adds is the locator FTS table (task 3), which is additive and guarded by
  its own `_ensure_schema` path, not a corpus schema-version bump. If persisting
  the descriptor turns out to be genuinely required, that is a stop-and-confirm
  (section 0.3), not a silent migration.

## Boundaries

In scope:

- A pure provenance descriptor module (types + surface->descriptor mapping) and
  its use at the retrieval and model-facing-tool boundaries.
- A lexical, locator-only index over `metadata.spoken_derivative`, its
  projection lifecycle (build/rebuild/incremental/session-delete), and its query
  path returning the owning event with canonical text hydrated.
- Journal UI search reaching locator matches, clearly framed as heard-phrase
  locators distinct from canonical hits.
- Tests at every boundary that changes: retrieval candidates, `search_history`
  output, Journal search, and working-context rendering where provenance is now
  visible.
- Docs: config/PROJECT.md notes only where an architectural decision is
  actually recorded, plus the human-run verification handoff.

Out of scope:

- Any change to the mode-3 generation pipeline. The derivative is already
  stored; this story reads it. (Roadmap boundary.)
- Automatic promotion of spoken derivatives into memory / automatic retrieval.
  (Cross-cutting rule 3; roadmap boundary.)
- A semantic/embedding index of the derivative or of any locator surface.
- Cross-surface ranking that blends locator and canonical scores.
- An "archive summary" text surface. The archive overlay
  (`src/jarvis/journal/archive.py`) stores audio-removal *outcome metadata*
  (bytes reclaimed, per-file KEEP/REMOVE), not indexable prose. The roadmap's
  phrase "archive summaries" refers to this non-text overlay; task 1 records it
  as a non-text-bearing surface and this story builds no summary text for it.
  Producing conversational summaries is a separate, later concern.
- Consolidation planning/execution behavior (`consolidation.py`,
  `consolidation_executor.py`) - untouched.

## Scope (ordered task cards, opened one at a time)

Sizes below are the deliberate segmentation check the owner asked for: the
locator capability - the natural "middle task that balloons" - is split into a
storage half (task 3) and a query/surfacing half (task 4) so no single card
carries both a schema/projection lifecycle and a query+UI+hydration path. Task
boundaries follow design dependencies: task 3's index-shape decision is an
input to task 4, so task 4 is written after task 3 lands.

1. **Provenance descriptor module + surface inventory.** (Size: S-M, pure
   logic, no behavior change.) A new pure module defining the provenance
   vocabulary (source kind, derivation, target, eligibility class) and a total
   function mapping each existing surface (raw event, transcript overlay,
   annotation, spoken derivative; archive overlay recorded as non-text) onto a
   descriptor. Ships with a written inventory table in the card's completion
   notes. No consumer is rewired yet; this is the shared type the next tasks
   thread through. Explicitly forbidden: touching the corpus schema, adding an
   index, changing any retrieval output.

2. **Thread the descriptor through model-facing retrieval + `search_history`.**
   (Size: M.) `HistoryRetrievalCandidate` and `_serialize_retrieval_candidates`
   (`tools/history.py`) express provenance through the task-1 descriptor rather
   than the ad-hoc `kind` + `text_is_transcript` pair - the pair may remain as
   the descriptor's inputs but the serialized result gains an explicit,
   documented provenance field the model reads. No new surfaces, no locator yet:
   this task only makes *existing* candidate provenance explicit and tested.
   Boundary: raw/transcript/annotation only; the derivative is still absent
   here.

3. **Spoken-derivative locator index + projection lifecycle.** (Size: M.)
   Add the lexical, locator-only FTS surface over
   `metadata.spoken_derivative`, physically separate from the canonical FTS,
   inside `history_corpus.db`. Wire it into the same projection lifecycle the
   canonical corpus already has: build on rebuild, incremental
   `project_event`/`update_session_projection`, and `delete_session_projection`.
   Storage and projection only - no query surface, no UI, no model exposure in
   this card. Verified by projecting fixtures and asserting the locator table
   contents and that canonical FTS is byte-unchanged. Boundary: no corpus
   schema-version bump (additive table via `_ensure_schema`); no generation
   change.

4. **Locator query + hydration + Journal UI surfacing.** (Size: M.) The
   locator query path: match heard phrases, return the owning assistant
   `JournalEventRef`, hydrate canonical `event.text`, tag the result as a
   locator match with the derivative snippet only as recognition aid. Wire it
   into the Journal UI search path (`JournalSearchIndex` /
   `status_console`), framed distinctly from canonical hits. Decide model-facing
   exposure per the design decision above: expose through `search_history` as a
   distinct locator result class only if the contract is clean, else ship
   UI-only and record the deferral. Update working-context rendering only where
   a locator/provenance distinction must be visible. Boundary: no ranking blend;
   no automatic-retrieval eligibility for the derivative.

5. **Refactoring + optimization sweep (code and tests).** (Size: S-M.) A
   deliberate consolidation pass so the tails of tasks 1-4 do not accumulate:
   collapse any provenance signal now expressed two ways into the single
   task-1 descriptor, remove transitional shims left while wiring, de-duplicate
   the projection-lifecycle and search-serialization code paths the locator
   surface now shares with the canonical one, and tighten the tests added
   across 1-4 (shared fixtures/helpers for the repeated projection and
   candidate-building setup, no assertion of behavior that a task-1 unit test
   already pins). Strictly behavior-preserving: no new capability, no contract
   change. Verified by the suite staying green with no acceptance-criterion
   regression. Boundary: this is cleanup of *this story's* code and tests only,
   not a licence to refactor unrelated modules.

6. **Docs + release verification.** (Size: S.) PROJECT.md entry for the
   provenance-descriptor and locator-exclusion decisions if they rise to
   architectural facts; user-facing note on heard-phrase Journal search; and the
   human-run verification handoff (a mode-3 turn, then a Journal search for a
   phrase that exists only in the spoken derivative, asserting it locates the
   turn and shows canonical text - a manual/UI check per the Testing protocol).
   Automated logic gates (`pytest`, `ruff check`, `ruff format --check`) green.

## Acceptance criteria

- [x] A single provenance descriptor type exists and every text-bearing search
      surface maps onto it through one total function; the mapping is unit-
      tested and the surface inventory is recorded. (Task 1.)
- [x] `search_history` results carry an explicit, documented provenance field
      that distinguishes raw event / transcript / annotation, verified by tool-
      output tests; no derived or transcript text is presented to the model as a
      canonical turn. (Task 2.)
- [x] A lexical, locator-only index over `metadata.spoken_derivative` exists,
      physically separate from the canonical FTS, and follows the full
      projection lifecycle (build/rebuild/incremental/session-delete); the
      canonical FTS output is unchanged by its presence. (Task 3.)
- [x] A Journal search for a phrase present only in a mode-3 spoken derivative
      returns the owning assistant event with the canonical on-screen text as
      the authoritative content, tagged as a locator match; the derivative is
      never fed into automatic retrieval or model memory. (Task 4.)
- [x] Whether locator matches are exposed to the model through `search_history`
      is decided and recorded; if exposed, they are a distinct locator result
      class the model is told is a locator, never blended into ranked memory
      candidates. (Task 4.)
- [x] A behavior-preserving refactoring pass has collapsed duplicated
      provenance/projection/serialization paths introduced across tasks 1-4 into
      the single descriptor and shared helpers, and consolidated the tests
      those tasks added; the suite stays green with no acceptance-criterion
      regression. (Task 5.)
- [x] `python -m pytest`, `ruff check`, and `ruff format --check` are green for
      all non-hardware logic; the mode-3-then-search verification is a prepared
      human-run handoff with exact commands. (Task 6.)

## Stop conditions

- Stop if expressing raw/transcript/annotation provenance through one
  descriptor cannot be done without persisting new data in the corpus (i.e. it
  is not computable at read time). Persisting it is a corpus schema-version bump
  and migration - an architectural change to confirm (section 0.3), not to slip
  into a "make provenance explicit" task.
- Stop if the locator FTS cannot be kept physically separate from the canonical
  FTS such that a locator phrase can never match through the canonical `MATCH`.
  A shared index that needs post-filtering to hide the derivative is a leak
  risk, not an implementation detail.
- Stop if a clean, honestly-labeled model-facing locator contract is not
  reachable within task 4's bounds; ship the UI-only path and record the
  deferral rather than inventing a contract that blurs locator and memory.
- Stop if surfacing a locator match in the working context cannot be done
  without changing how canonical turns render (i.e. it forces a rework of the
  working-context contract shared with normal turns) - that is a shape problem
  to raise, not to absorb.
- Stop if "review every text-bearing surface" turns up a surface not accounted
  for here (beyond raw event, transcript, annotation, spoken derivative, and the
  non-text archive overlay) - a new indexable surface is new scope to report,
  not to fold in silently.
