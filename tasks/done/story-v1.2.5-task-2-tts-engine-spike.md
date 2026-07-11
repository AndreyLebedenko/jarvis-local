# Task: TTS engine timing and quality spike

**Story:** `tasks/done/story-v1.2.5-tts-engine-foundation.md`
**Status:** Completed.
**Release:** v1.2.5
**Depends on:** `tasks/story-v1.2.5-task-1-ollama-attention-cache-options.md`

## Summary

Create `manual_check_tts_engines.py` to measure local TTS candidates and
Ollama KV-cache resource trade-offs on the human's machine.

## Current Boundary

- This is a spike and handoff only.
- Do not refactor TTS engine code in this task.
- Use the configured Ollama attention/cache options from task 1; do not rely
  on ad-hoc environment variables for the measured runtime path.
- The agent writes the script and exact commands, then stops.
- The human runs live GPU/Ollama/audio measurements.

## Acceptance Criteria

- [x] Script can compare Silero, Piper, Kokoro, and XTTS-v2 where installed
      locally.
- [x] Script uses fixed Russian, English, mixed Latin, numbers, short answer,
      and code-like phrases.
- [x] Script reports first-sentence latency from first token to audible
      playback.
- [x] Script reports cold load time.
- [x] Script reports peak VRAM delta while Gemma remains resident.
- [x] Human follow-up compares f16 and q8_0 on Gemma4 and gpt-oss at large
      contexts.
- [x] Handoff explains exact commands and expected output fields.

## Completion Decision

The spike is fully closed. Human checks found no task-detectable accuracy loss
from q8_0 on Gemma4 or gpt-oss and measured a 10-20% speed improvement at
large contexts. Kokoro and XTTS-v2 were not forced through costly environment
work: their installation and startup complexity made further investigation
unacceptable for the current project boundary, so they are considered
unsuitable for now.

## Verification

- Run pure tests for script logic where possible.
- Do not run live Ollama/GPU/audio measurements as the agent.
- Human runs the script and reports results.

## Stop Conditions

- Stop if a candidate engine requires runtime network access after setup.
- Stop if measuring a candidate needs a large dependency decision not covered
  by the story.
- Stop if the script cannot avoid live hardware during automated tests.
