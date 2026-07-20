# Task v1.6.2-4: Module integration and UI

**Status:** Planned.
**Story:** `tasks/story-v1.6.2-camera.md`
**Depends on:** task-v1.6.2-3 (camera tool).

## Summary

Make the camera a proper privacy-sensitive sensor module with parity to
the microphone: health chip, sound cues on capture, and a user-facing
privacy toggle that is the single authority over whether capture is
possible.

## Context you need

- Module health machinery: how existing modules publish health/state
  (`src/jarvis/core` runtime state tracker and module health events
  from story-v1.2.14) and how the Status Console renders chips.
- Mic sleep as the parity model: state ownership, toggle event flow,
  Control Center control, and its sound cues
  (`src/jarvis/audio/sound_cues.py`).
- Task 2/3 outcome: where the camera-enabled state actually lives -
  this card gives it its events, UI, and cues without creating a
  second owner.
- Cross-cutting rule 9: the camera toggle is privacy-relevant and
  never delegable; there must be no builtin tool that can flip it.
- Hidden mode / visibility (`src/jarvis/ui/visibility.py`): decide and
  record how camera state presents under Hidden mode, consistent with
  how the microphone presents there.

## Boundary

- No new capture behavior; this card wires state, events, cues, and UI
  around what tasks 2-3 built.
- Off by default stays the startup contract (config may opt into
  starting enabled; the honest default ships off).
- UI work stays within existing Status Console / Control Center
  patterns; no new surface types.

## Requirements

- The camera module reports health like other modules: distinct states
  for disabled (privacy off), ready, capture failure (e.g. last
  capture failed / source unreachable) - reflected in the chip.
- The privacy toggle in the Control Center flips the single
  camera-enabled state; engine-state events keep the UI honest in both
  directions (hotkey parity with mic sleep is not required in this
  release unless it falls out for free - record the decision).
- Every successful capture plays an audible cue; the cue is distinct
  enough from mic cues to be attributable. Failure produces a
  localized `SystemEvent` visible in the events panel.
- Toggling the camera off during an in-flight capture resolves
  deterministically (the capture completes or fails cleanly; no frame
  is delivered after the toggle if the story's guarantee would be
  violated) - state the chosen semantics in the card outcome.
- UI strings are localized per the existing UI language catalog.

## Acceptance criteria

- [ ] Tests cover: state transitions and their events, chip state
      derivation, toggle authority (no other code path can enable
      capture), cue triggering on capture, and the toggle-during-
      capture semantics.
- [ ] A human-run handoff scenario covers: chip states on a real
      device, cue audibility, toggle behavior mid-session, and Hidden
      mode presentation.
- [ ] `python -m pytest` and Ruff checks are green.
