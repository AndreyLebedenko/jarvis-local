# Jarvis-Local v1.9.1

Cumulative release. Covers everything merged since the last published release,
**v1.8.1** (2026-08-23): the v1.8.2 and v1.8.3 playback work, the v1.9.0
response-mode feature, and the v1.9.1 provenance-aware indexing layer.

Most new capabilities below are opt-in - a new control, a new mode you switch
into, or a new search surface. The one deliberate default behavior fix is the
short voice-message padding described under v1.9.1.

Runtime stays local: core orchestration and inference require nothing beyond the
configured local Ollama endpoint. External access remains an explicit,
off-by-default per-component capability.

---

## Highlights

- **Re-listen to any reply, and play back whole stretches of a conversation
  hands-free** (v1.8.2, v1.8.3).
- **Three response modes - Text-Only, Voice-Only, and Text+Voice** - so an
  answer can be shaped for reading or for listening without one format serving
  every purpose (v1.9.0).
- **Find a turn by a phrase you only heard.** Journal search now reaches the
  spoken part of a Text+Voice answer, and always shows you the authoritative
  on-screen text (v1.9.1).
- **Short voice messages are heard more reliably.** Very short microphone
  chunks are padded before they are sent to the model, avoiding the fragile
  sub-3-second audio path found in live testing (v1.9.1).

---

## v1.8.2 - Replay TTS

- **Play/Stop on any past assistant reply.** A playback control on each
  assistant reply in the chat log re-speaks it on demand - not just the last
  reply, any of them.
- **Re-synthesis, not stored audio.** Replay runs the stored reply text back
  through the TTS engine at press time. No waveforms are kept in the journal, and
  playback uses whatever voice, rate, and accent TTS is configured *now* - handy
  for language practice, where hearing a line again under current settings is the
  point.

## v1.8.3 - Sequential journal playback

- **Pause/Resume** for replay (the piece deliberately deferred in v1.8.2).
- **Through-play from any point.** Start a sequence at a chosen turn and Jarvis
  speaks each playable turn in journal order, back to back, until the end of the
  log or until you stop it - re-listen to a stretch of conversation hands-free.
- **Two honest playback mechanisms.** Assistant replies play by TTS
  re-synthesis (the v1.8.2 contract); your own **voice-originated** requests play
  their **original recorded audio** straight from the journal, so you hear your
  real voice, not a re-synthesis.
- **Now-playing highlight** tracks the current item; single-reply Play/Stop is
  unchanged when no sequence is running.

## v1.9.0 - Response modes (Text-Only / Voice-Only / Text+Voice)

Switch Jarvis between three response modes. The active mode persists across
restarts; the default is **Text-Only**, so nothing changes until you opt in.

- **Mode 1 - Text-Only (default).** Today's behavior: single pass, text-oriented
  output, streaming and sentence-buffered TTS exactly as before.
- **Mode 2 - Voice-Only.** A single-pass, self-contained spoken answer: prose,
  no bullets, tables, or inline URLs; numbers and units spoken where it helps.
  Because nothing is shown, the spoken form references nothing external.
- **Mode 3 - Text+Voice.** Two passes. Pass 1 streams the canonical rich text to
  the screen immediately. Pass 2, **with reasoning off**, takes that exact shown
  text and speaks a guided rendering of it - it may say "as in the table above,"
  because that table is genuinely on screen. This trades latency for a richer
  experience: you get an inspectable answer first, then a spoken guide to it. The
  first-pass streaming TTS is silent in this mode; only the guided pass is spoken.
  - The spoken derivative is stored **inside the same assistant turn** and shown
    as a collapsed **"spoken aloud"** block you can expand. It is a rendering of
    the canonical answer, never a second source of fact, and is kept out of
    memory and retrieval.
- **Switch it your way.** A single hotkey cycles the modes (1 -> 2 -> 3 -> 1); a
  live control on the Status tab flips the running mode; a Settings drop-down sets
  the persisted default for the next launch; and a spoken "switch to <mode>"
  command works too, reliably told apart from ordinary request content.

## v1.9.1 - Provenance-aware indexing and search surfaces

Makes the history and search layer understand not just *text*, but what kind of
text it is and what it is based on.

- **Provenance the model can read.** History search results now carry an
  explicit provenance tag, so a retrieved passage is identifiable as a raw
  user/assistant turn, a voice transcript, or a derived annotation - the model no
  longer has to guess, and never mistakes derived or heard text for a canonical
  turn. This is unified into one typed descriptor across every search surface.
- **Heard-phrase Journal search.** You can now search the Journal for a phrase
  that only ever existed in the *spoken* part of a Text+Voice answer. The search
  locates the owning turn and shows the **canonical on-screen text** as the
  authoritative content; the heard phrase is only a locator. A phrase you heard
  can find a turn, but it is never promoted into what Jarvis "remembers" was said.
- **Kept separate by construction.** The spoken-derivative locator index is a
  lexical index, physically separate from the canonical search index, added
  without a storage-format change. There is no semantic indexing of spoken text
  and no automatic promotion of it into memory.
- **Short voice-message padding.** Microphone VAD chunks shorter than
  `[vad].min_chunk_seconds` are now padded symmetrically before WAV encoding,
  using deterministic white noise controlled by `[vad].padding_noise_rms`. The
  default is 3.0 seconds with RMS 0.002; owner end-to-end checks found
  3.0 seconds with RMS 0.001 to be a practically ideal local tuning for short
  messages. This does not add gain normalization, AGC, filtering, or prompt
  changes, and VAD start/end timestamps remain the original speech boundaries.

---

## Quality and verification

- Automated logic suite: **2398 passed, 1 skipped**; `ruff check` and
  `ruff format --check` clean.
- Hardware- and UI-dependent behavior (hotkeys, live TTS/audio timing,
  voice-command switching, mode-3 playback, and the heard-phrase search check)
  was verified through prepared, self-sufficient human-run handoffs per the
  project's testing protocol.

## Upgrade notes

- No configuration changes are required. Most new features are opt-in; short
  voice-message padding is enabled by default as a reliability fix.
- Response mode defaults to Text-Only and is read from config at startup; set a
  different default from the Settings drop-down if you want another mode on
  launch.
- Short voice-message padding can be tuned with `[vad].min_chunk_seconds` and
  `[vad].padding_noise_rms`; try `3.0` and `0.001` first if the default noise
  floor is more than your microphone/model setup needs.
- The history/search indexes are derived, rebuildable data beside the
  append-only journal; no manual migration is needed.
