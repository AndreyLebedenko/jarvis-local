# Task: thinking backend contract

Status: Completed.

Story: [story-thinking-mode.md](story-thinking-mode.md)

## Summary

Teach the Ollama backend adapter how to express thinking mode in the
`/api/chat` payload and lock down the stream contract that separates hidden
reasoning from normal assistant content.

This task does not add a user-facing toggle or any `main.py` runtime
wiring.

## Current boundary

In scope:

- Extend `OllamaBackend.build_payload()` / `chat()` with an explicit
  thinking-mode input, using the verified top-level `think` parameter.
- Preserve the existing media behavior: audio and screenshots still attach
  to the final message via `images`.
- Preserve the existing text-only history policy.
- Ensure `message.content` is the only source of `ResponseToken` events.
- Ensure `message.thinking` is either ignored or routed to an internal
  non-TTS-safe representation, but never published as `ResponseToken`.
  If a new event is proposed for reasoning traces, stop first: exposing
  reasoning is outside the story boundary and has product/privacy
  consequences.
- Keep latency metrics parsing unchanged unless Ollama's done chunk shape
  requires a narrowly scoped adjustment.

Out of scope:

- Config fields and config.example changes.
- Hotkey registration.
- Sound cues.
- `main.py` turn-state ownership.
- Manual live Ollama checks; the spike already covered the API shape.
  Final live verification belongs to task-13.

## Dependencies

- [task-spike-thinking-mode.md](done/task-spike-thinking-mode.md)
- Existing `backend.py` tests and fake streaming client patterns.

## Acceptance criteria

Automated tests:

- `build_payload(..., thinking_enabled=False)` includes `think: false`.
- `build_payload(..., thinking_enabled=True)` includes `think: true`.
- Existing image/media payload tests still pass and still use `images`.
- A streaming test with chunks containing `message.thinking` and
  `message.content` publishes only the content as `ResponseToken`.
- A streaming test with thinking-only chunks publishes no `ResponseToken`.
- `ResponseComplete` and `LatencyMetrics` behavior remains unchanged.

Documentation:

- No `PROJECT.md` architecture update is required in this task unless the
  implementation discovers a contract different from the spike. If that
  happens, stop before proceeding because it may invalidate the story.

Stop conditions:

- Any need to expose reasoning tokens to another runtime consumer.
- Any ambiguity about whether a field is final answer text or reasoning.
- Any change that would require TTS or Orchestrator to know about raw
  Ollama thinking chunks.
