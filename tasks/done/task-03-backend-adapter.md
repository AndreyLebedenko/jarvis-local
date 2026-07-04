# Task: Ollama backend adapter (backend.py)

Status: Completed.

Story: [story-jarvis-v1.0.md](story-jarvis-v1.0.md)

## Summary

The Ollama adapter: streaming `/api/chat`, media (audio wav and screenshot
png alike) sent via the `images` field, latency metrics captured on every
call. Interface kept thin so the backend is swappable later (Roadmap item 5,
not built in v1.0) with one config change.

## Current boundary

In scope:

- Async streaming HTTP client (implementation detail: pick one of
  `aiohttp`/`httpx`, whichever integrates more simply with the asyncio event
  bus; record the choice in code, not here).
- Request payload construction: system prompt + conversation history +
  optional `images` list carrying base64 audio and/or screenshot bytes.
  **Never** a dedicated `audio` field - Ollama silently drops it (verified
  fact, PROJECT.md and CLAUDE.md section 3).
- `num_ctx` and model name read from `config.py`'s settings object, not
  hardcoded.
- Streaming response tokens republished onto the bus as they arrive.
- Latency metrics (load/prefill/generation durations, token count) parsed
  from Ollama's response and logged/published on every call.

Out of scope:

- No second backend implementation (LiteRT-LM eval is Roadmap item 5).
- No retry/backoff policy beyond letting a failed request surface as an
  error event on the bus.
- No cross-restart conversation history persistence.

## Dependencies

`bus.py` (task-01), `config.py` (task-02).

## Acceptance criteria

Automated tests (no live Ollama server needed, use fixtures/mocks):

- Payload construction test asserts audio and image bytes are placed under
  `images`, and asserts no `audio` key is ever present in the payload - this
  is a regression test protecting the verified fact, not a hypothetical.
- `num_ctx` and model name in the constructed payload come from the config
  settings object, confirmed by varying the fixture config.
- A fixture of a chunked/streamed HTTP response is correctly reassembled
  into complete tokens and republished on the bus in order.
- Latency metrics are correctly parsed from a fixture Ollama response
  (nanosecond durations converted, token count extracted).

Manual handoff (hardware/live-endpoint dependent, human runs and reports):

- Exact command(s) to run a live call against the real Ollama endpoint with
  `gemma4:12b-it-qat`, one with an audio clip and one with a screenshot,
  confirming both succeed end-to-end.
- Confirm measured latency is in the neighborhood of PROJECT.md's day-0
  numbers (load ~0.3 s warm, prefill ~0.1-0.3 s, ~87 tok/s generation); note
  any material deviation rather than silently accepting it.
