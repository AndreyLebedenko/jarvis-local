# Interrupt hotkey handoff

Task: `tasks/task-v1.7.0-2-interrupt-hotkey-and-cancellation-core.md`.

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

1. Ask Jarvis something that produces a longish spoken answer (a few
   sentences), so there is time to interrupt it mid-speech.
2. While Jarvis is talking, press `ctrl+alt+i`.
3. Confirm: TTS playback stops promptly (not "finishes the current
   sentence then stops" - it should cut off mid-word/mid-sentence).
4. Confirm: the Status Console's state returns to listening (same as
   after a normal turn finishes), and the system log/events panel shows
   the turn completing rather than staying stuck.
5. Ask a new question. Confirm it is answered normally - the interrupt
   must not leave Jarvis unresponsive to further requests.
6. Press `ctrl+alt+i` again while Jarvis is idle (not speaking or
   generating). Confirm nothing happens - no cue, no log entry, no
   error.
7. Repeat step 1-3 but press the hotkey during the "thinking" phase,
   before Jarvis has started speaking at all (right after asking, before
   any audio starts). Confirm the request is cancelled and Jarvis
   returns to listening without ever speaking.

## Report

- Whether playback stopped promptly (rough latency in your own words -
  "instant", "a noticeable beat", etc.) for both mid-speech and
  mid-thinking interrupts.
- Whether a following turn worked normally after each interrupt.
- Whether the idle press (step 6) was truly silent.
- Anything that felt wrong: a stray sound cue, a console state that
  looked stuck, a crash, or a log error.
