# Task: Manual markup handoff

**Story:** `tasks/story-v1.2.8-multilingual-speech-markup.md`
**Status:** Backlog.
**Release:** v1.2.8
**Depends on:** `tasks/story-v1.2.8-task-3-system-prompt-speech-markup-contract.md`

## Summary

Prepare a human-run manual check for Gemma4 speech-markup stability and record
verified behavior in `PROJECT.md`.

## Current Boundary

- Manual handoff and documentation only.
- The agent writes exact prompts and expected observations.
- The human runs live Ollama/Gemma4 checks.
- Do not tune generation defaults here; use configured values and record them.

## Acceptance Criteria

- [ ] Handoff includes the exact system prompt or points to the runtime prompt
      used by Jarvis.
- [ ] Handoff includes fixed prompts for:
      - Russian-only answer;
      - English-only answer;
      - mixed Russian/English with code identifiers;
      - quotes and slash-separated English examples;
      - punctuation-heavy short segments;
      - malformed-pressure case, such as asking for a long nuanced answer.
- [ ] Handoff asks the human to record model, Ollama version, `temperature`,
      `top_p`, `top_k`, `min_p`, `repeat_penalty`, and other configured
      generation options.
- [ ] Handoff records pass/fail observations:
      - no text outside `<speak>`;
      - all speakable text inside `<lang>`;
      - tags are closed;
      - no nested `<lang>`;
      - identifiers are usually routed to `en`;
      - punctuation does not create unusable markup.
- [ ] Human-confirmed results are recorded in `PROJECT.md`.
- [ ] Any unresolved behavior is documented as an open question or bug report,
      not silently worked around.

## Verification

- Read `PROJECT.md` with `Get-Content -Raw -Encoding UTF8 PROJECT.md`.
- Run `python -m pytest` unless the human agrees this is a docs-only handoff.

## Stop Conditions

- Stop if live results show Gemma4 cannot keep the markup contract stable under
  normal Jarvis prompts.
- Stop if generation-parameter choices have non-obvious trade-offs for
  factual quality, latency, or markup stability.
- Stop if observed failures require changing the parser contract from task 1.
