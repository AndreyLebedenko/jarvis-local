# Story: Jarvis v1.0 - Local Voice/Vision Assistant

Status: Not started.

## Goal (user-facing)

A background process, no GUI, controlled by hotkeys and sound cues. The user
speaks in Russian; the assistant hears via microphone (VAD-segmented
utterances) and optionally looks at the screen (hotkey-triggered
screenshot). It reasons via the local Ollama backend (`gemma4:12b-it-qat`)
and replies with short, spoken Russian answers, streamed sentence-by-sentence
so speech starts within ~3 s of the end of the user's utterance (VAD
end-of-speech), covering audio prefill, first-sentence generation, and TTS
synthesis of that sentence. Fully offline at runtime.

## Boundaries

Out of scope for v1.0 (per PROJECT.md's Roadmap section and by omission from
the Architecture v1.0 section):

- emotion2vec+ intonation side channel (Roadmap item 1, v1.x).
- XTTS-v2 expressive TTS (Roadmap item 2, v1.x). v1.0 TTS is Silero only.
- Audio-preserving re-tuning research (Roadmap item 3).
- Optional GUI / dialog history window (Roadmap item 4).
- Backend evaluation / LiteRT-LM swap (Roadmap item 5). backend.py must be
  swappable later, but v1.0 ships only the Ollama adapter.
- Auto-start / Windows service installation. v1.0 is a script the user
  launches manually; no requirement for this exists in PROJECT.md.

## Acceptance criteria

- All 7 task cards below are completed and moved to `tasks/done/`.
- Automated test suite is green: event bus behavior, config parsing, backend
  request payload construction, VAD chunking on prerecorded wav fixtures,
  TTS sentence buffering, capture crop/full-screen logic, main.py wiring.
- Manual test handoffs for hardware-dependent behavior (microphone,
  speakers, hotkeys, live Ollama call, VRAM under real load) are prepared by
  the agent and executed by the human with reported-good results.
- End-to-end path verified on real hardware: a spoken question (with an
  optional screenshot) produces a short spoken Russian reply, first audio
  starting within ~3 s of the end of the user's utterance (VAD
  end-of-speech) - covering audio prefill, first-sentence generation, and
  TTS synthesis of that sentence, per PROJECT.md's Architecture v1.0
  section.
- `day0_checks.py` verified facts still hold on the finished build (rerun
  after any backend, model, or driver change per PROJECT.md).

## Task-card sequence (implementation order)

Each task card is independently completable and verifiable; later cards
depend on earlier ones as noted in each card.

1. [task-01-event-bus.md](task-01-event-bus.md) - `bus.py`
2. [task-02-config.md](task-02-config.md) - `config.py`
3. [task-03-backend-adapter.md](task-03-backend-adapter.md) - `backend.py`
4. [task-04-audio-input.md](task-04-audio-input.md) - `audio_in.py`
5. [task-05-tts.md](task-05-tts.md) - `tts.py`
6. [task-06-screen-capture.md](task-06-screen-capture.md) - `capture.py`
7. [task-07-main-wiring.md](task-07-main-wiring.md) - `main.py`

## Open decisions recorded during story-card creation

- Config: a dedicated `config.py` module was added to the architecture
  (task-02) to give the "config parsing" automated-test category named in
  CLAUDE.md's testing protocol a concrete home. This was resolved with the
  human before task-card breakdown (CLAUDE.md 0.2/0.1) and PROJECT.md's
  Architecture v1.0 section has since been updated in the same change to
  list `config.py`, per CLAUDE.md's "Project context" rule 2. PROJECT.md is
  now the source of record for this module; this note is a historical
  record of the decision, not the current source.
