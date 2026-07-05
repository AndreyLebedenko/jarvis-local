# Task: Microphone sleep mode (audio_in.py)

Status: Completed.

Review found one typing issue, fixed: the `StreamFactory` seam used
`Callable[[int], Any]`, erasing the stream's type; replaced with a
`Protocol` (`InputStreamLike`) declaring `read`/`stop`/`start`/
`__enter__`/`__exit__`, so `StreamFactory = Callable[[int], InputStreamLike]`.
Automated tests (118 passed) and the manual handoff (sleep/wake toggle via
a throwaway console script, Windows mic-in-use indicator confirmed off
while asleep) both verified.

Story: [story-v1.1-controlled-input.md](story-v1.1-controlled-input.md)

## Summary

A global hotkey toggles the microphone between listening and a genuine
privacy-oriented sleep: capture actually pauses at the device/stream
level, rather than continuing to listen while results are merely
discarded. This is an explicit privacy feature, not an internal
implementation detail of some other mechanism (see the story's Boundaries
for why automatic mic-pausing during Jarvis's own speech is deliberately
excluded from this task and left as an open decision for task-10).

## Current boundary

In scope:

- `AudioInput` gains awake/asleep state, driven from *outside* the
  module (a hotkey callback via the bus, or direct method calls - decide
  the exact mechanism during implementation, matching capture.py's
  established pattern of an injectable, testable seam plus a thin
  hardware-facing wrapper).
- `run_microphone_loop()` must not busy-poll while asleep: block
  efficiently (e.g. on an `asyncio.Event`) until woken, rather than
  looping with a sleep/check cadence.
- Pause/resume must reuse the *same* `sd.InputStream` object via its own
  `.stop()`/`.start()` methods, not tear down and reconstruct the stream.
  Reconstructing adds wake-up latency and is unnecessary - `InputStream`
  is designed to be paused and resumed in place.
- The internal audio buffer must be reset on the sleep transition (and
  verified clean on wake). Without this, audio captured just before sleep
  and audio captured just after wake could be merged by the VAD/merge
  pipeline into one utterance spanning a real gap where nothing was
  actually being captured - a correctness bug, not just a cosmetic one.
- New hotkey binding (`hotkeys.mic_sleep_toggle` or similar - a single
  toggle, not separate sleep/wake bindings, matching the story's "a
  global hotkey pauses... and later resumes it" framing) and sound cues
  for sleep and wake.
- Sleep must not interrupt an in-flight backend request or TTS response -
  toggling sleep only affects whether *new* audio is captured going
  forward; it must not cancel `Orchestrator`'s current turn (per the
  story's boundary). Since sleep only touches `AudioInput`/the mic
  stream, and the current turn's audio was already captured and handed
  off before sleep was toggled, this should fall out naturally rather
  than needing explicit coordination - confirm this with a test.

Out of scope:

- Any automatic (non-hotkey-triggered) use of this pause/resume mechanism,
  in particular pausing the mic during Jarvis's own speech as an
  echo-mitigation. That is a distinct cross-module control path
  (Orchestrator commanding AudioInput, not a user privacy action) and is
  an explicit open decision for task-10, not assumed here.
- Any change to VAD thresholds, chunking, or merge logic.
- Visual/GUI indication of sleep state (sound cues only, per the story).

## Dependencies

`bus.py` (task-01), `config.py` (task-02), `audio_in.py` (task-04 - this
task modifies it directly).

## Acceptance criteria

Automated tests (fakes/mocks for hardware, no real microphone needed):

- Toggling to asleep stops new utterances from being published even
  though the fake stream has queued/available data - its `read` method is
  simply never called while asleep (not "the stream keeps producing data
  and we discard it": once `.stop()` is called, a real stream would not
  be producing anything - the fake should reflect that reads don't
  happen, not that production continues and is ignored).
- The mic loop does not busy-poll while asleep: a test with a short
  timeout confirms the loop is genuinely blocked/waiting, not spinning
  (e.g. assert the fake stream's read call count stays flat for the
  whole sleep duration, or use a fake awake-event and confirm the loop
  doesn't proceed past it).
- Waking resumes capture on the *same* stream instance (fake stream
  object identity check), not a newly constructed one.
- The buffer is empty/reset immediately after a sleep transition -
  audio captured before sleep never merges with audio captured after a
  subsequent wake into one utterance (construct a fixture: speech, sleep,
  gap, wake, more speech - confirm two separate utterances, not one).
- Config parsing test for the new hotkey binding, following existing
  style.

Manual handoff (microphone/hotkey-dependent, human runs and reports):

- Exact command/script to toggle sleep and wake via the real hotkey;
  confirm speaking while "asleep" produces no utterance and no response,
  the sleep/wake cues play at the right moments, and speaking again after
  wake works normally with reasonable latency (no noticeable extra delay
  from reusing the stream vs. reconstructing it).
- If Windows exposes a microphone-in-use indicator, confirm it reflects
  the sleep state (off while asleep) - a direct check that capture is
  genuinely paused at the device level, not just at the application
  level.
