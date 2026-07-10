# Bug report: stale audio buffer replays as a fresh utterance after a mic stall

Detected at commit: fcfa507 (main, after v1.2.9 TTS review fixes merge).

## Symptoms

Reproduced live 2026-07-10 with a hardware-muted microphone (device mute
button pressed after the first spoken turn, never released):

- Spurious turns keep firing while the mic is muted (requests reach the
  LLM, responses are spoken aloud).
- The characteristic signature is `listening -> thinking` within ~35 ms
  in the log (observed at 19:39:55.439 -> .473, and twice in an earlier
  session). Fresh audio cannot produce this: after resume the loop reads
  300 ms blocks and the `still_extending` guard requires
  `request_end_pause_seconds` (2.0 s) of buffered trailing silence before
  publishing, so the earliest legitimate publish is ~2 s after resume.

## Suspected cause

All capture-state hygiene in `run_microphone_loop()` (audio_in.py) - the
`_awake` check, buffer reset, `stream.stop()` - runs only at the top of a
loop iteration, i.e. only after `stream.read()` returns. A hardware-muted
(or otherwise stalled) device stops delivering frames, so the loop hangs
inside `stream.read()` indefinitely:

1. `auto_pause_for_speech()` only clears an `asyncio.Event`; the blocked
   loop never observes it. The pause branch never runs, so the buffer
   (still holding the user's pre-mute speech and trailing silence) is
   never cleared and the stream is never stopped.
2. `finish_turn()` later sets the event back and clears `busy` - again
   unobserved.
3. When frames eventually arrive (device unmuted, USB hiccup recovery, or
   the shared PortAudio machinery being kicked by cue playback - which
   would explain the exact coincidence with the `listening` cue), the
   read returns, the chunker sees old speech with a long silent tail, and
   publishes it instantly. `busy` is already False, so the stale
   utterance is accepted as a fresh turn.

A milder variant needs no stall at all: a read that was already in flight
when the pause hit returns normally and its data is processed as if
awake (this is even documented in
`test_sleep_resets_buffer_so_pre_sleep_audio_never_merges_with_post_wake_audio`
as the "leaked read"). Today that data is merely too short to confirm an
utterance; nothing guarantees it stays harmless.

## Decision

Fix in `audio_in.py` (see `tasks/task-fix-mic-stale-buffer-replay.md`)
rather than adding a minimum-utterance-duration filter: the replayed
utterance is full-length real speech, so a duration threshold would not
catch it. Chosen mechanism, three layers:

1. Entering the paused/sleep state actively stops the active stream (the
   same mechanism `AudioInput.stop()` already uses for shutdown), so a
   blocked `read()` is interrupted and the pause branch runs
   deterministically.
2. A `_buffer_invalidated` flag set on every pause: whatever `read()`
   returns across or after a pause boundary is discarded together with
   the accumulated buffer, instead of being processed. This covers the
   worst case where even `stop()` fails to unblock a stalled read.
3. A read exception while not awake is treated as the pause interrupting
   the read, not as a device failure.

Alternatives considered:

- `min_utterance_seconds` config filter: does not address the cause (see
  above); deferred.
- `stream.abort()` instead of `stop()` for the pause path: PortAudio's
  abort discards pending buffers and cannot block waiting for them, which
  is theoretically safer for a stalled device, but `stop()` is the
  mechanism already verified live for shutdown and keeps the
  `InputStreamLike` protocol unchanged. If the manual check shows
  `stop()` hanging on a muted device, switch the pause path to `abort()`.

## Future considerations

- The `listening -> thinking` ~35 ms signature is a useful canary; if it
  ever reappears in logs, buffer hygiene regressed.
- Echo cancellation is still not attempted (v1.0 decision); the busy-flag
  cooldown in `finish_turn()` is reduced to a configurable
  `resume_cooldown_seconds` (default 1.0 s) since the mic pause is now
  deterministic and the buffer is invalidated on every pause, so the
  cooldown no longer needs to mirror `request_end_pause_seconds`.
