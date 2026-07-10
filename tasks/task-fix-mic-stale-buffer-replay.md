# Task: Fix stale audio buffer replay after a microphone stall

Status: Completed.
Bug report: `tasks/bug_reports/stale-audio-buffer-replay-after-mic-stall.md`

## Summary

Make microphone pause/resume hygiene in `audio_in.py` deterministic
instead of dependent on `stream.read()` returning, so audio buffered
before a pause (including across a hardware-mute stall) can never be
published as a fresh utterance after resume. Additionally reduce the
post-response busy cooldown from `request_end_pause_seconds` (2.0 s) to a
new configurable value defaulting to 1.0 s.

## Boundary

In scope:

- `audio_in.py`: stop the active stream when entering pause/sleep;
  invalidate the buffer on every pause; discard read data that spans a
  pause boundary; tolerate a read exception caused by the pause stop.
- `config.py` / `config.example.toml`: `[vad] resume_cooldown_seconds`
  (default 1.0).
- `main.py`: wire the new cooldown into `finish_turn()`; update the
  now-obsolete cooldown rationale in the `finish_turn()` docstring.
- Pure tests with fake streams covering: pause interrupts a blocked read;
  data read across a pause is discarded; a stalled-read buffer is dropped
  on resume instead of replayed (the live 34 ms signature); the exception
  path does not crash the loop.
- Manual handoff for the human: reproduce the muted-mic scenario and
  confirm no spurious turns.

Out of scope:

- `min_utterance_seconds` filtering (deferred, see bug report).
- Echo cancellation.
- `stream.abort()` migration (fallback option only if the manual check
  shows `stop()` hanging on a muted device).

## Acceptance Criteria

- Entering auto-pause or user sleep stops the active stream so a pending
  `stream.read()` is interrupted.
- Any data returned by a read that started before a pause is discarded
  together with the buffered audio; nothing buffered before a pause can
  be published after resume.
- A read exception raised because the pause stopped the stream is treated
  as a pause, not a crash; genuine device errors still propagate.
- `finish_turn()` cooldown uses `[vad] resume_cooldown_seconds`
  (default 1.0 s), configurable like its sibling VAD settings.
- Existing sleep/wake and shutdown tests remain green.
- `python -m pytest` passes.
- Human manual check: with the reproduction scenario (mute mid-session),
  no spurious turns and no `listening -> thinking` sub-100 ms signature.
