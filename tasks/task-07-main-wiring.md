# Task: Main wiring and system prompt (main.py)

Status: Not started.

Story: [story-jarvis-v1.0.md](story-jarvis-v1.0.md)

## Summary

The process entry point: instantiates every module, wires their bus
subscriptions, authors the system prompt, and drives sound cues for state
transitions (listening / thinking / speaking / error) - the only feedback
mechanism available given "hotkeys + sound cues only, no GUI" (PROJECT.md).
The system prompt must enforce short conversational answers (latency is
proportional to answer length) and Russian by default.

## Current boundary

In scope:

- Process startup: load config, construct `bus`, `backend`, `audio_in`,
  `tts`, `capture` and subscribe them to each other correctly through the
  bus (no direct module-to-module calls, per PROJECT.md).
- System prompt text encoding the two hard requirements: short answers,
  Russian by default.
- Sound cue playback bound to defined state-transition events (listening
  started, thinking/generating, speaking, error) using cue file paths from
  `config.py`.
- Graceful shutdown on a hotkey or OS signal: unsubscribe everything, let
  in-flight requests finish or cancel cleanly, no hang.
- Top-level error handling so one failed request/turn does not crash the
  process.

Out of scope:

- Auto-start / Windows service installation (explicitly out of scope for
  v1.0, see the story card).
- Any GUI.
- Multi-session or multi-user support.

## Dependencies

All prior task cards (task-01 through task-06).

## Open question inherited from task-03

PROJECT.md's "Open questions" section flags two unresolved items that this
task's history-wiring design must settle, not assume:

- Whether media on a non-final message in a multi-turn `messages` array is
  actually used by `gemma4:12b-it-qat`, or silently ignored/erroring -
  never verified against live Ollama (day-0 only covered single-turn
  media). May need a day-0-style experiment before this task relies on
  resending media in history.
- The prefill-cost/history-retention policy for accumulated media across
  turns (trim to the latest turn's media, replace older turns with a
  text-only summary, or something else).

Resolve both before or during this task's implementation and update
PROJECT.md's "Open questions" section with the answer, per CLAUDE.md's
"Project context" rule 2.

## Acceptance criteria

Automated tests (fakes/mocks for hardware-touching modules):

- A wiring test confirms every module is subscribed to the bus events it is
  supposed to consume, using fake stand-ins for `audio_in`, `tts`, and
  `capture` where they would otherwise touch hardware.
- A content test confirms the system prompt text includes the Russian-
  default directive and the short-answer directive.
- The shutdown path unsubscribes all modules and returns without hanging,
  exercised with a short timeout in the test itself.

Manual handoff (full hardware stack, human runs and reports):

- Exact command to launch the assembled process.
- Script: speak a question, optionally trigger a screenshot capture, and
  time from the end of your utterance (VAD end-of-speech, i.e. the point
  audio_in.py publishes the finished chunk) to the first audio out of the
  speakers. Confirm this end-to-end interval is within ~3 s, per the target
  defined once in PROJECT.md's Architecture v1.0 section and the story
  card (covers audio prefill + first-sentence generation + TTS synthesis
  of that sentence). This is the authoritative measurement of the target;
  task-05's manual check only covers its own synthesis/playback slice.
  Also confirm sound cues play at the right moments (listening, thinking,
  speaking, and on an intentionally triggered error).
- Rerun `day0_checks.py` against this build and confirm the verified facts
  in PROJECT.md still hold; report any deviation rather than accepting it
  silently (PROJECT.md instructs a rerun after any backend/model/driver
  change - a fresh full build qualifies).
