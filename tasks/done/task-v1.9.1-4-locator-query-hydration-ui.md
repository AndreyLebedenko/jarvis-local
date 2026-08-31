# Task v1.9.1-4: Locator query + canonical hydration + Journal UI surfacing

**Status:** Completed. (2026-08-31; see completion notes below.)
**Story:** `tasks/story-v1.9.1-provenance-aware-indexing.md`.
**Depends on:** task-v1.9.1-3 (the locator FTS table and its lifecycle) and
task-v1.9.1-1 (the descriptor). The index-shape decision from task 3 is a
direct input; do not start until task 3 has landed and its derivative-table
columns are fixed.
**Executor:** Sonnet 5 High. This card turns the task-3 index into a user-
visible capability: query it, resolve the owning event, hydrate the canonical
on-screen text, and surface it in Journal search framed as a heard-phrase
locator. Two things you must NOT do: feed the derivative into automatic
retrieval/model memory, and blend locator scores into the canonical ranking.

## Summary

Add the locator query path over the task-3 derivative FTS: match heard phrases,
return the owning assistant `JournalEventRef`, hydrate its canonical
`event.text`, and present the result tagged as a locator match with the
derivative text used only as a recognition snippet. Wire it into the Journal UI
search path so a user searching a phrase they only heard finds the turn and
sees the canonical answer. Decide, and record, whether the model-facing
`search_history` exposes locator matches at all - defaulting to UI-only unless a
clean, honestly-labeled contract is reachable.

## Why this exists

Task 3 built the index but nothing reads it. This card is where "find a turn by
a phrase you heard" becomes real, while holding the two invariants the whole
story exists to protect: the canonical canvas is authoritative (a locator hit
shows canonical text, not the derivative as fact), and a heard phrase never
gets promoted into memory (cross-cutting rules 1 and 3).

## Required reading before implementing

- `tasks/task-v1.9.1-3-spoken-derivative-locator-index.md` and the derivative
  table it created; note its exact columns and key.
- `src/jarvis/journal/corpus.py` - the canonical `search` method and
  `_search_sql`/`_search_where_parts` for the query pattern to mirror; the
  read/hydration methods (`read_event`, `read_events`) for canonical-text
  hydration.
- `src/jarvis/journal/search.py` - `JournalSearchIndex` and `JournalSearchHit`,
  the UI-facing search wrapper. This is the seam where the Journal UI reaches
  search.
- `src/jarvis/app.py` around line 1807 - how `JournalSearchIndex` is
  constructed and wired.
- `src/jarvis/ui/status_console.py` and `src/jarvis/ui/status_console_ui/`
  (`app.js`, `strings.js`) - how Journal search results are requested and
  rendered; find where a hit becomes a UI row, and where the mode-3
  "spoken aloud" block already renders (grep `spoken_derivative`).
- `src/jarvis/tools/history.py` - `_serialize_retrieval_candidates` (task 2's
  provenance field) - the reference point if a model-facing locator class is
  taken.
- Cross-cutting rules 1 and 3 in `tasks/roadmap-v1.9-v2.0.md`, and this story's
  "Locator search is UI-first" decision.

## What to build

1. **A locator query method** (on the corpus repository or a small locator
   type - mirror where the canonical `search` lives). Input: a query string
   (plus the same date/session filters the canonical search accepts, only if
   free to add - do not gold-plate). Output: locator hits, each carrying the
   owning assistant `JournalEventRef`, a matched-phrase snippet from the
   derivative (for human recognition), and the score. Reuse the canonical query
   tokenization/prefix logic; do not invent a second query dialect.
2. **Canonical hydration.** For each locator hit, resolve the owning event and
   attach its canonical `event.text` as the authoritative content. The result
   object must make it unmistakable which text is canonical (shown, authored on
   screen) and which is the heard-phrase snippet (recognition only). Tag it with
   the task-1 `SPOKEN_DERIVATIVE` / `LOCATOR_ONLY` provenance so no consumer can
   treat it as a canonical turn.
3. **Journal UI surfacing.** Extend `JournalSearchIndex` (or a sibling method)
   so the Journal UI search can return locator matches distinctly from canonical
   hits, and render them so the user sees: this turn was located by something you
   heard; here is what was shown on screen. Keep the canonical-hit rendering
   unchanged; the locator result is an additional, clearly-labeled kind. Follow
   the existing Journal-search request/render path rather than adding a parallel
   one. Mind the Browser-pane sub-resource caching note in project `CLAUDE.md`
   tooling note 7 when verifying `app.js`/`strings.js` edits.
4. **Model-facing decision (bounded).** Decide whether `search_history` exposes
   locator matches:
   - Default and safe: UI-only. `search_history` continues to return only
     model-eligible surfaces (raw/transcript/annotation); the locator surface's
     `LOCATOR_ONLY` eligibility keeps it out. Record the deferral in this card's
     completion notes with the reason.
   - Only if a clean contract is obvious: expose locator matches as a *distinct*
     result class in `search_history`, explicitly labeled a locator (owning
     event + canonical text hydrated + provenance), never blended into the
     ranked memory candidates, never counted as a lexical/semantic memory hit.
   Do not split the difference: no half-labeled locator leaking into the memory
   candidate list. If in doubt, ship UI-only.
5. **Working-context rendering.** Touch it only if a locator/provenance
   distinction must be visible there. If canonical turns and locator matches
   cannot be rendered without reworking the shared working-context contract,
   that is a story stop condition - raise it, do not absorb it.

## Explicitly out of scope

- No automatic-retrieval eligibility for the derivative - it never enters the
  hybrid candidate feed (`retrieval.py` fusion), only the explicit locator path.
- No cross-surface ranking blend: locator hits are their own result group.
- No change to task-3 storage/lifecycle (if you need a column task 3 did not
  provide, that is a task-3 gap to report, not to patch here ad hoc).
- No mode-3 generation change; no new persisted derivative data.
- No semantic locator.

## Tests

- A query for a phrase present only in a mode-3 derivative returns a locator hit
  whose owning ref is the assistant event, whose canonical text equals that
  event's `event.text`, and whose snippet comes from the derivative.
- The same query returns no *canonical* hit for that phrase (it was never in
  canonical text) - proving the surfaces stay separate end to end.
- A locator hit is tagged locator-only provenance; a consumer checking "is this
  a canonical turn" gets false.
- The derivative never appears among `retrieve()` hybrid candidates for the
  same query (guards the no-auto-promotion invariant).
- If model-facing exposure is taken: a `search_history` locator item is a
  distinct class, carries canonical text + provenance, and does not appear in or
  inflate the lexical/semantic memory counts. If UI-only: a test asserts
  `search_history` returns no locator/derivative content for a derivative-only
  phrase.
- Journal UI search path (mirror existing `test_journal_view_ui.py` style)
  returns and labels a locator match distinctly from a canonical hit.

## Acceptance criteria

- [x] A locator query over the task-3 index returns owning-event refs with
      canonical `event.text` hydrated and a derivative snippet for recognition,
      tagged locator-only provenance.
- [x] Journal UI search reaches locator matches and renders them distinctly from
      canonical hits, with canonical rendering unchanged.
- [x] The derivative is provably absent from automatic retrieval and (unless the
      model-facing class is deliberately taken) from `search_history`; the
      model-facing decision is recorded with its reason.
- [x] No ranking blend: locator hits are a separate group, never merged into or
      counted among canonical/annotation ranked candidates.
- [x] `python -m pytest`, `python -m ruff check`, `python -m ruff format --check`
      green; JS/CSS UI edits verified against the caching note before claiming
      they apply.

## Model-facing decision (recorded 2026-08-31)

**UI-only.** `search_history` does not expose locator matches. Reasons:

- The card's default and safe path. A clean, honestly-labeled model-facing
  locator contract was not reachable within this card's bounds without
  answering two open product questions the card leaves open: in what
  situations should the model know a phrase the user merely heard (it invites
  the model to treat heard content as conversation context), and what would a
  model do with a locator hit that it cannot do with the same event through
  canonical search. Neither has a clean answer today.
- The eligibility contract already encodes the correct state:
  `SPOKEN_DERIVATIVE.eligibility == {LOCATOR_ONLY}` - the derivative keeps
  itself out of `search_history` by construction. No special-casing was
  added or needed.
- Deferral recorded for task 5/6 or a later story. If revisited, the
  contract must be a distinct, non-blended result class labeled a locator,
  never counted as a memory hit (per the story's wording).

## Completion notes (2026-08-31)

- Repository surface: `HistoryLocatorRequest`/`HistoryLocatorHit`/
  `HistoryLocatorResult` + `HistoryCorpusRepository.search_locator`
  (corpus.py). Query mirrors the canonical prefix-token dialect
  (`_to_prefix_match_query`), reuses `_append_date_filter`-style bound
  math; hits hydrate the owning event's canonical `text` from
  `history_corpus_events` and carry the task-1
  `spoken_derivative_provenance_descriptor`. Snippet column: FTS `snippet`
  on the derivative text (column 4), marked tokens for recognition.
- Phrase-lookup semantics (codex green-review finding): an empty or
  date-only locator request matches nothing instead of listing every
  derivative. The locator is a heard-phrase lookup, not a feed.
- Journal UI: `JournalSearchHit` gained `kind` ("canonical"|"locator") and
  `canonical_text`; `JournalSearchIndex.search_locator` mirrors `search`;
  `JournalHistoryService.search_locator` fans out; `/api/journal/search`
  returns locator matches in a separate `locator_hits` group (never mixed
  into `hits` - no ranking blend by construction); app.js renders the
  locator group after canonical groups with its own header, dashed
  per-hit border, "heard-phrase match" tag, and a "shown on screen:"
  canonical line fed by `hit.canonical_text`. Canonical hit rendering is
  byte-unchanged (regression test on the old render signature updated for
  the new one).
- Model-facing: no `search_history` change (see decision above); tests
  assert `search_history` returns zero results/counts for a derivative-only
  phrase, and `HistoryRetrievalService.retrieve()` produces no candidate
  whose text derives from a derivative (no-auto-promotion invariant).
- Working-context rendering: untouched - locator matches never enter the
  working context (they are not model-eligible), so no change was needed
  and the shared contract is intact.
- Red-phase history: b06b6c0-ish (red) + review-fix commit (4 blockers:
  UI-only guard untested, retrieve() invariant missing, transport seam
  untested, snippet assertion could confuse canonical and derivative text;
  1 minor resolved). Green: implementation commit + fix commit (date-only
  locator semantics) + bookkeeping; codex green review LGTM after the fix.
- TDD note: refactor phase had nothing to collapse - the green shape
  already matched the canonical search structure; gates rerun green
  (2366 passed, ruff clean), so no separate refactor commit exists.
- For task 5: candidate cleanup list now includes the UI payload `kind`
  field being a plain string (could be an enum shared with the descriptor
  vocabulary) if task 5 agrees the collapse is worth it.

## Notes for the executor

- The user-visible payoff of the whole story lands here, but the guardrails are
  the point: if a change makes the derivative easier to find at the cost of
  blurring "heard" vs "said", it is wrong even if search feels better. Canonical
  text authoritative; heard phrase is a locator only.
- Prefer UI-only for the model-facing decision unless the clean contract is
  genuinely obvious. Shipping UI-only and recording the deferral fully satisfies
  this card; inventing a model contract that blurs the line does not.
