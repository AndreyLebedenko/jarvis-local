# Task: Graded reasoning Ollama spike

**Story:** `tasks/story-v1.3.1-graded-reasoning-mode.md`
**Status:** Not started.
**Release:** v1.3.1

## Summary

Prepare one manual script that verifies the four proposed request values
against the configured local Ollama and model. The agent writes and tests the
script. The human runs it and returns the output. This task makes no runtime or
UI changes.

## Current boundary

In scope:

1. Add `manual_check_graded_reasoning.py` beside the existing manual checks.
2. Read the endpoint, model, and backend options through the same project
   configuration path used by Jarvis.
3. Send top-level `think` values `false`, `"low"`, `"medium"`, and `"high"`.
4. Use fixed prompts from three categories:
   - short deterministic calculation;
   - multi-step reasoning;
   - concise analysis of one reproducible image fixture.
5. Run each text prompt three times per level. Run the image prompt once per
   level. Do not claim stable performance ordering from a single request.
6. Print, for every request:
   - requested `think` value;
   - HTTP/result success;
   - `eval_count`;
   - thinking character count;
   - final content;
   - whether reasoning appeared outside `message.thinking`.
7. Print Ollama version when the local API exposes it.
8. Add pure tests for payload construction and result classification. Tests
   must not contact Ollama.
9. Hand the exact command `python manual_check_graded_reasoning.py` to the
   human and wait for the reported output.
10. After the human confirms the results, update the verified-facts section of
    `PROJECT.md` with only the observed facts.

Out of scope:

- Editing runtime thinking state, backend production code, UI, or sound cues.
- Testing `true` or `"max"` as product states.
- Treating token count as a guaranteed monotonic measure of reasoning quality.
- Running the live script by the agent.

## Acceptance criteria

- [ ] The script sends all four exact product values.
- [ ] The script covers text-only and image input through the existing
      `images` field.
- [ ] Pure tests cover request construction and reasoning/content separation
      classification.
- [ ] The agent provides one exact manual command.
- [ ] The human reports successful results for every required case.
- [ ] `message.content` remains clean final-answer text for every case.
- [ ] `PROJECT.md` records the verified values, environment version, measured
      observations, and the unchanged isolation rule.
- [ ] `python -m ruff format --check .`, `python -m ruff check .`, and
      `python -m pytest` pass before handoff.

## Stop conditions

- Stop if `low`, `medium`, or `high` is rejected.
- Stop if reasoning appears in `message.content` or the response shape is
  ambiguous.
- Stop if the media request no longer uses the verified `images` field.
- Stop after handing the script to the human until the human reports output.

