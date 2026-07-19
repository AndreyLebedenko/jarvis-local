# Task v1.6.0-6: Attachment turn orchestration

**Status:** Backlog.
**Story:** `tasks/story-v1.6.0-file-attachments.md`
**Depends on:** task-v1.6.0-3, task-v1.6.0-4, task-v1.6.0-5.

## Summary

Wire accepted attachment plans into Jarvis's normal turn lifecycle as a
distinct source from microphone and clipboard, while preserving the
current-turn-only media rule and the busy guard.

## Context you need

- `src/jarvis/app.py`: `Orchestrator.on_utterance()`,
  `on_clipboard()`, and `_start_turn()` own the existing turn path.
- `src/jarvis/core/lifecycle.py`: add attachment-specific
  `TurnSource`/`ModelRequestInput` values narrowly.
- `src/jarvis/journal/recorder.py`: currently records voice and text user
  events; attachment journal behavior must be explicit.
- v1.4.0 model presentation layer: current-turn media survives stateless
  tool-loop follow-up requests.

## Boundary

- Orchestration and lifecycle only. Do not add browser upload controls or
  HTTP endpoints here.
- Do not alter microphone, screenshot, clipboard, reasoning-level, or MCP
  dispatch behavior except where tests prove shared lifecycle metadata
  needs the new attachment input type.
- Do not put attachment media into `ConversationHistory`.

## Requirements

- Add an orchestrator entry point for an accepted attachment plan from the
  Journal input dock transport.
- Preserve busy-guard behavior: rejected busy submissions must not consume
  pending screenshots, play success cues, or journal a user event.
- Publish `TurnAccepted` and `ModelRequestStarted` with attachment-specific
  metadata.
- Send planned text plus planned media to `backend.chat()` for the current
  turn only.
- Record the user turn in the journal with source `attachment` or another
  task-approved stable source label, including accepted text and attachment
  media references only if the journal-recording policy explicitly allows
  them.
- Keep tool-loop follow-up requests carrying the same current-turn media,
  matching the v1.4.0 correction for media survival.

## Acceptance criteria

- [ ] Tests prove accepted attachment turns call the backend with expected
      messages, media, source, and input metadata.
- [ ] Tests prove attachment media is not stored in `ConversationHistory`.
- [ ] Tests cover busy rejection and backend failure recovery.
- [ ] Tests prove existing voice and clipboard turn behavior is unchanged.
- [ ] `python -m pytest` and Ruff checks are green.

