# Interrupt hotkey handoff

Tasks: `tasks/done/task-v1.7.0-2-interrupt-hotkey-and-cancellation-core.md`
and `tasks/task-v1.7.0-5-docs-and-release-verification.md`.

Hardware-dependent (global hotkey, speakers, microphone) - human-run, not
CI. Automated tests already cover the cancellation logic itself
(`tests/test_tts.py`'s `cancel()` tests, `tests/test_main.py`'s
`cancel_active_turn`/`_on_interrupt_requested` tests,
`tests/test_interrupt_input.py`); this checks the real end-to-end path:
a physical keypress actually reaching a live turn.

Default binding: `ctrl+alt+i`. Override via `[hotkeys] interrupt = "..."`
in `config.toml` if it conflicts with something else on your machine.

## Steps

```powershell
python -m jarvis --status-console
```

1. Open the Journal tab as well as the Status tab.
2. Ask Jarvis for a long, structured spoken answer (for example, a numbered
   explanation with many items). Press `ctrl+alt+i` after it has started
   speaking but while it is still producing later text. This exercises an
   interrupt during active backend token generation, not only after it has
   finished generating.
3. Confirm: speech stops promptly (not "finishes the current sentence then
   stops" - it should cut off mid-word or mid-sentence); the Status Console
   returns to listening; and the system log/events panel shows the turn
   completing rather than staying stuck.
4. Confirm in the live Journal, without restarting Jarvis: the interrupted
   turn appears immediately and its outcome is shown as interrupted.
5. Repeat with a long answer, pressing `ctrl+alt+i` during speech playback.
   Confirm the same stop, listening-state, and live-Journal outcome behavior.
6. Repeat with the hotkey during the "thinking" phase, before any audio
   starts. Confirm the request is cancelled, Jarvis returns to listening
   without speaking, and the interrupted Journal entry appears live with the
   interrupted outcome.
7. Ask a new question. Confirm it is answered normally after every interrupt
   scenario.
8. Press `ctrl+alt+i` while Jarvis is idle (not speaking or generating).
   Confirm nothing happens - no cue, no Journal entry, no log entry, and no
   error.

## Report

- Whether interruption was prompt for active generation, speech playback,
  and thinking (rough latency in your own words - "instant", "a noticeable
  beat", etc.).
- For each interruption scenario: whether the Journal entry appeared live
  immediately and showed the interrupted outcome.
- Whether a following turn worked normally after each interrupt.
- Whether the idle press (step 8) was truly silent.
- Anything that felt wrong: a stray sound cue, a console state that
  looked stuck, a crash, or a log error.
