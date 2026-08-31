# Task v1.9.1-6: Docs + release verification

**Status:** Completed. (2026-08-31; see completion notes below.)
**Story:** `tasks/story-v1.9.1-provenance-aware-indexing.md`.
**Depends on:** tasks 1-5 landed (feature complete and cleaned up).
**Executor:** Sonnet 5 High. Documentation and a self-sufficient human-run
handoff. No production logic changes here; if you need one, the story is not
actually done - stop and report.

## Summary

Record the story's architectural decisions where they rise to durable facts,
add the user-facing note for heard-phrase Journal search, and prepare the
human-run verification handoff for the parts that are hardware/UI-manual (a
live mode-3 turn, then a Journal search for a phrase that exists only in the
spoken derivative). Confirm the automated gates are green.

## Required reading before implementing

- `tasks/story-v1.9.1-provenance-aware-indexing.md` - the design decisions, to
  decide which are PROJECT.md-worthy facts vs card-local detail.
- `PROJECT.md` - its existing structure and the "do not re-litigate" fact style,
  plus the runtime-locality and retrieval sections, to place the new facts
  correctly and not duplicate them.
- The task 4 completion notes - the recorded model-facing exposure decision
  (UI-only vs a locator result class), which the docs must state accurately.
- `CLAUDE.md` "Testing protocol" and "Standard task-card workflow" - especially
  the handoff self-sufficiency rule (a handoff must be executable from its own
  text, every hotkey/config key/command named literally with a source
  reference).
- The v1.9.0 release handoff
  (`tasks/done/task-v1.9.0-5-docs-and-release-verification.md`) as the format
  precedent for a self-sufficient handoff.
- `README.md` / `README.ru.md` where Journal search / mode-3 are already
  described, to slot the heard-phrase note consistently in both.

## What to do

1. **PROJECT.md facts (only the durable ones).** Record, in the retrieval/
   indexing area:
   - Provenance is a single typed descriptor; every search surface maps onto it;
     the eligibility axis (auto-retrieval / model-search / journal-UI /
     locator-only).
   - The spoken derivative is locator-only: lexical, physically separate FTS,
     canonical text authoritative, never promoted into automatic retrieval or
     model memory. State the model-facing exposure decision as taken in task 4.
   - The archive overlay is a non-text surface (no indexable prose) - so a
     future reader does not re-open "index archive summaries".
   Keep each to the settled-fact style; do not paste card prose. If a decision
   is genuinely card-local (not an architectural invariant), leave it in the
   card, not PROJECT.md.
2. **User-facing note.** In README (both language files, per project convention)
   describe heard-phrase Journal search: a user can search a phrase they heard
   in a Text+voice answer and land on the turn, seeing the on-screen answer as
   the authoritative content. Keep it short and accurate to what task 4 shipped
   (UI-only vs model-facing).
3. **Human-run verification handoff.** Prepare a self-sufficient handoff (its own
   section or file under `tasks/`) that a runner who has not read the code can
   execute:
   - How to put Jarvis in Text+voice (mode 3): name the mechanism literally
     (the Status-tab response-mode control and the cycling hotkey) with a source
     reference to where its default/binding is defined, per the handoff
     self-sufficiency rule - do not assume a starting mode; state the
     state-independent way to reach mode 3.
   - Produce a mode-3 answer whose spoken derivative contains a phrase unlikely
     to appear in the canonical on-screen text (so the match can only come from
     the derivative).
   - Open the Journal, search that phrase, and assert: the owning turn is found,
     the result is labeled a heard-phrase/locator match, and the canonical
     on-screen text is shown as the authoritative content.
   - If task 4 shipped model-facing exposure, add the step to confirm
     `search_history`'s locator class is labeled and not counted as memory; if
     UI-only, state explicitly that `search_history` must NOT surface the
     derivative, and how to confirm.
   - State any dependency on documentation that is another task's debt
     explicitly rather than crossing it silently (handoff rule); if it cannot be
     made self-sufficient, stop and report (section 0).
4. **Confirm automated gates.** `python -m pytest`, `python -m ruff check`,
   `python -m ruff format --check` green; record counts in the handoff.

## Explicitly out of scope

- No production logic change. Docs and handoff only.
- No new tests beyond what tasks 1-5 already have (this card verifies, it does
  not add coverage).
- Do not close the story card or move cards to `tasks/done/` yourself - per the
  workflow, that is the human's call after review.

## Acceptance criteria

- [x] PROJECT.md records the provenance-descriptor, locator-only-derivative, and
      non-text-archive facts in settled-fact style, without duplicating existing
      sections.
- [x] README (both language files) has an accurate, short heard-phrase Journal
      search note matching what task 4 shipped.
- [x] A self-sufficient human-run verification handoff exists, executable from
      its own text, naming every control/config/command literally with source
      references, and covering the mode-3-then-locator-search check and the
      model-facing exposure assertion.
- [x] `python -m pytest`, `python -m ruff check`, `python -m ruff format --check`
      green, counts recorded.

## Completion notes (2026-08-31)

- PROJECT.md: added "Architecture v1.9.1 (provenance-aware indexing and
  search surfaces)" right after the v1.9.0 section (whose "Future search
  note" this delivers) - three settled facts: the single typed provenance
  descriptor with the eligibility axis encoded on the enum; the
  locator-only, physically-separate spoken-derivative FTS with the UI-only
  model-facing decision stated; the archive overlay recorded non-text. The
  v1.9.0 "future search note" bullet was left in place (historical record of
  the v1.9.0 state, not contradicted - the new section is the delivery).
- README en + ru: two edits each - (a) updated the stale v1.9.0
  "currently not indexed ... a later v1.9.1 change may add" wording in the
  "Unlimited conversation history" section to the shipped state (locator
  exists, UI-only), (b) added a dedicated heard-phrase Journal search
  bullet describing the labeled group, the snippet-vs-canonical split, and
  the never-into-retrieval/memory boundary.
- Handoff: `tasks/v1.9.1-release-verification-handoff.md` - self-sufficient
  per Testing protocol item 4: launch command literal; Ctrl+Alt+O named with
  source (`config.py:140`, `config.example.toml:146`, `[hotkeys]
  response_mode_toggle`); state-independent mode-reach step; the task-2
  bug-report lesson applied (no undocumented-hotkey dependency - the binding
  is documented in README hotkey section and config.example.toml, cited in
  the handoff). Covers: mode-3 production of a derivative-only phrase,
  locator search assertion (group label, tag, canonical line), the UI-only
  model-facing assertion (behavioral), canonical-hit regression sanity.
  Dependencies on other docs: none - every cited fact is in
  `src/jarvis/core/config.py`, `src/jarvis/journal/provenance.py`, the
  `strings.js` UI strings (named literally), or tests, all named in the
  handoff itself.
- No production logic change; automated gates re-run green with counts
  recorded in the handoff (2366 passed / 1 skipped, ruff clean) - identical
  to the task-5 baseline.
- Story card NOT closed and no story-level cards moved to done here, per
  the card's boundary: that waits for the human's review of the run handoff
  report.

## Notes for the executor

- The handoff self-sufficiency rule is load-bearing: this project has already
  been bitten once by a handoff that silently depended on an undocumented
  hotkey default (`tasks/bug_reports/2026-08-30-handoff-silently-depends-on-
  undocumented-hotkey.md`). Name the response-mode control and its default with
  a citation; if that default is itself undocumented, that is a debt to surface,
  not to cross.
