# Task: v1.1 main wiring, config, and manual handoff (main.py)

Status: Completed.

Real hotkeys, wiring, config, and sound cues landed for clipboard input
(task-08) and microphone sleep (task-09). Open decision resolved: yes,
Orchestrator auto-pauses the mic during Jarvis's own speech, layered on
the existing busy-cooldown mitigation.

Manual testing (human) found two real issues, both fixed:
- No logging was configured anywhere in the process, so INFO-level
  messages (including sound-cue activity) were silently dropped.
  `run()` now calls `logging.basicConfig(level=INFO, ...)`, and cue
  playback / mic sleep-wake transitions log an INFO line.
- The `input_error` cue was a single short/quiet tone and not reliably
  audible; redesigned as two blips, matching the other v1.1 cues.

Code review then found three real bugs in the echo-mitigation feature,
all fixed with regression tests confirmed to fail without the fix and
pass with it:
- P1: a single `is_awake` bit could not represent "user wants privacy"
  and "Jarvis is auto-pausing for its own speech" independently, so a
  hotkey press during auto-pause could be misread, and finish_turn()
  could wake a mic the user had put to sleep independently. Fixed by
  giving `AudioInput` two separate flags (user-requested vs internal
  auto-pause) ANDed into the actual capture state; `Orchestrator` no
  longer reasons about the user's own state at all.
- P2: the hotkey callback decided sleep-vs-wake from a stale read of
  `is_awake` in the keyboard package's own thread, so two rapid presses
  could schedule the same action twice instead of toggling twice. Fixed
  by moving the decision into `AudioInput.toggle_user_sleep()`, run
  entirely on the event loop.
- P2: the internal auto-pause was publishing `MicSleepToggled` and
  playing the privacy sound cues on every spoken response. Fixed - only
  the user-triggered `toggle_user_sleep()` publishes that event now.
- P3 (test-only): a hotkey-listener test task was left uncancelled, and
  a later test had a redundant duplicate cancel/await block. Both fixed.

Final state: 138/138 automated tests passing; full manual handoff
(clipboard hotkey, mic sleep/wake hotkey, all v1.1 sound cues, normal
voice turn, echo-mitigation behavior, offline-after-setup) confirmed by
the human.

Story: [story-v1.1-controlled-input.md](story-v1.1-controlled-input.md)

## Summary

Wires task-08's clipboard input and task-09's microphone sleep mode into
`main.py`'s `build_app()`/`wire()`, adds their config validation and
remaining sound cues, and runs the full v1.1 manual handoff - the same
role task-07 played for v1.0's modules.

## Current boundary

In scope:

- Add the actual global-hotkey listener for clipboard submission to
  `clipboard_input.py` (task-08 deliberately left this out - see its
  scope boundary note): a `run_hotkey_listener`-shaped function, mirroring
  `capture.py`'s, that binds `hotkeys.clipboard_submit` via `keyboard` and
  publishes the `ClipboardSubmitted` event task-08 already built.
- Register that listener and `audio_in.py`'s new sleep/wake hotkey
  listener as background tasks in `main.py`'s `run()`, and their bus
  subscriptions in `build_app()`/`wire()` - same pattern as `capture.py`'s
  listener in task-07 (started in `run()`, cancelled and awaited in
  `run_until_shutdown()`).
- `config.example.toml` entries for every new v1.1 field (`clipboard.
  max_chars`, the new hotkey bindings, the new sound cue paths), matching
  `config.py`'s existing strict style and keeping the file in sync with
  the schema task-08/task-09 already added.
- Update the system prompt if needed to mention that input may now arrive
  as pasted text, not only as a spoken question with optional screenshot -
  decide during implementation whether this is necessary for response
  quality; not assumed here.
- Full v1.1 manual handoff: clipboard hotkey, mic sleep/wake hotkey, all
  new sound cues, end-to-end with live Ollama/TTS, offline-after-setup
  confirmed (no new network dependency introduced).

## Open decision: should Jarvis pause its own microphone while speaking?

Task-09 builds a user-triggered mic sleep/wake mechanism for privacy.
PROJECT.md's Roadmap item 7 (real echo cancellation) and the existing
`Orchestrator.finish_turn()` cooldown mitigation both exist because Jarvis
currently has no way to avoid hearing its own TTS output through the
microphone. Once task-09 ships a real pause/resume primitive on
`AudioInput`, it becomes possible for `Orchestrator` to call it directly:
pause capture when a turn starts speaking, resume it after the existing
cooldown window.

This is **not** authorized by task-09 alone. It is a materially different
thing from a user pressing a privacy hotkey: it is `Orchestrator`
commanding `AudioInput` automatically, a new cross-module control path
that didn't exist before, layered on top of (not instead of) the current
busy-cooldown mitigation. It is probably the right direction - noticeably
more robust than a delayed-rejection mitigation, likely at fairly low
implementation cost given task-09's primitive already exists - but it
should not be folded into this task silently.

Decide explicitly, only after task-09's user-triggered sleep/wake has
been implemented, manually tested, and confirmed working on its own
terms:

- If yes: implement it here, update PROJECT.md's Roadmap item 7 and the
  echo-cancellation Verified-facts entry to reflect the new mitigation,
  and add a test confirming capture is paused for the correct window
  (turn start through cooldown end) and resumes correctly afterward.
- If no (or deferred): record why in PROJECT.md next to Roadmap item 7,
  and leave task-09's mechanism purely user-triggered for v1.1.

## Dependencies

`task-08-clipboard-input.md`, `task-09-microphone-sleep-mode.md`, and all
of v1.0's task cards (`main.py`'s existing `build_app()`/`wire()`).

## Acceptance criteria

Automated tests (fakes/mocks for hardware-touching modules):

- A test for `clipboard_input.py`'s new hotkey-listener function itself,
  using a fake `keyboard` module (same technique as `capture.py`'s
  `test_hotkey_listener_registers_bindings_from_config`): confirms the
  binding comes from config and the callback publishes
  `ClipboardSubmitted`.
- A wiring test confirms the new clipboard and mic-sleep hotkey listeners
  are started as background tasks and are cancelled/awaited on shutdown,
  same shape as the existing audio/capture wiring test from task-07.
- Config parsing test confirms all new v1.1 fields validate per the
  established style, and `config.example.toml` round-trips.

Manual handoff (full hardware stack, human runs and reports):

- Exact command to launch the assembled v1.1 process.
- Script covering: clipboard hotkey with real text/code, mic sleep/wake
  hotkey, all sound cues (clipboard submit, sleep, wake, input error, plus
  the existing listening/thinking/speaking/error from v1.0), and a normal
  voice turn still working unchanged.
- Confirm the process remains fully offline after one-time setup - no new
  network dependency was introduced by clipboard or mic-sleep.
- If the "Open decision" above was resolved as "yes": confirm Jarvis's
  own speech is no longer picked up as a self-triggered turn, and that a
  genuine user utterance spoken shortly after Jarvis finishes still works
  correctly (capture must have resumed by then).
