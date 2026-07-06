# Bug report: extra unprompted turn observed once during thinking-mode manual test

Commit: HEAD at time of writing is `77cc1f1` (task-12 merge); observed on
the in-progress task-13 branch during its manual handoff (task-13's
`main.py`/`thinking_mode.py` wiring, not yet committed at observation time).

## Symptoms

Human report from `python main.py`, thinking mode enabled via
`ctrl+alt+t`, physical hardware mute button on the microphone engaged:
after a normal thinking-mode turn finished speaking, Jarvis started and
completed a third turn without any deliberate new question, staying on
the same topic as the prior exchange. The human was not confident whether
this was an error, or whose.

Reasoning-token isolation itself was confirmed correct in the same
session (no reasoning reached the spoken answer) - this report is scoped
only to the extra/unprompted turn, not the isolation guarantee.

Relevant excerpt from the reported log (timestamps trimmed to the
relevant window; full log is in the task-13 conversation, not reproduced
here):

```
20:03:19,513 INFO sound_cues: Playing sound cue 'speaking'   <- turn B starts speaking
20:03:43,227 INFO sound_cues: Playing sound cue 'listening'  <- turn B ends
20:03:43,258 INFO sound_cues: Playing sound cue 'thinking'   <- turn C starts, 31 ms later
20:03:43,891 INFO httpx: HTTP Request: POST .../api/chat "200 OK"
20:03:48,069 INFO sound_cues: Playing sound cue 'speaking'
20:04:05,055 INFO sound_cues: Playing sound cue 'listening'  <- turn C ends
```

Every other `listening -> thinking` gap in the same log is several
seconds to several minutes. This one is 31 ms - too short for
`audio_in.py`'s VAD pipeline to capture, merge, and confirm a genuinely
new utterance under the default `config.vad.request_end_pause_seconds`
(2.0 s): confirming an utterance requires that much trailing buffer with
no further speech merged in, per `VadChunker`/`run_microphone_loop()`'s
own logic. No `config.toml` was present for this run, so this default
applied.

## Suspected cause

Not confirmed - no audio recording or VAD-level debug output was
captured, only the cue/HTTP log above. Two candidate explanations, not
mutually exclusive:

1. **Thinking mode measurably widens the window during which
   `AudioInput` stays fully active while a turn is already in flight.**
   `Orchestrator`'s echo mitigation
   (`audio_input.auto_pause_for_speech()`) is called from
   `on_response_token()` - i.e. only once the *first* `ResponseToken`
   arrives. Per task-11's backend contract, `message.thinking` never
   becomes a `ResponseToken`; with thinking enabled, the model spends
   real wall-clock time on reasoning tokens before any content token
   flows (the spike in `tasks/done/task-spike-thinking-mode.md` measured
   161 vs 10 eval tokens for the media case). During that reasoning
   window, `_start_turn()` has already set `_busy = True`, but the mic is
   *not yet* auto-paused - it only pauses once speech starts. This does
   not, by itself, explain a 31 ms gap (any utterance captured and
   rejected during this window is dropped by the busy-guard, not queued
   for later), but it is a real, quantifiable behavioral difference
   thinking mode introduces to the existing self-hearing risk documented
   in PROJECT.md's Verified facts (no echo cancellation in v1.0; task-10's
   mic-pause-during-speech mitigation narrows but does not eliminate it).
2. **A stream-restart artifact or trailing room reverb was misread as a
   completed utterance right at the mic's resume moment.**
   `run_microphone_loop()` calls `stream.start()`/resets its buffer on
   every pause/resume transition (see `audio_in.py`'s module docstring).
   A hardware pop/click on `stream.start()`, or physically decaying
   reverberation from Jarvis's own just-finished TTS output, arriving in
   the very first read block after resume, could be misclassified by
   Silero VAD as speech. This still does not obviously explain the 2.0 s
   confirmation gate being satisfied in 31 ms under the code as written -
   the exact mechanism remains unconfirmed.

The human's physical mute button should have produced silence at the
driver level; whether it was actually engaged for the full window in
question, or whether hardware mute on this device does not guarantee
true digital silence, is also unconfirmed.

## Temporary decision

No code change made. This is explicitly out of scope for the
thinking-mode story (`tasks/done/story-thinking-mode.md`'s boundaries exclude
audio-pipeline changes) and out of scope for task-13 specifically
(main.py wiring only). Real echo cancellation for `audio_in.py` is
already tracked as a separate, deliberately deferred roadmap item
(PROJECT.md's Roadmap after v1.0, item 7) - this report does not change
that prioritization, only adds a data point (thinking mode widens the
pre-auto-pause capture window) worth considering when that item is
picked up.

## Future considerations

- If this recurs, capture VAD-level debug output (segment start/end
  timestamps, buffer duration at evaluation time) alongside the cue log -
  the current log alone cannot distinguish "genuine fast false-positive
  utterance" from "stale confirmed segment surviving a pause transition
  it shouldn't have."
- When roadmap item 7 (real echo cancellation) is picked up, explicitly
  test with thinking mode both on and off, given the widened pre-auto-
  pause window identified above.
- Consider (not decided here) whether `on_response_token()`'s auto-pause
  trigger should instead fire at turn start (`_start_turn()`) rather than
  first spoken token, closing the reasoning-phase gap - this would be a
  behavioral change to task-10's existing mitigation and needs its own
  review given it affects every turn, not just thinking-mode ones.
- Out of scope for this report: the reasoning-token isolation guarantee
  itself, which was confirmed correct in the same manual test session.
