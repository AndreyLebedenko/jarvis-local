# Task v1.5.2-3: Feed copy controls

**Status:** Completed.
**Story:** `tasks/done/story-v1.5.2-journal-ux-pack.md`
**Depends on:** nothing in this story; independent of tasks 1-2.

## Summary

Let the user copy a whole Jarvis answer or an arbitrary selected
fragment out of the Journal feed (explicit owner request, 2026-07-18).
UI only.

## Context you need

- `src/jarvis/ui/status_console_ui/app.js`: journal feed rendering
  (message tiles, `journal-msg-text` content).
- `src/jarvis/ui/status_console_ui/strings.js`: localization catalog.
- The UI runs inside pywebview/WebView2: verify which clipboard API
  works there (`navigator.clipboard.writeText` vs `execCommand`
  fallback) instead of assuming browser behavior; if neither works,
  that is a story stop condition, not something to patch around.

## Boundary

- Assistant answers get the explicit copy control; arbitrary-fragment
  copy is normal text selection plus Ctrl+C - make sure feed CSS does
  not block selection, do not build a custom selection mechanism.
- No transport or backend changes; no copy of media, only text.
- No feed re-layout; the control must fit the existing tile design.

## Requirements

- Each assistant message tile exposes a copy control that copies the
  full answer text (the recorded text, not the highlighted/derived
  HTML).
- Successful copy gives brief visual feedback; failure shows a
  localized message instead of failing silently.
- Text selection within feed messages works for partial copy.
- New strings go through the localization catalog (ru/en).

## Acceptance criteria

- [x] If copy logic is factored as a pure function (tile data -> copied
      string), a test pins that the copied text matches the recorded
      answer text, including multi-line answers.
- [x] Human-run manual handoff covers: copy button on a short and a
      multi-line answer, paste into an external editor, partial
      selection copy, and behavior in Hidden mode (no feed, nothing to
      copy).
- [x] `python -m pytest` and Ruff checks are green.
