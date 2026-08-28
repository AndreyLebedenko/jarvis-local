# Task v1.8.2-1: Replay core (re-synthesis path, busy-guard, interrupt)

**Status:** Completed.
**Story:** `tasks/story-v1.8.2-replay-tts.md`
**Depends on:** nothing; first implementation card of v1.8.2.

## Summary

Build the non-UI core for replaying a past assistant reply: a single "text
to speak for this turn" accessor over stored replies, a one-shot
re-synthesis + playback path that reuses the existing shared playback
channel, a busy-guard that rejects a replay attempt (beep + error) when
speech is already active, and integration with the existing Ctrl+Alt+I
interrupt so it cancels an in-progress replay. No chat-log UI in this card.

## Context you need

- `tasks/story-v1.8.2-replay-tts.md`: locked decisions - re-synthesis only
  (no stored audio), reject-when-busy (no queue, no second route), Ctrl+Alt+I
  cancels replay, and the forward seam for v1.9.0.
- `src/jarvis/audio/tts.py`:
  - `BilingualTtsEngine.synthesize(text, language)` - the re-synthesis entry
    point.
  - `TtsOutput` - the live-turn path; note `_playback_lock` (a process-wide
    output serializer shared with `SoundCuePlayer`), `cancel()` (the
    task-v1.7.0-2 interrupt), and that `on_token`/`on_response_complete` honor
    `TtsMuteState`. `TtsOutput` is token-stream oriented; replay is a one-shot
    full-text synthesize+play, so it is a sibling path, not a reuse of
    `on_token`.
- `src/jarvis/app.py`:
  - `playback_lock = asyncio.Lock()` (~line 1382), shared into `TtsOutput`
    and `SoundCuePlayer(... playback_lock=playback_lock)` (~1394).
  - The interrupt path `app.tts_output.cancel()` (~1906, ~2050) - where a
    replay-in-progress must also be cancelled.
- `src/jarvis/audio/sound_cues.py`: `SoundCuePlayer` plays a cue under the
  same `playback_lock`; the busy-reject beep is a sound cue.
- `src/jarvis/journal/recorder.py` (`record_assistant`) and
  `src/jarvis/history/recent_history.py` (`ConversationTurn`) - where a past
  assistant reply's text lives, for the accessor to read back per turn.

## Boundary

- Core + wiring only. No Play/Stop control in the status console (task 2), no
  docs/config/user-doc changes (task 3).
- Re-synthesis only. No audio is stored, read, or exported.
- The busy-guard rejects; it never queues and never opens a second playback
  route. Concurrent replay stays out of scope per the story.
- The accessor returns the canonical reply text today. It is the single seam
  v1.9.0 will later point at the mode-3 spoken derivative; this card does not
  add the derivative, only the seam shape.

## Requirements

- Add a `reply_speech_text(turn_ref) -> str | None` accessor (name/module a
  card decision, e.g. `src/jarvis/audio/replay.py`) that reads a past
  assistant reply's stored text for an arbitrary turn, not just the last.
- Add a one-shot replay path that synthesizes that text via
  `BilingualTtsEngine.synthesize` and plays it through the same shared
  `playback_lock` channel, so it can never physically overlap live speech or
  sound cues on the output device.
- Provide a **busy signal that reflects "speech is currently active"** - a
  live turn producing/playing units, or a replay already running - not merely
  whether the per-unit `playback_lock` is held this instant. The lock is
  released between sentences while the turn is not finished, so trylock on the
  lock alone is not a correct "is something playing" test; introduce/consult
  an explicit active-speech flag.
- On a replay attempt while busy: do not play. Emit the busy beep via
  `SoundCuePlayer` and surface a visible error event ("busy") on the event
  bus for the UI/status console to render. Reject is immediate; nothing is
  queued.
- Register the in-progress replay so the existing Ctrl+Alt+I interrupt path
  cancels it alongside (or instead of) a live turn, reusing the current
  cancellation wiring rather than adding a second interrupt owner.
- Replay must never mutate history or the journal.

## Acceptance criteria

- [ ] Tests prove `reply_speech_text` returns the stored reply text for an
      arbitrary past assistant turn (not only the most recent) and `None`
      when the turn has no assistant reply.
- [ ] Tests prove a replay attempt while speech is active is rejected: no
      synthesis/playback occurs, a busy beep is requested, and a visible
      error event is emitted - with the "active" condition covering the gap
      between sentences of a live turn, not just the instant the device lock
      is held.
- [ ] Tests prove a replay attempt while the channel is free synthesizes the
      accessor's text via the TTS engine and plays it through the shared
      playback channel.
- [ ] Tests prove Ctrl+Alt+I's existing interrupt path cancels an
      in-progress replay through the same cancellation wiring, and is safe to
      call when no replay is running.
- [ ] Tests prove replay leaves history and the journal unchanged.
- [ ] `python -m pytest`, `python -m ruff check .`, and
      `python -m ruff format --check .` are green. Actual replay audio and
      the live-turn-vs-replay timing are a prepared human-run handoff with
      exact commands.

## Stop conditions

- Stop if there is no clean, existing signal for "speech is currently active"
  spanning a whole live turn (not just per-unit lock holding), and adding one
  would require reworking the `TtsOutput`/`OrderedPlayback` contract rather
  than reading or adding a small flag alongside it.
- Stop if the Ctrl+Alt+I interrupt path is so turn-scoped that making it also
  cancel a replay requires reworking the cancellation contract instead of
  registering the replay with it.
- Stop if a past turn's reply text cannot be read back per-turn through the
  existing journal/history read path without an expensive or lossy projection
  query.

## Verification

- Focused replay-core, busy-guard, and interrupt-integration logic tests.
- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Human-run handoff: replay audio plays; replay while Jarvis is mid-reply is
  rejected with a beep and error; Ctrl+Alt+I stops a running replay.
