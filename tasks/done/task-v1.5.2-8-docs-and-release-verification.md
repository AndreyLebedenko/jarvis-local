# Task v1.5.2-8: Docs and release verification

**Status:** Completed.
**Story:** `tasks/done/story-v1.5.2-journal-ux-pack.md`
**Depends on:** tasks v1.5.2-1 through v1.5.2-7.

## Summary

Record the v1.5.2 architecture in PROJECT.md, bring config/docs up to
date, and prepare the human-run release verification checklist that
closes the story.

## Context you need

- `PROJECT.md`: the "Architecture v1.5.0 (dialog journal)" section is
  the model for a compact per-release architecture entry.
- All seven task cards of this story and their outcomes.
- `tasks/done/` release-verification precedents (e.g. the v1.5.0 story
  closure and `task-v1.6.0-10-release-verification.md`'s shape).

## Boundary

- Documentation and verification only; no code changes beyond fixes the
  verification itself reveals as in-scope one-liners (anything larger
  becomes a bug report per the reporting protocol).

## Requirements

- PROJECT.md gains an "Architecture v1.5.2" entry: text input endpoint
  and turn source, copy controls, screenshot media recording and
  thumbnails, disk usage/deletion contract (manual, whole-session,
  index-consistent, active-session protected at the transport layer),
  and the unchanged privacy/locality boundaries.
- `config.example.toml` documents any new config fields introduced by
  the story (only if some were actually added).
- README/user-facing docs mention the new Journal capabilities where
  the journal is already described.
- A consolidated human-run verification checklist covers the manual
  handoffs of tasks 2, 3, 5, and 7 plus an end-to-end pass: typed turn
  answered aloud, copied, its screenshot thumbnail visible, session
  deleted after the run.
- Any behavior found broken but out of scope becomes a report under
  `tasks/bug_reports/`.

## Acceptance criteria

- [x] PROJECT.md updated in the same change as the story closure.
- [x] Human-run checklist executed by the human with results recorded;
      open findings filed as reports.
- [x] `python -m pytest` and Ruff checks are green.
- [x] Story card moved toward closure per the task documentation
      workflow (cards to `tasks/done/` after human approval).

## Human-run verification checklist

Run from the repository root after automated checks are green:

```powershell
python -m jarvis --status-console
```

Manual pass:

- Journal input dock: send by button; send by Enter; Shift+Enter inserts a
  newline; accepted text clears only after the endpoint accepts it; the answer
  appears live in the feed and is spoken aloud.
- Rejections: while Jarvis is busy, submit another typed message and confirm
  the text remains in the dock with visible feedback; switch to Hidden and
  confirm the Journal view and dock are suppressed and submission does not
  reach Jarvis.
- Copy controls: copy a short assistant answer and a multi-line assistant
  answer with the per-answer button, paste into an external editor, then copy
  an arbitrary selected fragment from the feed with normal Ctrl+C.
- Screenshot thumbnails: capture a screenshot for the next voice request,
  speak a request, confirm the same turn records audio plus an image thumbnail
  in the live feed and after reload; temporarily remove the PNG media file on
  disk and confirm the localized missing-image placeholder appears.
- Journal management: compare total/per-session size display against the
  session directory on disk for sanity; cancel a delete confirmation; delete a
  non-active session; confirm the session list, usage numbers, selected feed,
  and search results update without full page reload; confirm the active
  session cannot be deleted.
- End-to-end release pass: typed turn answered aloud, answer copied,
  screenshot thumbnail visible, then the completed test session deleted after
  review.

Record the human result here before moving task cards to `tasks/done/`.

## Human verification result

Executed by the human on 2026-07-19.

- Journal typed input: passed after the live-selection fix. The dock creates a
  new runtime journal session, auto-selects it, displays the user input and
  assistant answer live, speaks the answer, and clears unchanged submitted text
  after completion.
- Rejections: passed. Busy/Hidden rejection keeps user text and does not leak
  Hidden text to the orchestrator.
- Copy and paste: passed for answer copy and normal selection copy.
- Screenshot thumbnail: passed, including thumbnail rendering from journal
  media.
- Disk usage and deletion: passed. Size display is sane against
  `D:\AI\Jarvis\journal`; confirmed non-active deletion works and active
  session deletion is protected.

Verification notes:

- The dock is visually global but appears below whichever session is selected;
  this can read like archived-session continuation. v1.5.2 intentionally has no
  explicit "new session" button and no continuation of old sessions.
- PNG screenshot media can dominate per-session size. v1.5.2 keeps the exact
  PNG bytes sent to the model; derived JPG/WebP thumbnails are deferred to a
  future storage/thumbnail policy rather than changing this story's media
  contract.
