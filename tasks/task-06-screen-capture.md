# Task: Screen capture (capture.py)

Status: Not started.

Story: [story-jarvis-v1.0.md](story-jarvis-v1.0.md)

## Summary

Hotkey-triggered screenshots via `mss`, in two modes: full screen and
region-select. Publishes the resulting PNG to the bus for inclusion in the
next backend request. Region-select exists specifically because the day-0
OCR check found small fonts garble at the standard visual token budget, and
the fix is cropping at full resolution rather than raising the budget
(PROJECT.md verified facts).

## Current boundary

In scope:

- Hotkey listener that triggers a capture (binding read from `config.py`).
- Full-screen capture mode.
- Region-select capture mode: an interactive rectangle selection, captured
  at full resolution.
- Publishing the resulting PNG bytes plus mode/dimension metadata on the
  bus.

Out of scope:

- OCR itself - the model reads screen text at request time (day-0 verified
  fact); this module only produces the image.
- Any multi-monitor selection UI beyond whatever `mss` provides for its
  default monitor enumeration.
- Screenshot history or a gallery/review UI (no GUI in v1.0 per PROJECT.md).

## Dependencies

`bus.py` (task-01), `config.py` (task-02, for the hotkey binding).

## Acceptance criteria

Automated tests (mocked/fake screen buffer, no live hotkey or display
interaction required):

- Full-screen capture and region-select crop each return image bytes of the
  expected dimensions given a fake screen buffer.
- The hotkey binding used is read from the config settings object, not
  hardcoded (confirmed by varying the fixture config).
- The published bus event carries the expected metadata (mode, width,
  height).

Manual handoff (hotkey/display-dependent, human runs and reports):

- Exact command to run the live capture listener; confirm the real hotkey
  triggers a full-screen capture, a second binding (or modifier) triggers
  region-select, the interactive selection works as expected, and the
  resulting image looks correct.
