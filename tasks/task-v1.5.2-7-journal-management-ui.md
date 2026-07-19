# Task v1.5.2-7: Journal management UI

**Status:** Backlog.
**Story:** `tasks/story-v1.5.2-journal-ux-pack.md`
**Depends on:** task-v1.5.2-6 (usage and deletion API).

## Summary

Surface journal disk usage in the Journal view and give the user a
confirmed, per-session deletion flow on top of the v1.5.2-5 API. UI
only.

## Context you need

- `src/jarvis/ui/status_console_ui/app.js`: journal session list
  rendering and the token-in-query fetch pattern.
- `src/jarvis/ui/status_console_ui/strings.js`: localization catalog.
- task-v1.5.2-6's response contracts (usage shape, structured errors
  for active-session and not-found).

## Boundary

- Display and deletion flow only; no thresholds, warnings automation,
  or bulk "delete all" control.
- No feed re-layout; usage and delete controls attach to the existing
  session list presentation.
- Hidden mode: the whole surface is suppressed with the rest of the
  journal view.

## Requirements

- The Journal view shows total journal size and per-session sizes in
  human-readable units.
- Each non-active session exposes a delete control; the active session
  shows none (or a disabled one with a localized explanation).
- Deletion requires an explicit confirmation step naming the session
  and its size; cancel is the default/safe action.
- After deletion the session list, usage numbers, and search results
  reflect the removal without a full page reload.
- API errors (active session, not found, auth) surface as localized
  messages, not silent failures.
- All new strings go through the localization catalog (ru/en).

## Acceptance criteria

- [ ] Pure logic that is factored testably (byte-size formatting,
      response-to-state mapping) has tests.
- [ ] Human-run manual handoff covers: usage display sanity against
      on-disk sizes, full confirm-delete flow, cancel flow,
      active-session protection, search consistency after deletion,
      and Hidden mode suppression.
- [ ] `python -m pytest` and Ruff checks are green.
