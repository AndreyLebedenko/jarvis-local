# Story v1.8.2: Replay TTS (Play button on any assistant reply)

**Status:** In Review. Task cards 1-3 written (see Scope below); none started.
**Created:** 2026-08-26.

## Origin

Came out of the response-modes discussion (`story-v1.9.0-response-modes.md`).
Re-listening to a spoken reply is useful on its own - notably for language
learning - and it is a more *primitive* capability than the response modes:
it does not need any of that machinery. So it ships first, standalone, and
the later mode-3 work simply retargets it. See v1.9.0's "Canonical text and
spoken derivative" and replay decisions for the seam.

## User-facing goal

The user can re-listen to any past assistant reply in the chat log by
pressing a Play control on it. Playback is produced by **re-synthesizing the
stored reply text through TTS on demand** - no audio is stored. Because it is
re-synthesis, the user can hear it again under whatever voice/rate/accent TTS
is configured at replay time, not frozen to how it first sounded.

## Design decisions (proposed here, confirmed by card approval)

- **Re-synthesis, not stored audio.** Replay calls the existing TTS engine
  (`BilingualTtsEngine.synthesize(text, language)` in `src/jarvis/audio/tts.py`)
  on the stored reply text at press time. No waveform blobs in the
  journal/history, no coupling to the TTS settings that were active when the
  turn first played. This was chosen over storing audio deliberately: exact
  acoustic reproduction is not worth the storage weight or the settings
  lock-in, and re-synthesis under current settings is the more useful
  behavior for the language-learning case.
- **Play is available on any past assistant reply, not just the last one.**
  Same cost, and the value for language study is precisely in returning to
  older lines.
- **Replay is honest about what it speaks.** In v1.8.2 the stored reply text
  is today's canonical answer, which may contain tables/URLs that sound as
  rough re-spoken as they did the first time - replay makes nothing worse, it
  repeats what TTS already does. "Speaks it *nicely*" is a v1.9.0 concern
  (mode 3's spoken derivative); v1.8.2 sells only "hear it again."
- **Replay plays only when the channel is free; no queueing.** (Owner
  decision, 2026-08-26, chosen to avoid building an isolated second playback
  route now.) Replay reuses the single existing playback channel. Press Play
  while anything is already playing - a live turn or another replay - and the
  attempt is *rejected*, not queued: a short beep plus a visible error
  message ("busy"). Nothing interleaves, and no second audio route is built.
  Losing a rejected press costs nothing - the Play control is always there to
  try again once the channel is free.
- **Ctrl+Alt+I cancels any playback, live or replay.** The existing interrupt
  hotkey (`HotkeySettings.interrupt`, story-v1.7.0) stops whatever is
  currently playing, including a replay. Since replay uses the same single
  channel, this falls out of the existing cancellation path rather than
  needing replay-specific interrupt ownership.
- **Forward seam to v1.9.0.** Replay resolves "the text to speak for this
  turn" through one accessor. Today that returns the canonical reply text.
  Once mode 3's spoken derivative exists, that accessor returns the
  derivative when present. v1.8.2 builds the accessor so v1.9.0 only changes
  what it points at, not the Play control or playback path.

## Boundaries

In scope:

- A Play control on each assistant reply in the chat log UI
  (`src/jarvis/ui/status_console.py` and related), for any past reply.
- An on-demand re-synthesis + playback path that reads the stored reply text,
  synthesizes it, and plays it back without disturbing history/journal.
- A busy-channel guard: reject a replay press when the single playback
  channel is occupied (live turn or another replay), signalling a beep plus a
  visible error message instead of queueing.
- Ctrl+Alt+I cancelling replay via the existing interrupt path.
- A single "text to speak for this turn" accessor as the forward seam for
  v1.9.0.

Out of scope:

- Storing audio waveforms anywhere. Re-synthesis only.
- The response modes themselves (`story-v1.9.0-response-modes.md`). v1.8.2
  speaks the existing canonical reply text; the spoken derivative does not
  exist yet.
- Any change to how a *live* turn is synthesized or streamed (sentence
  buffering, ordered playback) beyond the busy-channel guard and reusing the
  existing interrupt path.
- An isolated second playback route or any queueing of replay attempts -
  explicitly rejected in favor of the reject-when-busy rule above. Concurrent
  replay is a possible later story, not this one.
- Scrubbing, pause/resume, speed control UI, or per-reply voice selection -
  Play (and at most Stop) only. Richer transport is a later concern.
- Persisting or exporting the synthesized audio (download/save) - none.

## Scope (ordered task cards, to be opened one at a time)

1. `task-v1.8.2-1-replay-core.md` - **Replay core.** The "text to speak for
   this turn" accessor over stored replies, plus an on-demand re-synthesis
   path that reuses the single playback channel, does not touch
   history/journal, and rejects the attempt (beep + error) when speech is
   active. Ctrl+Alt+I cancels it via the existing interrupt path. No UI yet;
   verified by logic tests on accessor/busy-reject/interrupt plus a human-run
   audio handoff.
2. `task-v1.8.2-2-play-control-ui.md` - **Play control in the chat log.** The
   per-reply Play (and Stop) control in the status console UI, wired to the
   replay core, available on any past assistant reply. Human-run UI/audio
   verification handoff.
3. `task-v1.8.2-3-docs-and-release-verification.md` - **Docs + release
   verification.** User docs, PROJECT.md entry for the architectural
   decisions, the v1.9.0 forward-seam note, and the human-run verification
   checklist (replay audio, busy-reject, interrupt, older-reply replay).

## Acceptance criteria

- [ ] Every past assistant reply in the chat log exposes a Play control;
      pressing it re-synthesizes the stored reply text via TTS and plays it
      back.
- [ ] No audio is stored: replay is always a fresh synthesis, and it honors
      the TTS voice/rate/accent configured at replay time, not at original
      turn time.
- [ ] Replay never mutates history or the journal.
- [ ] A Play press while the playback channel is busy (live turn or another
      replay) is rejected with a beep and a visible error message, never
      queued and never interleaved; the control can simply be pressed again
      once free.
- [ ] Ctrl+Alt+I stops an in-progress replay, through the same interrupt path
      that stops a live turn.
- [ ] The "text to speak for this turn" accessor exists as a single seam, so
      v1.9.0 can point it at the mode-3 derivative without touching the Play
      control or playback path.
- [ ] `python -m pytest`, `ruff check`, and `ruff format --check` are green
      for all non-hardware logic; replay audio and UI interaction are prepared
      human-run handoffs with exact commands.

## Stop conditions

- Stop if the stored reply text cannot be read back cleanly for an arbitrary
  past turn through the existing journal/history read path (e.g. it is only
  available as part of a larger projection that is expensive or lossy to
  query per-reply) - that is a history-read-API question, not a replay-UI
  detail.
- Stop if the playback channel exposes no clean "is something playing right
  now?" signal to gate the busy-reject on, and adding one would mean
  reworking the live playback/OrderedPlayback contract - that is a larger
  audio-pipeline change needing its own decision.
- Stop if the existing Ctrl+Alt+I interrupt path is so turn-scoped that
  making it also stop a replay would require reworking the cancellation
  contract rather than reusing it.
