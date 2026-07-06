# Task: thinking mode main wiring and manual handoff

Status: Draft.

Story: [story-thinking-mode.md](story-thinking-mode.md)

## Summary

Wire thinking mode end to end in the assembled Jarvis process: start the
hotkey listener, apply the current state to each new backend turn, play
on/off cues, update config.example, run the final manual handoff, and
record the architecture in `PROJECT.md`.

## Current boundary

In scope:

- `main.py` constructs the thinking-mode state owner and passes its
  current value into each accepted `OllamaBackend.chat()` call.
- The current state is sampled at turn start. A hotkey press during an
  in-flight response affects the next accepted turn, not the current
  stream.
- `wire()` subscribes `ThinkingModeToggled` and plays `thinking_on` /
  `thinking_off` cues.
- The same subscriber logs an INFO line naming the new state, analogous
  to the existing "Microphone awake/asleep" log.
- `run()` starts the thinking-mode hotkey listener as a background task
  and cancels/awaits it during shutdown like the existing listeners.
- `sound_cues.py` generates distinct placeholder tones for
  `thinking_on` and `thinking_off`.
- `config.example.toml` lists every new field from task-12.
- `PROJECT.md` records the final architecture and the hard rule:
  `message.thinking` must never be published as `ResponseToken` or reach
  TTS.

Out of scope:

- Showing reasoning to the user.
- Interrupting or restarting an in-flight response when the mode changes.
- Changing conversation history retention.
- Changing the system prompt to request hidden chain-of-thought.
- Any GUI/status indicator.

## Dependencies

- [task-11-thinking-backend-contract.md](task-11-thinking-backend-contract.md)
- [task-12-thinking-mode-state.md](task-12-thinking-mode-state.md)
- Existing `main.py` wiring and shutdown tests.
- Existing `sound_cues.py` generated-cue pattern.

## Acceptance criteria

Automated tests:

- `Orchestrator` passes `thinking_enabled=False` by default to
  `backend.chat()`.
- After a `ThinkingModeToggled(True)` event, the next accepted turn passes
  `thinking_enabled=True`.
- A toggle while busy does not mutate the already-started backend call and
  applies only to the following accepted turn.
- `wire()` plays the correct cue for on/off events.
- `wire()` logs "Thinking mode enabled" / "Thinking mode disabled" (or
  equivalent wording) for on/off events at INFO level.
- `run()` starts and cancels the thinking-mode hotkey listener with the
  other background tasks.
- `config.example.toml` round-trips through strict config parsing.
- A regression test confirms `message.thinking` chunks from the backend
  still do not reach `TtsOutput.on_token` through the real bus wiring.

Manual handoff (human runs and reports):

- Launch Jarvis from an elevated terminal:
  `python main.py`
- Confirm the thinking-mode hotkey works globally.
- Confirm `thinking_on` and `thinking_off` cues are audible and distinct.
- Confirm the console logs the thinking-mode state transition when the
  hotkey is pressed.
- With thinking off, submit a normal clipboard or voice turn and confirm
  normal latency/answer behavior.
- Toggle thinking on, submit a harder text/clipboard turn, and confirm the
  answer is spoken normally while reasoning is not spoken.
- With thinking on, submit a turn with a screenshot or voice/audio input
  and confirm reasoning is still not spoken.
- Toggle thinking off and confirm the next turn uses non-thinking mode.
- Confirm the process remains offline after one-time setup.

Documentation:

- `PROJECT.md` records:
  - default thinking mode;
  - configured hotkey;
  - sound cue fields;
  - state owner and "sampled at turn start" behavior;
  - exact backend parameter;
  - reasoning-token isolation rule;
  - manual verification result.

Stop conditions:

- Any evidence that reasoning appears in `ResponseToken`, TTS, history, or
  logs.
- Any race where a hotkey press can affect the already-running backend
  request in a partially applied way.
- Any hardware/manual failure outside the code scope, per project
  testing protocol.
