# Task: Main wiring and system prompt (main.py)

Status: Completed.

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

## Open question inherited from task-03 - resolved

Human decision: history is text-only in v1.0. Media is attached only to
the current turn's message; `ConversationHistory`/`Turn` in main.py carry
a `media_b64` field precisely so a later release can start resending
media in history without restructuring this abstraction - v1.0 code
simply never populates it. This sidesteps both originally-open items
(unverified non-final-message media behavior; prefill-cost/retention
policy) rather than resolving them - they remain genuinely unverified and
would need addressing if a future release changes this decision. Recorded
in PROJECT.md's "Open questions" section.

## Backlog notes inherited from task-03, task-04, and task-06 - resolved

Implementation decisions surfaced while building backend.py, audio_in.py,
and capture.py, deferred to this task since they belong to process
startup / wiring, not the individual adapters:

- **Warm-up request at startup - resolved.** Cold load measured at 4.2 s
  vs 0.3 s warm. main.py's `warm_up()` fires a throwaway `backend.chat()`
  call *before* `wire()` subscribes anything to the bus, so the response
  tokens are published to zero subscribers (bus.py: publishing with no
  subscribers is a no-op) rather than spoken aloud or recorded into
  history - no unsubscribe/resubscribe dance needed.
- **Malformed stream line policy - resolved, no backend.py change.**
  backend.py's `chat()` still lets a `json.loads` failure on a malformed
  stream line raise out of `chat()` uncaught. `Orchestrator.on_utterance`'s
  try/except around the `backend.chat()` call already catches this (or
  any other exception from that call), logs it, plays the error cue, and
  clears the busy flag so the process keeps running - task-07's own
  top-level error handling requirement covers this directly.
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
  is focused. **Resolved:** main.py's `is_elevated()` checks at startup
  and prints a clear warning (chosen over refusing to start, so the
  process still stays usable for local testing/development without
  elevation) - see the manual handoff for confirming the warning appears
  correctly when not elevated.

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

- Exact command to launch the assembled process: `python main.py`. Run it
  from a non-elevated terminal at least once to confirm the elevation
  warning prints; run it elevated (as Administrator) for the rest of this
  handoff so hotkeys work globally.
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

Manual handoff findings, all fixed and re-verified by the human on the
final pass (tests green, cold start clean, sound quality good, English
text recognized and spoken well via `transliterate_latin()` including
loanwords like "calvados" with expected pronunciation nuances, no further
remarks):

- Cold-start `httpx.ReadTimeout` on the warm-up call - fixed via
  `config.backend.read_timeout_seconds` (see Verified facts).
- Audible crackling/tempo artifacts from a sound cue and TTS speech
  overlapping on the output device - fixed via a shared playback lock
  (see Verified facts).
- Latin-script words (e.g. "gemma") silently unvoiced by Silero - fixed
  via `tts.py`'s `transliterate_latin()` (see Verified facts).
- Jarvis responding to its own TTS output picked up by the microphone (no
  echo cancellation) - mitigated via `Orchestrator.finish_turn()`'s
  cooldown (see Verified facts; full fix is Roadmap item 7).
- `KeyError` crash in capture.py's region-select overlay (suspected
  Tkinter thread-safety issue) - defensive guard added; see
  `tasks/bug_reports/capture-region-select-tkinter-thread-safety.md` for
  the full writeup, since the suspected root cause is not fully resolved.

Manual handoff passed: end-to-end timing, sound cues at all transitions,
and a `day0_checks.py` rerun were all covered across this task's manual
handoff rounds with no outstanding remarks. Human sign-off: "Замечаний
нет. Закрывай задачу... как успешную."
