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

## Backlog notes inherited from task-03, task-04, and task-06

Implementation decisions surfaced while building backend.py, audio_in.py,
and capture.py, deferred to this task since they belong to process
startup / wiring, not the individual adapters:

- **Warm-up request at startup.** Cold load measured at 4.2 s vs 0.3 s
  warm. Given the ~3 s end-to-end latency target (see PROJECT.md's
  Architecture v1.0 section and the story card), the first real user
  request cannot absorb a cold-load penalty. Fire a throwaway warm-up
  request to Ollama during startup, before the process signals it is
  ready to listen.
- **Malformed stream line policy.** backend.py's `chat()` currently lets a
  `json.loads` failure on a malformed stream line raise out of `chat()`
  uncaught. Acceptable for v1.0 as built, but this task must decide
  explicitly whether to catch it (log and skip the line, or surface an
  error event on the bus) rather than let it silently remain an
  unhandled-exception path into whatever calls `chat()`.
- **Resolved: the ~3 s target is measured from audio_in.py's publish, not
  from the literal instant speech physically stopped.** `vad.
  request_end_pause_seconds` (audio_in.py) is a separate, tunable cost
  paid *before* the ~3 s window starts, not counted against it. audio_in.py
  merges Silero's raw speech segments across any gap shorter than this
  threshold (a breath or thinking pause mid-request), and only publishes
  an utterance once it is followed by this much buffered silence with no
  further speech merged into it - confirming the user actually finished
  the request, not just paused inside it. Its current default (2.0 s) is
  deliberately conservative for the development stage (chosen after an
  earlier 0.5 s default caused a real bug: a request with an internal
  ~0.3 s breath pause was published as two separate requests); production
  is expected to tighten it to ~1.0-1.5 s once request-boundary behavior
  is validated. Total perceived latency from the user's real silence to
  first audio is therefore roughly `request_end_pause_seconds + ~3 s`,
  and tuning the former down is how that total improves - not by
  loosening the ~3 s figure itself. This task's manual handoff already
  times from publish (see below), which is correct as-is.
- **The process must run elevated (Administrator) for global hotkeys to
  actually be global (task-06's `keyboard`-based capture.py).** Verified
  live: without elevation, hotkeys only fire while Jarvis's own window
  has focus - defeating the point of a hotkey-driven background
  assistant, since the whole idea is triggering it while some other app
  is focused. This task's process-startup step should check for
  elevation and print a clear warning (or refuse to start) if not
  elevated, rather than silently degrading to "only works when focused"
  with no explanation. Document the elevation requirement in whatever
  launch instructions this task produces.

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
