# Task v1.8.3-1: Pausable playback primitive + Pause/Resume (single reply)

**Status:** Not started.
**Story:** `tasks/story-v1.8.3-sequential-journal-playback.md`
**Depends on:** nothing; first implementation card of v1.8.3.

## Summary

Replace `ReplayPlayer`'s one-shot `sd.play` + `sd.wait` playback with a
source-agnostic, pausable playback primitive: a callback `sounddevice`
`OutputStream` fed from an in-memory float32 frame buffer with a
playback-position marker, supporting pause (suspend at position) and resume
(continue from position). Wire a Pause/Resume control for the existing
single-reply (assistant) replay through the same held-request UI seam that
v1.8.2 uses for Play/Stop. No sequence and no wav/human playback in this card
- but the primitive is built source-agnostic so task 3 can feed decoded wav
frames through it unchanged.

## Context you need

- `src/jarvis/audio/replay.py`:
  - `ReplayPlayer._default_play` (~127) is the one-shot to replace:
    `sf.read` -> `sd.play` + `sd.wait` under `_playback_lock`. It is not
    pausable and blocks the lock for the whole clip.
  - `ReplayPlayer.cancel` (~96) calls `sd.stop()`; the new primitive must
    stop its own stream instead.
  - `_run` (~114) synthesizes each unit then plays it; pause must be able to
    suspend mid-clip, not only between units.
- `src/jarvis/app.py`:
  - `replay_player = ReplayPlayer(...)` (~1413); `playback_lock` shared with
    `TtsOutput`/`SoundCuePlayer` (do not change that sharing).
  - `replay_reply` (~1964), `_run_reply_replay` (~1990),
    `stop_reply_replay` path (~2001-2003, ~2030), and the
    `journal_reply_replay_handler` route wiring (~2457). Pause/Resume is a new
    signal alongside Stop; unlike Stop it must NOT resolve the held request
    (the replay is still running, just suspended).
- PROJECT.md "Architecture v1.8.2 (reply replay)":
  - The "HTTP request lifetime = replay lifetime" seam and the deferred
    pause/resume note (which names the callback `OutputStream` shape). This
    card implements that deferred note.
- `status_console_ui/` (the WebView): the Play/Stop control from
  task-v1.8.2-2; a Pause/Resume affordance is added here. Note the
  `file://` sub-resource caching gotcha in CLAUDE.md when verifying UI edits.

## Boundary

- Playback-engine change to `ReplayPlayer` plus its Pause/Resume wiring only.
- Keep the single shared `playback_lock` and `TtsMuteState` behavior exactly
  as today; keep `cancel()` (Stop / Ctrl+Alt+I / TTS-off / turn-start) working
  unchanged. The turn-start cancel via `on_turn_start` (~1645) must still stop
  a paused replay too.
- No sequence engine (task 2), no wav/human playback (task 3), no docs
  (task 4).
- Do not touch the live-turn `TtsOutput`/`OrderedPlayback` path.

## Requirements

- A pausable playback primitive (new class, e.g. `PausablePlayback` in
  `src/jarvis/audio/replay.py` or a sibling module): given float32 frames +
  sample rate, plays via a callback `OutputStream`, tracking a frame position
  marker; `pause()` stops feeding and holds the position, `resume()` continues
  from it, `stop()`/`cancel()` ends playback. It acquires the shared
  `playback_lock` for the duration of a clip (pause does not release the lock,
  matching "one channel" - a paused replay still owns the device; revisit only
  if that proves wrong).
- `ReplayPlayer._run` plays each synthesized unit through this primitive so a
  pause during any unit suspends immediately at the current frame.
- Pause/Resume signal path from the WebView through the app to the primitive,
  distinct from Stop (Stop cancels and resolves the held request; Pause holds
  it). Exact route shape (e.g. `POST .../replay/pause`, `.../replay/resume`)
  is decided in this card and recorded in PROJECT.md by task 4.
- `is_active` stays true while paused; add an `is_paused` view if the UI needs
  to render the toggle state.

## Acceptance criteria

- [ ] Single-reply replay plays identically to v1.8.2 when never paused.
- [ ] Pause suspends the audio at its current position; Resume continues from
      that exact position; multiple pause/resume cycles within one clip work.
- [ ] Stop, Ctrl+Alt+I, TTS-off, and a new live turn each still cancel the
      replay, including while paused, releasing the `playback_lock`.
- [ ] A Play attempt while a live turn speaks is still rejected (busy); a live
      turn starting during a paused/playing replay still cancels it.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` are green.
- [ ] Automated logic tests cover: position marker advances and is preserved
      across pause/resume (on a synthetic frame buffer, no device); cancel
      while paused clears state; is_active/is_paused transitions. Device
      playback and audible pause/resume timing are a human-run handoff.

## Verification handoff (human-run, hardware)

- Play a stored assistant reply, pause mid-sentence, resume; confirm it
  continues from where it stopped with no glitch or restart.
- Pause, then start a new live turn (voice or typed); confirm the replay is
  cancelled and the new turn speaks cleanly on the shared device.
- Exact commands provided at handoff time.
