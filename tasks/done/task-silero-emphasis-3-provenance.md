# Task 3: Provenance wiring

**Status:** Completed.
**Story:** `tasks/story-silero-v5-emphasis-markers.md` (decision B: markers
only from the caller's `spoken_text`).
**Predecessor:** `tasks/done/task-silero-emphasis-2-engine-boundary.md`.

## Summary

With `emphasis = true` an engine keeps any marker it is given, and it cannot
tell where the text came from. So every text that is not the caller's
`spoken_text` loses its asterisks before it reaches an engine. The rule is
default-deny: a new producer that goes through `TextReply` or `ResponseToken`
is safe without any code. A new direct caller of an engine's `synthesize`
would not be covered and must strip itself.

## The paths into an engine (checked in the code)

1. `TtsOutput.on_token` (`audio/tts.py`): the local model's streamed answer.
   Untrusted. Strip every chunk; stripping `*` per chunk is safe because it
   removes single characters, so a marker split across two tokens loses both
   asterisks.
2. `ReplayPlayer` (`audio/replay.py`), through `TextReply`: voice-guide speech,
   journal replay (`app.py`), and the personal proxy answer
   (`personal_proxy/answer/answer_speaker.py`). `TextReply` gets
   `emphasis_trusted: bool = False`; `ReplayPlayer._segment` strips unless it is
   true.
3. `VoiceGuideService._speak` (`dialog/voice_guide.py`) is the only place that
   sets it, and only for `SpeechOrigin.CALLER`. Verbatim canvas and the local
   guide pass stay untrusted.

## Boundary

Files to change: `src/jarvis/audio/replay.py`, `src/jarvis/audio/tts.py`,
`src/jarvis/dialog/voice_guide.py`, and tests in `tests/test_replay.py`,
`tests/test_tts.py`, `tests/test_voice_guide.py`, plus two end-to-end cases in
`tests/test_silero_emphasis_boundary.py` (a trusted and an untrusted reply
through a real `SileroEngine` with a stub model).

Must NOT touch: `app.py`, the personal proxy, `speech_cleanup.py`, the engines,
config, the MCP tool description (task 4).

## Known limits, accepted

- Journal replay of a caller's `spoken_text` is voiced without markers (replay
  text is untrusted), the same as before this story.
- In dynamic language mode a marker at a language-switch boundary, such as
  `*API*` or `*Python*` inside Russian speech, or a Russian marker right before
  a Latin word, can be split across two speech units by charset routing; both
  halves then lose their asterisks (the normalizer drops unpaired ones). The
  sentence still plays. Reviewed 2026-11-25: it fails safe, no leak.
- Stripping now happens before segmentation for untrusted text, so
  `**Итог.** Дальше идём.` splits into two units where it used to be one. It is
  benign: the bold heading ends its own sentence.
- The journal stores the caller's `spoken_text` with its markers as written.

## Tests

- an untrusted `TextReply` reaches the engine without asterisks; a trusted one
  keeps its markers; several sentences become several units, each keeping its
  own markers; the default is untrusted;
- caller `spoken_text` is spoken with its markers; verbatim canvas and a local
  guide text are spoken without asterisks;
- streamed tokens never carry an asterisk to the engine, including a marker
  split across two tokens.

## Acceptance criteria

- `python -m pytest`, `ruff check .`, and `ruff format --check .` pass.
- Only the three source files above change (`replay.py`, `tts.py`, `voice_guide.py`).
