# Task v2.1.0-3: speech-to-text stage

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 3 (Size: M-L). Facts: spikes
v2.1.0-5, -6, -8 (`tasks/done/`) and `PROJECT.md` section "v2.1.0 speech recognition
and confidence spikes". Follows tasks 1-2 (`src/jarvis/personal_proxy/` exists).

## Summary

A Whisper large-v3-turbo engine behind a small protocol, returning the text, every
word with its probability, and each segment's `avg_logprob`, `no_speech_prob`, and
`compression_ratio`; a speech-presence guard that keeps silence and noise away from
the engine; an optional-dependency file with lazy imports; a one-time weights setup
script. No Gemma, no pipeline, no wiring into the application.

## Owner decisions (2026-10-20, planning question of this task)

- The speech-presence guard reuses the project's Silero VAD and `[vad].threshold`.
  The guard itself is a pure function over a series of speech probabilities (the
  probability source is injected), and requires at least `stt_min_speech_seconds`
  of speech; below that the clip is "no speech" and never reaches the engine. New
  setting `[personal_proxy].stt_min_speech_seconds`, default 0.3, validated like
  the other keys of task 1 (finite, positive), documented in `config.example.toml`.
  The default is an unmeasured starting value and is labeled so; its calibration on
  the spikes' silence and noise controls is part of the human-run handoff below.

## Boundary

In scope (all under `src/jarvis/personal_proxy/`, tests under `tests/`):

1. **Engine protocol and result types.** A small protocol (transcribe a mono 16 kHz
   float32 clip, as the capture path delivers it - verify against `audio/input.py`)
   returning a result: the text, the words (word, start, end, probability), and the
   segments (text, `avg_logprob`, `no_speech_prob`, `compression_ratio`). Frozen
   dataclasses; the language is not a result field.
2. **faster-whisper engine.** Whisper large-v3-turbo through faster-whisper with the
   settings of the spikes (`manual/personal_proxy/stt_engines.py` and the spike 5/6
   cards: GPU `float16`, `language="ru"` from settings, beam 5, no built-in VAD,
   word timestamps). Model, device, language come from `[personal_proxy]`
   (`stt_model`, `stt_device`, `stt_language`). All third-party imports are lazy
   (inside the constructor/load), so importing the package without the optional
   dependencies works and CI is unchanged. Loading with missing dependencies or
   missing local weights raises a typed error with an actionable message; the
   runtime never downloads weights (offline: `local_files_only=True` or the
   equivalent).
3. **Speech-presence guard.** The pure function above, plus a thin adapter that gets
   per-window speech probabilities from the project's Silero VAD (reuse the model
   loading and window handling already in the code base; do not duplicate it; if it
   cannot be reused without a change to existing audio code, stop and report). A
   guarded transcription function composes guard + engine: no speech returns a typed
   "no speech" result without calling the engine.
4. **Dependencies.** `requirements-stt.txt` (faster-whisper and whatever it needs
   that the main file does not already pin), with a header comment explaining it is
   optional and why. `requirements.txt` and `.github` CI files are unchanged.
5. **Weights setup script** `setup_stt_model.py`, mirroring `setup_tts_model.py`:
   downloads the model once into the local cache (needs the network once), verifies
   it loads offline, prints what it did. Not run by the agent.
6. Tests with a fake engine and fake probability source (pure logic): result
   shaping, guard boundaries (below, at, above the minimum; empty clip; all-silence;
   all-speech), guarded transcription never calls the engine without speech, lazy
   import (importing the module does not import faster-whisper; a test with the
   import blocked), typed errors, config key validation.

Out of scope: Gemma, the check stage, any pipeline or app wiring, new UI, the
sanitize pass, changing existing audio/VAD code, running Whisper or downloading the
weights (human-run).

## Human-run handoff (prepared by the agent, run by the owner)

A script/command set under `manual/` (self-sufficient per CLAUDE.md Testing protocol
4: every command, key, and default named literally with its source): (a) install
`requirements-stt.txt` and run `setup_stt_model.py`; (b) transcribe a few spike
recordings through the guarded function and print text, words, segment signals, and
timing; (c) run the guard over the spikes' silence and noise controls and the real
utterances and print the speech seconds per clip, so the owner can see whether
`stt_min_speech_seconds` separates them. Preparing it must not run any of it.

## Acceptance criteria

- [x] The engine protocol returns text, per-word probabilities, and per-segment
      `avg_logprob`, `no_speech_prob`, `compression_ratio`.
- [x] Silence and noise (no or too little speech) never reach the engine: a test with
      a fake engine asserts it is not called.
- [x] Without the optional dependencies the package imports, the main runtime and
      `requirements.txt` and CI are unchanged; a missing dependency or weights raises
      a typed, actionable error; no code path downloads weights at runtime.
- [x] `stt_min_speech_seconds` is documented, validated, and labeled as unmeasured.
- [x] The human-run handoff exists and is self-sufficient.
- [x] `python -m pytest`, `ruff check`, and `ruff format --check` are green.

## Outcome (2026-10-20)

Accepted by the owner. Developer subagent; an independent reviewer found four
defects (a CUDA/DLL failure reported as missing weights, DLL search only in
`purelib`, clip format not validated, untyped errors from the probability source),
all fixed test first. Suite: 4227 passed, 1 skipped; ruff clean.

Handoff run by the agent on the owner's request (2026-10-20, GPU, weights from the
local cache; `requirements-stt.txt` installed into the main interpreter with the
owner's yes): step 2 (guard) both controls 0.00 s of speech, least speech in any of
the 44 real utterances 1.54 s, so the unmeasured default `stt_min_speech_seconds`
= 0.3 sits clear of both; step 3 (five recordings through the guarded function on
CUDA): correct Russian text, 0.23-0.37 s per short recording and 0.93-1.43 s per
long one (22-28 s of audio), model load 5.7 s, controls never reach the engine.
Not done: step 1.3 (`setup_stt_model.py`, the weights were already cached), step 4
(offline proof, needs the network switched off), the CPU variant of step 3.

Notes for later tasks: all segments of one decoding window share `avg_logprob` and
`compression_ratio` (eight identical lines on a 28 s recording), so these signals
are per window, not per segment, in practice. Weak words seen: "-01234" in an
account number p=0.69, "тысяч" p=0.64, "-1234" in a card number p=0.83. The guard
counts windows at or above the threshold with no hysteresis; music or other
speech-like noise counts as speech.
