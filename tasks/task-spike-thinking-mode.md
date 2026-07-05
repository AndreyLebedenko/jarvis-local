# Task: Thinking-mode spike

Status: Draft.

Story: [story-v1.1-controlled-input.md](story-v1.1-controlled-input.md)

## Summary

A day-0-style manual experiment for Ollama/Gemma thinking mode. The goal is
to determine whether Jarvis can safely support a future think on/off hotkey
without ever sending reasoning tokens to TTS.

This task does not implement runtime thinking-mode wiring.

## Current boundary

In scope:

- Add a manual check script following the style of
  `manual_check_backend.py`.
- Send the same prompt to the configured Ollama model with thinking disabled
  and enabled - twice: once text-only, and once with one media input (an
  image is preferred over audio, since it is trivially reproducible
  without a microphone; a synthetic wav fixture is acceptable if audio is
  used instead). Jarvis's real payloads are always multimodal via the
  `images` field (day-0 verified fact), so a text-only check alone would
  not confirm reasoning-token isolation holds for the actual use case.
- Capture the exact request parameter used for each mode.
- Record whether reasoning appears in a separate stream field or inside
  normal response content - for both the text-only and the media request.
- Measure latency difference between thinking off and thinking on.
- Record the findings in `PROJECT.md`.
- Define the hard implementation requirement for later wiring: reasoning
  tokens must never reach `ResponseToken` consumers or the TTS pipeline.

Out of scope:

- Any user-facing hotkey for thinking mode.
- Any change to default runtime behavior.
- Any TTS changes.
- Any assumption that official Ollama documentation alone is sufficient;
  this project needs local verification against the configured model and
  local Ollama version.

## Dependencies

- Existing `backend.py` request/streaming behavior.
- Live Ollama endpoint and configured model. This is hardware/live-service
  dependent and therefore run by the human, not the agent.

## Acceptance criteria

Automated tests:

- If the manual check script has pure payload-building helpers, cover them
  with unit tests.
- No automated test may require a live Ollama endpoint.

Manual handoff:

- Exact command to run the script, for both the text-only and the media
  variant.
- The human reports the raw relevant stream shape for thinking off/on, in
  both variants.
- The human reports latency for all four runs (text/media x off/on).
- The human reports whether reasoning is separate from content, in both
  variants - a text-only pass alone does not satisfy this task.

Documentation:

- `PROJECT.md` records:
  - local Ollama version if available from the manual script;
  - exact API parameter for thinking off/on;
  - where reasoning tokens appear in the stream, text-only and multimodal;
  - whether content tokens remain clean for TTS in both cases;
  - observed latency difference;
  - the implementation rule for any future thinking-mode wiring.

Stop condition:

- If reasoning appears in normal content, or the stream shape is ambiguous,
  in either the text-only or the multimodal variant, stop and do not plan
  product wiring until the ambiguity is resolved.
