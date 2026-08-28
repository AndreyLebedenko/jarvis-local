# Task v1.8.3-3: Include voice user turns (direct wav playback)

**Status:** Not started.
**Story:** `tasks/story-v1.8.3-sequential-journal-playback.md`
**Depends on:** task-v1.8.3-1 (pausable primitive), task-v1.8.3-2 (sequence
engine).

## Summary

Extend the sequence so a **voice-originated** user request
(`source == "voice"`) plays too - by playing its **original stored `.wav`
directly** from the journal media store through task 1's pausable primitive,
not by re-synthesis. Typed user requests (`source == "text"`) and system
events stay skipped. Generalize the per-event accessor from "reply text" to
"playable source for this event": assistant -> text-to-synthesize, voice
user -> wav media reference, everything else -> `None` (skip). The v1.9.0
forward seam is preserved: the assistant branch still returns text and later
retargets to the mode-3 derivative.

## Context you need

- `src/jarvis/journal/recorder.py`: `record_voice_user` (~44) persists the
  request `.wav` as a media file; the event's `media` tuple carries its
  relative path. `record_text_user` (~72) uses `source == "text"` with no
  media. This is the voice-vs-typed and wav-location basis.
- `src/jarvis/journal/events.py`: `JournalEvent.media` (relative media paths,
  validated) and `source`. `src/jarvis/journal/store.py`: media resolve
  relative to the session dir under `JournalStore.root`.
- `src/jarvis/audio/replay.py`: `reply_speech_text` (~49) - generalize (or add
  a sibling) into a "playable source for this event" accessor; task 1's
  pausable primitive already accepts float32 frames, so decode the wav
  (`soundfile.read`) and feed it through the same path.
- task-v1.8.3-2's `SequencePlayer`: it currently selects assistant records;
  now it selects assistant + voice-user records and dispatches by source
  kind (synthesize vs decode-wav).

## Boundary

- Voice user turns via their stored wav only. No re-synthesis of human turns,
  no TTS normalization, no wav transform, no separate/second voice.
- Typed user requests and system events remain skipped.
- No new transport controls; Pause/Resume/Stop from tasks 1-2 apply to wav
  segments identically (that is why the primitive is source-agnostic).
- Single-reply Play still targets assistant replies only (a Play control on a
  human turn is a UI decision the card may add if trivial, else deferred).

## Requirements

- A "playable source for this event" accessor: given a `JournalEventRecord`,
  return an assistant text unit(s) source, a resolved wav path/bytes for a
  `source == "voice"` user event, or `None` for typed-user/system events.
- The sequence engine plays voice-user segments by decoding the stored wav and
  feeding frames through the pausable primitive, in journal order interleaved
  with assistant segments; skipped events advance silently.
- Guard: a voice event whose wav is missing/corrupt is skipped (not a hard
  error) with a logged warning; the sequence continues.
- Keep the assistant branch returning text so the v1.9.0 seam is intact.

## Acceptance criteria

- [ ] A sequence over a mixed log plays assistant replies (TTS) and voice user
      requests (original wav) in journal order; typed-user and system events
      are silently skipped.
- [ ] Pause/Resume/Stop and live-turn-cancel behave identically on wav
      segments and synthesized segments.
- [ ] A voice event with a missing/corrupt wav is skipped with a warning and
      the sequence continues.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` are green.
- [ ] Automated logic tests cover: the accessor returns wav for voice-user,
      text for assistant, None for typed-user/system; the walk interleaves
      both kinds in order; missing-wav is skipped. Audible wav playback is a
      human-run handoff.

## Verification handoff (human-run, hardware)

- Record a short mixed conversation (a couple of voice questions, a couple of
  replies), start a sequence from the top; confirm the human's own recorded
  voice plays for the questions and TTS plays for the replies, in order.
- Confirm a typed request in the middle is skipped without a gap artifact.
- Exact commands provided at handoff time.
