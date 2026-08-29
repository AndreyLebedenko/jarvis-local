# Story v1.8.3: Sequential journal playback (through-play + pause)

**Status:** Complete. All four task cards implemented, hardware-verified, and
merged to `main` (tasks 1-4 in `tasks/done/`). Delivered: pausable playback
primitive + Pause/Resume, the sequence engine with play-from-here and the
now-playing highlight, voice user turns played from their stored wav, and the
docs/release-verification pass.
**Created:** 2026-08-28.
**Version note:** `v1.8.3` is a placeholder pending owner confirmation of
where this slots against v1.9.0 and the other roadmap work; the user-facing
goal and task split below stand regardless of the number.

## Origin

v1.8.2 shipped Play/Stop replay of a single assistant reply via on-demand
re-synthesis, and deliberately deferred pause/resume (see PROJECT.md's
"Architecture v1.8.2 (reply replay)" deferred note). Owner now wants two
things folded into one slice, because they share a playback engine:

1. Pause/resume of a replay (the deferred piece).
2. Sequential through-playback: from a chosen point in the journal, play back
   in order everything that *can* be played, one item after another - the
   human's voice-originated requests and the assistant's replies - so the
   owner can re-listen to a stretch of conversation hands-free.

## User-facing goal

From any point in the chat log, the user starts a *sequence* that speaks each
playable turn in journal order, back to back, until the end of the log or
until stopped. A single pause control suspends and resumes the current
sequence at its playback position. Default and single-reply Play/Stop
behavior from v1.8.2 are unchanged when the user does not start a sequence.

- **What is playable (this story).** Assistant replies (as today) and the
  user's **voice-originated** requests (`source == "voice"` in the journal).
  They play by **two different mechanisms**: an assistant reply is spoken via
  TTS re-synthesis of its stored transcript (v1.8.2's contract, unchanged); a
  voice user request plays its **original recorded `.wav` directly** from the
  journal's media store (`record_voice_user` already persists it), so the
  user hears their own real voice, not a re-synthesis.
- **What is skipped.** Typed user requests (`source == "text"`) and system
  events (fork/context markers). They are silently stepped over; the sequence
  advances to the next playable turn. Typed-request playback is explicitly
  out of scope for now ("текст пока не трогаем").
- **Pause.** One control pauses the audio at its current position and resumes
  from there, for both a single-reply replay and a running sequence.

## Design decisions (proposed here, confirmed by card approval)

- **Two playback mechanisms, one channel. Human turns play their original
  wav; assistant turns re-synthesize.** The journal already stores each voice
  request's `.wav` (`record_voice_user`), so playing it directly is using
  existing media, not new persistence, and it gives the user their own real
  voice. This does NOT touch v1.8.2's "re-synthesis, not stored audio" rule:
  that rule governs *assistant replies*, which still re-synthesize under
  current TTS settings. The two sources converge on the single shared
  playback channel.
- **The accessor returns a "playable source for this event", not just text.**
  v1.8.2's `reply_speech_text()` reads a stored *assistant* reply's text.
  This story generalizes it: given a journal event, return what to play -
  text-to-synthesize (assistant), a `.wav` media reference (voice user), or
  `None` (skip: typed user, system). The sequence engine walks events and
  plays each non-`None` source by its kind. The v1.9.0 forward seam stays
  intact: for assistant turns the text branch still retargets to the mode-3
  derivative.
- **This story revisits "reject-when-busy, no queue" for self-playback - and
  only for that.** PROJECT.md's v1.8.2 architecture states a hard
  "no queue, no second route" rule. A sequence *is* an ordered queue of
  re-synthesis items played back to back on the single shared `playback_lock`.
  This is not the concurrency the v1.8.2 rule forbade: items never overlap,
  there is still exactly one playback channel, and the sequence is one logical
  replay that happens to have multiple segments. The rule that must hold
  unchanged: a **live turn** starting during a sequence still cancels the
  whole sequence (not just the current segment), and a Play/sequence attempt
  while a live turn is speaking is still rejected. Advancing to the next
  segment within a sequence must not be seen as "busy" against itself.
  PROJECT.md's v1.8.2 note is updated in the same change to scope its
  "no queue" wording to *concurrent* replay, not self-sequenced playback.
- **Pause needs a pausable playback primitive, as already recorded.** The
  v1.8.2 deferred note names the shape: a callback `OutputStream` with a
  playback-position marker and resume-from-position, replacing the current
  synthesize-then-blocking-play one-shot. It must be source-agnostic: the
  same pausable stream plays synthesized PCM (assistant) and decoded `.wav`
  frames (voice user) identically, so pause/resume and the position marker
  work the same for both. This is a playback-engine change, not a UI
  addition, and it is the foundation both features sit on - so it is task 1.
- **Sequence lifetime = one held request (UI seam), extending v1.8.2.**
  v1.8.2 holds one HTTP request open for the whole single-reply replay so the
  WebView toggles Play<->Stop off the fetch promise. A sequence is the same
  shape at a larger grain: one held request for the whole sequence, resolved
  by Stop or by reaching the end. Pause/resume is a separate lightweight
  signal that does not resolve the held request (the sequence is still
  "running", just suspended). Exact route shapes are a card decision.
- **Journal order is the play order.** The sequence walks events by their
  journal position from the start point forward; no re-sorting, no threading.

## Boundaries

In scope:

- A pausable, source-agnostic playback primitive (callback `OutputStream` +
  position marker) that plays both synthesized PCM and decoded `.wav` frames,
  with Pause/Resume for both single-reply replay and sequences.
- Direct playback of a voice user turn's stored `.wav` from the journal media
  store, on the same shared playback channel.
- A sequence engine that, from a start event, walks the journal forward and
  plays each playable turn (assistant replies via TTS + voice user turns via
  their wav) in order on the single shared playback channel, skipping
  typed-user and system events.
- The generalized "playable source for this event" accessor covering
  assistant replies (text->TTS) and voice user turns (wav reference).
- Chat-log controls: a "play from here" affordance to start a sequence, and a
  Pause/Resume control, alongside the existing single-reply Play/Stop.
- Reconciling the v1.8.2 reject-when-busy / live-turn-cancels-replay contract
  with self-sequenced playback, and updating PROJECT.md's v1.8.2 note to
  scope its "no queue" wording accordingly.

Out of scope:

- Typed (`source == "text"`) user requests in the sequence - voice only for
  now.
- Re-synthesizing human turns, TTS-normalizing them, or any transform of the
  stored wav - the original recording plays as-is.
- Scrubbing, seek-to-arbitrary-position, speed control, per-segment skip
  controls - Pause/Resume and Stop only. Richer transport is a later concern.
- Concurrent replays or a second playback route - still one channel; a live
  turn still cancels an in-flight sequence.
- Any change to the v1.9.0 response-modes work or the mode-3 derivative; this
  story only keeps the accessor seam intact.

## Scope (ordered task cards, to be opened one at a time)

1. **Pausable playback primitive + Pause/Resume.** Replace the one-shot
   synthesize-then-blocking-play in `ReplayPlayer` with a source-agnostic
   callback `OutputStream` carrying a playback-position marker; add pause
   (suspend at position) and resume (continue from position). Wire a
   Pause/Resume control for the existing single-reply (assistant) replay.
   Ships pause standalone - immediate value and the foundation for the
   sequence. No sequence, no human/wav playback yet.
2. **Sequence engine (assistant replies).** From a start event, walk the
   journal forward and play each assistant reply in order on the shared
   channel; Stop cancels the whole sequence; a live turn starting cancels the
   whole sequence; a start attempt during a live turn is rejected. Reconcile
   with the v1.8.2 reject-when-busy contract and update PROJECT.md's "no
   queue" wording to scope it to concurrent replay. Add the "play from here"
   chat-log control and the one-held-request sequence lifetime. Voice user
   turns not included yet (assistant-only sequence proves the engine).
3. **Include voice user turns (direct wav).** Generalize the accessor to
   return a voice user turn's stored `.wav` reference (`source == "voice"`),
   text->TTS for assistant turns, `None` for typed-user and system events;
   feed the decoded wav through the task-1 pausable stream. The sequence
   engine now plays those turns too, in order, from the original recording.
   Skipped events advance silently.
4. **Docs + release verification.** PROJECT.md architecture update (the
   pausable primitive, the sequence engine, the scoped "no queue" revision),
   `config.example.toml` / user docs for the new controls, and the human-run
   verification handoff (pause/resume audio timing, sequence playback,
   live-turn-cancels-sequence, and skip-typed behavior are hardware/manual
   checks).

## Acceptance criteria

- [ ] Default and single-reply Play/Stop behavior from v1.8.2 is unchanged
      when the user does not start a sequence.
- [ ] Pause suspends the current audio at its position and Resume continues
      from there, for both a single-reply replay and a running sequence.
- [ ] Starting a sequence from a chosen point speaks each playable turn in
      journal order, back to back, until the end of the log or Stop.
- [ ] Assistant replies play via TTS re-synthesis and voice-originated user
      turns play from their original stored `.wav`; typed-user and system
      events are silently skipped and the sequence advances past them.
- [ ] A live turn starting during a sequence cancels the whole sequence; a
      start/Play attempt while a live turn is speaking is still rejected;
      segments within a sequence never overlap on the shared channel.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green
      for all non-hardware logic; pause/resume timing, sequence playback,
      live-turn-cancel, and skip-typed behavior are prepared human-run
      handoffs with exact commands.

## Stop conditions

- Stop if a callback `OutputStream` with resume-from-position cannot be built
  as a localized replacement for `ReplayPlayer`'s one-shot play without
  reworking the live-turn `TtsOutput`/`OrderedPlayback` path shared with
  modes 1 and 2 - that is a playback-engine reshape, not this slice.
- Stop if the sequence's "advance to next segment" cannot be distinguished
  from "busy" without weakening the live-turn-cancels-replay guard - the
  guard's integrity outranks the sequence feature.
- Stop if the journal does not reliably expose voice-vs-typed for a past user
  turn at read time, or if a voice turn's stored `.wav` is not retrievable at
  read time (it records `source` and the wav media today; verify both survive
  the read path) - without them the "voice only, from wav" behavior has no
  basis.
- Stop if a single pausable stream cannot cleanly carry both synthesized PCM
  and decoded wav frames (e.g. sample-rate/format mismatch forcing per-source
  playback routes) - that would reopen the "one channel" decision and needs
  its own call.
