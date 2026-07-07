# Story v1.2.5: TTS engine foundation

**Status:** Backlog.
**Roadmap:** `tasks/roadmap-v1.2-v1.3.md`
**Release:** v1.2.5

## User-facing goal

Choose the next TTS direction from local measurements, then prepare the code so
TTS engines can be swapped without mixing synthesis concerns into sentence
buffering and playback orchestration.

## Boundaries

- The first task is a spike and handoff, not a migration.
- The agent writes measurement scripts but does not run live GPU/Ollama/audio
  measurements.
- TTS engine refactor waits until spike results are recorded in `PROJECT.md`,
  unless the human explicitly chooses a Silero-only preparatory refactor first.
- Do not implement "answer in the language of the request" in this release.
- Do not choose multilingual product behavior before measurements land.

## Acceptance Criteria

- [ ] A dedicated spike task produces `manual_check_tts_engines.py`.
- [ ] The spike compares Silero, Piper, Kokoro, and XTTS-v2 where they can be
      installed locally.
- [ ] The spike measures quality on fixed Russian, English, mixed Latin,
      numbers, short answers, and code-like phrases.
- [ ] The spike measures first-sentence latency, cold load time, and peak VRAM
      delta while Gemma remains resident.
- [ ] The spike compares Ollama Gemma with 64K f16 KV cache and 64K q8_0 KV
      cache, including resource headroom for stronger TTS options.
- [ ] Human-confirmed measurements are recorded in `PROJECT.md`.
- [ ] `TtsOutput` keeps buffering/playback orchestration while synthesis moves
      behind a `TtsEngine` interface.
- [ ] Current Silero behavior remains covered by tests after refactor.
- [ ] Config supports `[tts] engine` and engine-specific subsections.

## Task Card Sequence

1. TTS engine timing and quality spike.
   - Write `manual_check_tts_engines.py`.
   - Include exact commands and expected output fields for the human handoff.
   - Stop after handoff.

2. Record verified TTS facts.
   - Update `PROJECT.md` from human measurements.
   - Decide TTS host/model direction only after those facts exist.

3. TTS engine boundary.
   - Introduce `TtsEngine` and `SynthesisResult`.
   - Move Silero synthesis behind `SileroEngine`.
   - Keep existing behavior green.

4. TTS config shape.
   - Add `[tts] engine` and engine subsections.
   - Keep defaults equivalent to current Silero behavior.

## Stop Conditions

- Stop if the spike requires runtime network access after one-time setup.
- Stop if a candidate engine cannot be isolated behind a testable interface.
- Stop if the refactor makes current Silero behavior harder to test.
- Stop if measurements reveal non-obvious trade-offs with architectural
  consequences; record the data and ask before choosing.
