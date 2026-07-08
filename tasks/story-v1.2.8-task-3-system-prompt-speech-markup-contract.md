# Task: System prompt speech-markup contract

**Story:** `tasks/story-v1.2.8-multilingual-speech-markup.md`
**Status:** Backlog.
**Release:** v1.2.8
**Depends on:** `tasks/story-v1.2.8-task-2-tts-buffering-integration.md`

## Summary

Update Jarvis's system prompt so the local LLM emits the SSML-like speech
markup contract that the TTS path can parse.

## Current Boundary

- System prompt and prompt-contract tests only.
- Do not change backend generation parameters in this task.
- Do not implement "answer in the language of the request" as product behavior.
- Do not route to a new TTS engine.
- Do not expose a UI setting.
- Do not turn the system prompt into an untested user-editable config blob.
  If it is moved out of `main.py`, keep it as a tested runtime contract
  module/template.

## Acceptance Criteria

- [ ] The system prompt asks for all speakable assistant text to be inside
      `<speak>` and `<lang xml:lang="ru">` / `<lang xml:lang="en">` spans.
- [ ] The prompt explains that Russian prose belongs in `ru`.
- [ ] The prompt explains that English terms, API names, identifiers, short
      English phrases, and quotes belong in `en`.
- [ ] The prompt forbids Markdown, text outside `<speak>`, and nested
      `<lang>` tags for spoken responses.
- [ ] The prompt preserves the existing short-answer, Russian-by-default,
      low-latency behavior.
- [ ] Thinking/reasoning tokens remain excluded from `ResponseToken` consumers.
- [ ] Tests cover the expected prompt text or prompt-building behavior without
      contacting live Ollama.
- [ ] If the prompt is moved out of `main.py`, tests still protect the required
      speech-markup, short-answer, and Russian-by-default directives.
- [ ] `python -m pytest` passes.

## Verification

- Run `python -m pytest`.
- Prepare but do not run live Ollama checks as the agent.

## Stop Conditions

- Stop if prompt changes conflict with existing thinking-mode or TTS streaming
  guarantees.
- Stop if visible UI/history text would start exposing control markup without a
  documented decision.
- Stop if the prompt needs a larger response-format architecture than this
  task allows.
- Stop if making the prompt configurable would let the user silently break the
  TTS markup contract without validation or tests.
