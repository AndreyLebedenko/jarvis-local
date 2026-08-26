# Task v1.8.2-2: Play control in the chat log

**Status:** Proposed.
**Story:** `tasks/story-v1.8.2-replay-tts.md`
**Depends on:** task-v1.8.2-1 (replay core, busy-guard, interrupt). This card
adds the UI trigger only.

## Summary

Add a Play (and Stop) control to every past assistant reply in the status
console chat log, wired to the replay core from task 1. Any past reply is
replayable, not just the last. A press while speech is active shows the busy
error the core emits; there is no queueing.

## Context you need

- `tasks/story-v1.8.2-replay-tts.md`: locked decisions - Play on any past
  reply, reject-when-busy with beep + visible error, Ctrl+Alt+I cancels.
- `tasks/task-v1.8.2-1-replay-core.md`: the accessor, the one-shot replay
  entry point, the busy-reject behavior, and the error event this UI renders.
- `src/jarvis/ui/status_console.py` and `src/jarvis/ui/transport.py`: how
  assistant replies are currently rendered and how the console receives
  events; where a per-reply control attaches and how a user action on a past
  reply is dispatched back.
- `PROJECT.md` tooling note 7 (Browser-pane sub-resource caching for
  `status_console_ui/*.js|*.css`) - relevant if this control lives in the
  WebView layer; verify edits with a cache-busted fetch before assuming a
  change did not apply.

## Boundary

- UI trigger and its wiring to the task-1 core only. No new synthesis,
  playback, busy-detection, or interrupt logic - all of that is task 1.
- Play and at most Stop. No scrubbing, pause/resume, speed, or per-reply
  voice selection (out of scope per the story).
- No change to how a live turn renders or streams beyond attaching the
  control to past replies.

## Requirements

- Render a Play control on each assistant reply in the chat log, for any past
  reply in the session view.
- On press, invoke the task-1 replay entry point for that reply's turn.
- While a replay is running, offer a Stop affordance that routes to the same
  cancellation the core exposes (the Ctrl+Alt+I path). Its exact form
  (dedicated Stop vs. Play toggling) is a card decision.
- When the core rejects a press as busy, surface the core's visible error in
  the console; do not implement a separate busy check in the UI.
- Do not block the console while a replay synthesizes/plays.

## Acceptance criteria

- [ ] Every assistant reply in the chat log shows a Play control, including
      older replies, and pressing it replays that specific reply.
- [ ] Pressing Play while speech is active shows the busy error from the core
      (beep + message); nothing is queued and the control can be pressed
      again once free.
- [ ] A running replay can be stopped from the UI via the core's existing
      cancellation path.
- [ ] The control's presence and dispatch do not alter how a live turn
      renders or streams.
- [ ] `python -m pytest`, `python -m ruff check .`, and
      `python -m ruff format --check .` are green for the non-UI logic.
      Interactive Play/Stop and audio behavior are a prepared human-run
      handoff with exact steps.

## Stop conditions

- Stop if the status console has no per-reply anchor to attach a control to
  and adding one would mean reworking the reply-rendering contract shared
  with live streaming.
- Stop if dispatching a user action bound to a specific past turn back to the
  core is not expressible through the existing console event/transport
  wiring without a new bidirectional channel.

## Verification

- Focused tests for the reply-to-core dispatch and error-rendering logic.
- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Human-run handoff: Play on a recent and an older reply; Play while Jarvis
  speaks shows the busy error; Stop halts a running replay.
