# Task journal-06: Live feed and audio playback

**Status:** Completed.
**Story:** `tasks/story-v1.5.0-dialog-journal.md`
**Depends on:** task-journal-05.

## Summary

Make the Journal view live and audible: new turns of the current session
append in real time via the `journal_event` WS push, and audio tiles play
their clip.

## Context you need

- Story card: live feed is a v1.5.0 requirement (it is what makes v1.5.1
  text input cheap); playback is a v1.5.0 requirement and a debugging
  tool ("hear exactly what the model received").
- `src/jarvis/ui/status_console_ui/transport.js` + `app.js`: how existing
  WS messages (e.g. system events) are dispatched to the UI; handle
  `journal_event` the same way.
- task-journal-04 defines the `journal_event` payload and the media URL
  scheme.

## Boundary

- Changes limited to `src/jarvis/ui/status_console_ui/` and tests.
- Playback via the standard HTML5 `<audio>` element pointed at the media
  endpoint URL - no bundled player library, no file:// access.
- No right-click menu on the tile (v1.5.1); no transcription; no search
  (task-journal-07).

## Requirements

- A `journal_event` push appends a rendered turn to the feed if the
  affected session is currently displayed; if the user is viewing an old
  session, the session list metadata updates but the view does not jump.
- Bottom-anchoring: if the feed was scrolled to the bottom, it stays
  pinned as turns append; if the user scrolled up, position is
  preserved.
- Audio tile: play/pause toggle, progress indication, duration; only one
  tile plays at a time; playing state survives feed appends (no
  re-render that kills playback).
- Hidden mode entered mid-playback stops playback immediately along with
  swapping to the placeholder.

## Acceptance criteria

- [x] Structural/logic tests: `journal_event` dispatch appends to the
      correct session only; bottom-anchor logic covered (pinned vs
      scrolled-up); single-playback invariant present; Hidden stops
      playback.
- [x] `python -m pytest` green.
- [x] Human-run handoff prepared: speak to Jarvis with the Journal view
      open, verify the voice turn and answer appear live; play back the
      recorded utterance and confirm it is the audio the model received;
      verify Hidden mid-playback. This handoff also serves as the live
      end-to-end verification of task-journal-02 recording.

