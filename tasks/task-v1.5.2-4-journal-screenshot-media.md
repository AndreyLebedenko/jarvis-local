# Task v1.5.2-4: Record screenshot media in the journal

**Status:** Backlog.
**Story:** `tasks/story-v1.5.2-journal-ux-pack.md`
**Depends on:** nothing in this story; independent of tasks 1-3.

## Summary

Record the screenshot image that a turn actually sent to the model as
journal media beside the user event, the same way voice wav bytes are
already recorded. Recorder and orchestrator wiring only; rendering is
task-v1.5.2-5.

## Context you need

- `src/jarvis/app.py`: `Orchestrator.on_screenshot()` stores
  `_pending_screenshot_b64`; `on_utterance()` consumes it into the
  turn's `media` list (voice turns only - `on_clipboard()` deliberately
  never attaches the pending screenshot, see PROJECT.md v1.1 notes);
  `_start_turn()` currently passes only `voice_wav_bytes` to the
  recorder.
- `src/jarvis/journal/recorder.py`: `record_voice_user()` writes wav
  media via `store.write_media()` and `_next_media_name()`;
  `record_text_user()` records `media=()`.
- `src/jarvis/journal/events.py`: `JournalEvent` media reference shape
  and `_validate_media_path()`.
- `src/jarvis/ui/transport.py`: `_journal_media_handler()` - confirm
  the existing serving path handles the stored png (content type) or
  note the gap for task-v1.5.2-5; do not build serving changes here.

## Boundary

- Journal recording only: no feed rendering, no thumbnails, no
  transport endpoints, no UI.
- Record exactly what was sent to the model for this turn (the png
  captured by `capture.py`), stored as a media file beside the log -
  never embedded in JSONL, matching the voice wav pattern.
- Do not change which turns get screenshots (voice-only attachment
  stays as is); do not touch the v1.6.0 attachment paths.
- Hidden mode semantics for recording stay exactly as they are for
  voice media today (this task copies the existing pattern, it does
  not design a new privacy rule).

## Requirements

- A voice turn that consumed a pending screenshot records the png as a
  session media file and references it from the same user event that
  references the voice wav (event schema permitting; if the schema
  cannot carry two media references on one event, stop and report -
  that is a schema decision, not an implementation detail).
- Media naming follows the existing `_next_media_name()` convention
  with an image extension.
- Turns without a screenshot are byte-identical in recording behavior
  to today.
- The b64-to-bytes step happens in the orchestrator/recorder seam, not
  in the store.

## Acceptance criteria

- [ ] Tests cover: voice turn with screenshot records both wav and png
      media references on the user event; voice turn without screenshot
      is unchanged; text turns still record `media=()`; the stored png
      bytes equal the captured bytes.
- [ ] No UI or transport behavior changes.
- [ ] `python -m pytest` and Ruff checks are green.
