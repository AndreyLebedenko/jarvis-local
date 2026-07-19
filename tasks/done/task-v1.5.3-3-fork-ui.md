# Task v1.5.3-3: Fork UI

**Status:** Completed.
**Story:** `tasks/story-v1.5.3-memory-layer-a.md`
**Depends on:** task-v1.5.3-2 (fork command).

## Summary

Add "continue this conversation" to the Journal view: the user picks a
past session and triggers the fork, and the UI makes the new session's
provenance visible. UI only.

## Context you need

- `src/jarvis/ui/status_console_ui/app.js`: session list rendering,
  token-in-query fetch pattern, live `journal_event` handling.
- `src/jarvis/ui/status_console_ui/strings.js`: localization catalog.
- task-v1.5.3-2's response contract (success with new session id,
  structured errors) and the provenance event shape.

## Boundary

- One control per past session; no multi-select, no seed preview UI,
  no budget editing in the UI (budget is config).
- No feed re-layout.
- Hidden mode: suppressed with the journal view.

## Requirements

- Each non-active session in the Journal view exposes a localized
  "continue" control; triggering it calls the fork command and, on
  success, switches the view to the live feed of the new session.
- A forked session is visibly marked as continued from its source
  (e.g. a provenance line derived from the recorded provenance event),
  and dropped-turn truncation from the seed result is surfaced, not
  hidden.
- Errors (busy, unknown session, oversize turn, Hidden) surface as
  localized messages.
- All new strings go through the localization catalog (ru/en).

## Acceptance criteria

- [ ] Any pure mapping logic (response/provenance -> display state)
      that is factored testably has tests.
- [ ] Human-run manual handoff covers: fork from a past session, first
      new turn answering with awareness of seeded context, provenance
      marker display, busy rejection, and Hidden suppression.
- [ ] `python -m pytest` and Ruff checks are green.
