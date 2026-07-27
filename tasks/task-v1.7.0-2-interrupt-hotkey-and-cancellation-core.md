# Task v1.7.0-2: Interrupt hotkey and cancellation core

**Status:** Implemented, automated tests green. Awaiting the human-run
end-to-end handoff (`tasks/interrupt-hotkey-handoff.md`) before closing.
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
      backend stream within a short, measured latency. *(implemented;
      real-hardware latency is the human handoff's job)*
- [x] `_busy` always clears after an interrupt and a following turn is
      accepted normally - proven by an automated regression test, not
      only manual observation
      (`test_interrupt_while_busy_cancels_tts_and_backend_and_resumes_listening`,
      `test_cancel_active_turn_cancels_the_in_flight_backend_call`).
- [x] Pressing the hotkey while Jarvis is not speaking or generating is
      a no-op (`test_interrupt_while_idle_is_a_no_op`).
- [x] `python -m pytest` and Ruff checks are green; the end-to-end
      hotkey check is a prepared human-run handoff with exact steps
      (`tasks/interrupt-hotkey-handoff.md`).

## Implementation notes

- `src/jarvis/inputs/interrupt.py` - new `InterruptRequested` event and
  `run_hotkey_listener()`, mirroring `clipboard.py`'s shape exactly (bus
  publish only, no direct access to Orchestrator/TtsOutput).
- `src/jarvis/audio/tts.py` - `OrderedPlayback.cancel()` (flag stops
  anything still queued from playing) and `TtsOutput.cancel()`.
  **Real bug found and fixed during implementation, not just anticipated
  by the task card**: cancelling a synthesis task before it calls
  `submit()` for its index leaves `OrderedPlayback._next_index` stuck
  forever, since every later unit (this turn's and *all future turns'*,
  since indices only ever increase) waits for an index that will never
  arrive - silently killing all speech for the rest of the session, not
  just the interrupted turn. Fixed by having `cancel()` replace
  `self._playback` with a fresh `OrderedPlayback` (and reset
  `self._next_index` to match) rather than trying to make every
  cancelled task still submit its gap. `TtsOutput._pending_tasks` is
  reset the same way, for the same reason (a stale cancelled task
  otherwise poisons the *next* turn's `wait_for_pending()` with an
  unrelated `CancelledError`). See `tts.py`'s `cancel()` docstring and
  `test_cancel_does_not_wedge_a_later_turns_playback`.
- `src/jarvis/app.py` - `Orchestrator._active_chat_task` +
  `cancel_active_turn()`; `_start_turn()` split into itself (turn setup)
  and `_dispatch_backend_request()` (the cancellable dispatch, extracted
  to keep cyclomatic complexity under Ruff's C901 limit); `_start_turn()`
  now wraps `self._backend.chat(...)` in an `asyncio.Task` and treats its
  own `CancelledError` as "return quietly, the interrupt handler owns
  cleanup" rather than touching `_busy` itself. `_on_interrupt_requested()`
  is the cleanup sequence, subscribed to `InterruptRequested` in `wire()`
  and wired via a new `run_interrupt_hotkey_listener()` background task in
  `run_with_status_console()`.
- `HotkeySettings.interrupt = "ctrl+alt+i"`, documented in
  `config.example.toml`.
- Existing busy-gating tests in `tests/test_main.py` needed one extra
  `await asyncio.sleep(0)` each: wrapping the backend call in a real
  `asyncio.Task` means `chat()`'s body now starts one event-loop tick
  later than a direct `await` did (verified empirically, not guessed) -
  an accurate, unavoidable timing change from the feature itself, not a
  regression to work around.

## Post-implementation review (2026-07-26): two more real races found

An independent review of the first implementation found two genuine
races beyond what the task card anticipated, plus confirmed the
speech-buffer gap below. All three are fixed and covered by new
regression tests; verified each one actually reproduces against the
pre-fix code, not just inferred from reading.

- **Finding 1 - interrupt racing normal completion.**
  `OllamaBackend.chat()` publishes `ResponseComplete` while its own task
  is still technically active, and `_on_full_response_complete()` can
  still be awaiting trailing TTS (`wait_for_pending()`) when a hotkey
  interrupt lands. Both paths used to independently clear busy, publish
  `TurnCompleted`, and play a cue - worse, `_on_full_response_complete`
  could go on to record history for a turn the interrupt had already
  ended, potentially against state a *new* turn had since started using.
  Fixed with `Orchestrator.claim_turn_end()`: an atomic (no `await`
  between check and set) single-use gate both
  `_on_full_response_complete()` and the new shared `_cancel_current_turn()`
  must pass before doing anything else. Deliberately does not itself
  touch busy/mic/`TurnCompleted` - the winner still runs the existing
  `finish_turn()` sequence exactly as before, so the many pre-existing
  tests that call `finish_turn()` directly needed no changes. See
  `test_interrupt_racing_full_response_complete_only_finishes_once` and
  `test_stale_response_complete_after_interrupt_is_a_no_op` (both
  orderings of the race).
- **Finding 2 - interrupt before `_active_chat_task` exists.**
  `_start_turn()` sets `_busy = True`, then awaits journal/bus/cue work
  *before* `_dispatch_backend_request()` creates `_active_chat_task`. An
  interrupt landing in that window found `cancel_active_turn()` with
  nothing to cancel, so `_start_turn()` went on to dispatch the backend
  call anyway - right after `_cancel_current_turn()` had already told the
  rest of the app the turn was over. Fixed with a latched
  `Orchestrator._interrupt_requested` flag: `cancel_active_turn()` now
  always sets it (in addition to cancelling the task if one exists), and
  `_dispatch_backend_request()` checks it before dispatching anything,
  skipping the call entirely if set. See
  `test_interrupt_before_backend_dispatch_prevents_the_call_entirely`.
- **Finding 3 - `TtsOutput.cancel()` left `_units` untouched.**
  `SpeechUnitBuffer` carries an unterminated sentence across `on_token()`
  calls by design (a sentence split across streamed tokens still buffers
  correctly) - but `cancel()` reset `_playback`/`_pending_tasks` without
  resetting `_units`, so an interrupted turn's dangling partial sentence
  got concatenated onto the *next* turn's first tokens and spoken as one
  unit. Fixed by also replacing `_units` with a fresh `SpeechUnitBuffer`
  in `cancel()` (not via `flush()`, which returns units meant for
  playback - exactly what must not happen for an interrupted turn's
  leftovers). Verified the regression test actually catches this: ran it
  against the pre-fix code first and confirmed it failed with the exact
  concatenated text, not just a passing test taken on faith. See
  `test_cancel_resets_the_speech_unit_buffer`.

## Second review round (2026-07-26): the round-1 fix for finding 1 broke the feature

A second independent review, run against the round-1 fixes above, found
that the `claim_turn_end()` fix for finding 1 introduced a worse bug than
it solved, plus a second gap in the finding-2 fix. Both confirmed by
reverting the fix and rerunning the new test before trusting it.

- **Finding 1, round 2 - gating `tts_output.cancel()` on `claim_turn_end()`
  silently broke the hotkey for the most common case.** Round 1's fix
  made `_cancel_current_turn()` check `claim_turn_end()` *before* doing
  anything else, including stopping TTS. But `EventBus.publish()`
  (`core/bus.py`) awaits every subscriber via `gather()` before
  returning, so `OllamaBackend.chat()`'s own task stays "in flight" for
  as long as `_on_full_response_complete()` takes to run - including its
  `wait_for_pending()` wait for trailing speech. `_on_full_response_complete()`
  claims the turn first almost every time a real answer is more than one
  sentence, since it starts running the instant generation finishes,
  well before a human can physically react and press a key. Once it had
  claimed, `_cancel_current_turn()`'s claim attempt always lost and
  returned before calling `app.tts_output.cancel()` at all - the hotkey
  did nothing while Jarvis read out an answer, which is the single most
  common moment someone wants to interrupt. Confirmed by reverting the
  fix: the existing test's own `cancel_calls == 0` assertion is what had
  been silently locking the broken behavior in.

  Fixed by decoupling "stop now" from "who does the bookkeeping":
  `_cancel_current_turn()` cancels the backend task and TTS unconditionally
  whenever busy, *then* attempts `claim_turn_end()` - losing the claim
  only skips `finish_turn()`/`TurnCompleted`/the cue, which the
  already-running normal path still owns. This works because cancelling
  the same pending tasks `wait_for_pending()` is gathering makes that
  `gather()` raise `CancelledError`, and `bus.py`'s `publish()`
  deliberately re-raises a subscriber's `CancelledError` rather than
  swallowing it - so the normal path's own `finally` still runs promptly
  instead of waiting out the rest of the speech.

  That surfaced a second, smaller gap: when `wait_for_pending()` raises
  `CancelledError` this way, it isn't caught by `_on_full_response_complete()`'s
  `except Exception:` (`CancelledError` is a `BaseException`), so it
  skipped the trailing `await app.sound_cues.play("listening")` entirely
  - the turn ended correctly (busy cleared, `TurnCompleted` published via
  `finally`) but with *no* cue from either path. Added a dedicated
  `except asyncio.CancelledError: pass` branch (falls through to the
  same `finally` + listening-cue path a normal completion takes) rather
  than reworking the existing error-cue structure. See the rewritten
  `test_interrupt_racing_full_response_complete_only_finishes_once`
  (verified failing against the reverted fix first) and its docstring.
- **Finding 2, round 2 - the round-1 fix stopped the backend call but not
  `_start_turn()`'s other side effects.** `_dispatch_backend_request()`'s
  `_interrupt_requested` check (round 1) only guards the backend
  dispatch. An interrupt landing earlier - during the journal-recording
  await, before `_dispatch_backend_request()` even runs - let `_start_turn()`
  go on to publish `TurnAccepted` and play the "thinking" cue *after*
  `_cancel_current_turn()` had already published `TurnCompleted`: a
  UI-visible `TurnCompleted -> TurnAccepted` with nothing to follow,
  since the backend call itself was still correctly skipped, leaving the
  console showing THINKING indefinitely. Fixed with two more
  `if self._interrupt_requested: return` checks in `_start_turn()`, right
  after the journal-recording block and right after the `TurnAccepted`
  publish - both real windows the flag can be set in. Extended
  `test_interrupt_before_backend_dispatch_prevents_the_call_entirely`
  (rather than adding a near-duplicate test) to assert `TurnAccepted`
  and the "thinking" cue never fire, and confirmed it fails without the
  fix.

## Human handoff run (2026-07-27): passed, with one real finding

The owner ran `tasks/interrupt-hotkey-handoff.md` on real hardware: "Всё
проверил. Всё работает по сути." (hotkey stops TTS/backend promptly,
returns to listening, a following turn works normally, idle press is a
no-op) - the `sd.stop()`/shared-playback-lock stop condition below did
not trigger.

One real gap surfaced from live use, not from the scripted steps:
**interrupting during the "thinking" phase, the just-spoken voice
request did not appear in the live Journal panel** (it *did* appear
after restarting Jarvis, i.e. re-reading the store fresh - so this was
never data loss). Root-caused and fixed rather than assumed:

- `JournalRecorder.record_voice_user()`/`record_text_user()` schedule
  their actual disk write as a background task
  (`JournalRecorder._schedule()`) rather than blocking on it; the live
  Journal panel updates off `JournalEventAppended`
  (`ui/transport.py:786`), published only once that background task
  completes.
- Confirmed empirically with a direct reproduction (real
  `JournalRecorder`, temp store, no fakes): immediately after
  `_cancel_current_turn()` returned, 0 of 1 pending journal tasks had
  completed and `JournalEventAppended` had not fired yet. A normal turn
  never showed this because generation + TTS take several seconds,
  plenty of time for the background write to finish first - an interrupt
  during "thinking" can end a turn in a fraction of a second, well
  before that write completes.
- Fixed at the point both completion paths already converge -
  `Orchestrator.finish_turn()` - rather than patching
  `_cancel_current_turn()` alone: `finish_turn()` now awaits
  `journal_recorder.wait_for_pending()` first (when a recorder is
  configured), so the fix is symmetric for both the interrupt and the
  normal-completion path without duplicating it in each caller. This was
  a deliberate architectural call (owner's steer, not the first
  instinct) - the initial plan was to patch only `_cancel_current_turn()`,
  which would have left the identical latent race in
  `_on_full_response_complete()`'s path, just still masked by turn
  duration there.
- Re-ran the same direct reproduction against the fix: `JournalEventAppended`
  pushed = 1 and `recorder._tasks` empty immediately after
  `_cancel_current_turn()` returns. See
  `test_finish_turn_waits_for_pending_journal_writes` (confirmed failing
  against the reverted fix first, same discipline as every other
  regression test in this card).

## Stop conditions

- Stop if cancelling `self._backend.chat(...)`'s task does not propagate
  cleanly through `iter_chat()`'s `finally` block (e.g. leaves the
  `httpx` connection/session in a bad state) - that is a wider
  backend-layer problem needing its own decision, per the story's stop
  condition. *(not triggered: `FakeBackend`/real `OllamaBackend` both
  rely on the same `finally`-guarded async-generator shape; automated
  tests exercise the fake, the human handoff exercises the real one.)*
- Stop if `sounddevice.stop()` interrupts unrelated audio sharing the
  same output stream (e.g. a sound cue mid-playback) in a surprising or
  unsafe way - verify the interaction with `TtsOutput`/`SoundCuePlayer`'s
  shared playback lock before shipping, do not assume it is fine.
  *(verified live in the 2026-07-27 handoff run above - not triggered.)*
