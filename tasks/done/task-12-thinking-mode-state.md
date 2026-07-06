# Task: thinking mode state and hotkey input

Status: Completed.

Story: [story-thinking-mode.md](story-thinking-mode.md)

## Summary

Add the pure runtime state and hotkey-input surface for thinking mode,
without yet wiring it into the assembled `main.py` process.

The goal is a small, testable component that owns "thinking is currently
enabled for future turns" and publishes a state-change event for cues and
orchestration.

## Current boundary

In scope:

- Add config schema fields:
  - `hotkeys.thinking_toggle`, default `ctrl+alt+t`.
  - `sound_cues.thinking_on`.
  - `sound_cues.thinking_off`.
- Add a small state owner for thinking mode. It should expose an
  idempotent read of the current state and a toggle method that runs on
  the asyncio event loop.
- Add a bus event such as `ThinkingModeToggled(is_enabled: bool)`.
- Define the logging expectation for the eventual main.py subscriber:
  every explicit user toggle should produce an INFO log line naming the
  new state, analogous to task-10's "Microphone awake/asleep" log. This
  task only defines and tests the event data needed for that log; the
  actual logging belongs to task-13's `main.py` wiring.
- Add a hotkey listener function shaped like the existing capture,
  clipboard, and mic-sleep listeners: config-driven binding, injectable
  keyboard module, no direct dependency on `SoundCuePlayer`.
- Ensure the hotkey callback does not read/flip shared state in the
  keyboard thread; it should schedule the toggle on the event loop, same
  race-avoidance pattern as task-10's mic sleep toggle.
- Add config parsing tests and hotkey listener tests with fakes.

Out of scope:

- Passing the state into `OllamaBackend.chat()`.
- Playing sound cues in `main.py`.
- Writing the final INFO log line in `main.py`.
- Starting the listener in `run()`.
- Updating `config.example.toml`.
- Manual hardware hotkey testing.

## Dependencies

- task-11's backend contract, or at minimum its decided parameter name and
  boolean shape.
- Existing hotkey listener patterns in `capture.py`, `clipboard_input.py`,
  and `audio_in.py`.
- Existing config validation style in `config.py`.

## Acceptance criteria

Automated tests:

- Config parsing accepts the new hotkey and cue path fields.
- Defaults are present when the fields are omitted.
- The hotkey listener registers `hotkeys.thinking_toggle`.
- A fake hotkey press schedules exactly one event-loop toggle.
- Two rapid fake presses result in two toggles, not two copies of the same
  stale state transition.
- Toggling publishes `ThinkingModeToggled` with the new state.
- `ThinkingModeToggled` carries enough state for task-13 to log
  "Thinking mode enabled/disabled" without reading shared state from the
  hotkey thread.
- The state starts disabled by default.

Documentation:

- No `PROJECT.md` update is required yet unless this task changes the
  architecture beyond the story decisions.

Stop conditions:

- If the state owner needs to know about backend payload internals.
- If the hotkey callback cannot be made thread-safe without broad
  refactoring.
- If adding config fields forces unrelated config-schema changes.
