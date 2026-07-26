# Task v1.7.0-2: Interrupt hotkey and cancellation core

**Status:** Proposed.
**Story:** `tasks/story-v1.7.0-barge-in.md`
**Depends on:** `tasks/done/task-v1.7.0-1-aec-spike.md` (completed; drove
the pivot to a hotkey as the primary mechanism). Gates task 4
(experimental voice barge-in), which reuses this task's cancellation
core with a different trigger.

## Summary

The primary interruption mechanism: a global hotkey that cancels
in-flight TTS playback and the in-flight backend stream, clears the busy
flag, resumes the mic, and returns Jarvis to listening - on any
hardware, with no acoustic detection at all. This is the shared
cancellation core; task 4's experimental voice option triggers the same
mechanism from VAD-during-playback instead of a keypress.

## Context you need

- The story's pivot note and "Both mechanisms share one cancellation
  core" design decision.
- `Orchestrator._start_turn()` (`src/jarvis/app.py:499`) `await
  self._backend.chat(...)` directly (around line 587) - not wrapped in a
  cancellable `asyncio.Task` today.
- **`CancelledError` is a `BaseException`, not an `Exception`.** The
  `except Exception:` around that call (line 590) does not catch it, so
  a bare `task.cancel()` today would leave `_busy` stuck `True` forever
  and Jarvis would silently ignore every later turn ("previous request
  still in flight"). This must be handled explicitly.
- `_on_full_response_complete()` (`src/jarvis/app.py:951`) is the
  normal-path turn-completion sequence: flush trailing TTS, record
  history, wait for all pending speech, `Orchestrator.finish_turn()`,
  publish `TurnCompleted`, play the "listening" cue. An interrupt needs
  an equivalent cleanup sequence that runs *instead of* this one for the
  interrupted turn - a race where both run is a real risk to design
  against, not an edge case to discover later.
- `TtsOutput` has no cancellation path today: `OrderedPlayback.submit()`
  (`tts.py:291`) always eventually plays every submitted unit in order;
  `wait_for_pending()` (`tts.py:363`) is the opposite of what is needed
  (waits for completion, for graceful shutdown). `_default_play()`
  (`tts.py:456`) does `sd.play()` + `sd.wait()`;
  `sounddevice.stop()` halts whatever is currently playing on the
  default stream immediately - the natural primitive here.
- `TtsOutput` and `SoundCuePlayer` deliberately share one playback lock
  so a sound cue can never physically overlap spoken TTS (see
  `tts.py`'s `TtsOutput.__init__` docstring and PROJECT.md). Verify
  `sounddevice.stop()` interacts safely with that shared lock rather
  than assuming it does.
- Hotkey wiring precedent: `HotkeySettings` (`config.py:114`) holds
  `ctrl+alt+<letter>` bindings. Every existing hotkey except `shutdown`
  (registered inline in `build_app()`, a control-plane-critical
  exception) has its own `run_*_hotkey_listener()` async function added
  to `background_tasks` in `run_with_status_console()`
  (`app.py`, the list around lines 1279-1295), publishing a bus event
  that `wire()` subscribes to. Follow that majority pattern unless there
  is a concrete reason not to - `hotkeys.py`'s own documented rule is
  that the callback thread must never decide engine state itself, only
  marshal to the event loop.
- The story's "What is already known" section already established that
  wrapping `self._backend.chat(...)` in an `asyncio.Task` and cancelling
  it should propagate cleanly through `OllamaBackend.iter_chat()`'s
  `finally` block (`dialog/backend.py`); this task turns that plan into
  real code and tests the assumption for real.

## Boundary

- New hotkey only. No acoustic detection, no VAD-during-playback, no new
  config option - that is task 4's job, built on top of whatever this
  task ships.
- The interrupted turn's fate in history/journal is task 3's job. This
  task's minimum bar is narrower: `_busy` clears, the mic resumes,
  Jarvis returns to listening - it must not leave the app stuck. A
  minimal placeholder for history (e.g. not calling
  `ConversationHistory.add()` for a cut-short turn) is acceptable here
  and is expected to be revisited by task 3, not perfected now.
- No change to the mic-sleep/privacy toggle contract or its hotkey.

## Requirements

- New `HotkeySettings.interrupt` field (proposed default `ctrl+alt+i`,
  following the existing convention and not colliding with the five
  current bindings), plus `config.example.toml` documentation.
- A cancellation path through `OrderedPlayback`/`TtsOutput` that stops
  the currently-playing unit immediately and prevents any
  already-scheduled unit from starting playback afterward.
  Already-running synthesis tasks may be left to finish quietly or
  cancelled outright - author's call, record which and why.
- `Orchestrator._start_turn()`'s backend call wrapped in a cancellable
  `asyncio.Task`, with an interrupt handler that cancels it and awaits
  the cancellation cleanly - no unhandled `CancelledError` escaping to
  the event loop's default handler, no lingering task.
- An interrupt cleanup sequence, run instead of
  `_on_full_response_complete()`'s normal path for the interrupted turn:
  clears `_busy`, resumes the mic (`Orchestrator.finish_turn()` or
  equivalent), publishes `TurnCompleted`, plays a cue (reusing the
  existing "listening" cue is acceptable; a dedicated cue is a
  nice-to-have, not required here).
- The hotkey is a no-op - not an error, not a crash - when pressed while
  Jarvis is not speaking or generating.
- Automated tests: hotkey binding/parsing (pure, matching `hotkeys.py`'s
  existing test style), the cancellation sequence's ordering and
  idempotency against fakes (no real backend/audio, per the project's
  Testing protocol boundary for pure logic), and a regression test
  proving `_busy` cannot get stuck `True` after an interrupt.
- Human-run manual handoff: press the hotkey mid-response, confirm TTS
  stops promptly, Jarvis returns to listening, and a following turn
  works normally.

## Acceptance criteria

- [ ] Pressing the hotkey mid-response stops TTS playback and the
      backend stream within a short, measured latency.
- [ ] `_busy` always clears after an interrupt and a following turn is
      accepted normally - proven by an automated regression test, not
      only manual observation.
- [ ] Pressing the hotkey while Jarvis is not speaking or generating is
      a no-op.
- [ ] `python -m pytest` and Ruff checks are green; the end-to-end
      hotkey check is a prepared human-run handoff with exact steps.

## Stop conditions

- Stop if cancelling `self._backend.chat(...)`'s task does not propagate
  cleanly through `iter_chat()`'s `finally` block (e.g. leaves the
  `httpx` connection/session in a bad state) - that is a wider
  backend-layer problem needing its own decision, per the story's stop
  condition.
- Stop if `sounddevice.stop()` interrupts unrelated audio sharing the
  same output stream (e.g. a sound cue mid-playback) in a surprising or
  unsafe way - verify the interaction with `TtsOutput`/`SoundCuePlayer`'s
  shared playback lock before shipping, do not assume it is fine.
