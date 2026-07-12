# Task: Model request composition state

**Status:** Completed.
**Release:** v1.2.16
**Prerequisite for:** `tasks/story-v1.3.0-control-center.md`, task 3.

## Summary

Publish an authoritative, privacy-safe summary when Jarvis begins a real
backend request. This is the preparation contract for the Control Center's
"Last request to model" panel and the future metadata-only model-interaction
log.

## Current Boundary

- Add a lifecycle event owned by `Orchestrator`, emitted immediately before
  its call to `OllamaBackend.chat()` for an accepted turn.
- The event reports only request-composition metadata:
  - local wall-clock timestamp;
  - input kinds included in that request (`audio`, `screenshot`,
    `clipboard`);
  - total audio duration in seconds when audio is included.
- It must describe the exact current request composition. A captured
  screenshot is reported only when it is attached to the accepted voice
  request; an empty or busy-rejected clipboard submission is never reported.
- The event means that the backend call has begun. It must not claim model
  completion or a successful response; existing failure events remain the
  source for those outcomes.
- Add a typed UI-contract projection and a `last_model_request` transport
  snapshot section. No Control Center markup or visual styling belongs here.
- No text, audio/image bytes, filenames, screenshot dimensions, transcript,
  clipboard content, byte counts, waveform samples, retention history, or
  request log is added. The state is the latest request summary only.
- Preserve the verified Ollama media rule: audio and images use the current
  request's `images` field.

## Acceptance Criteria

- [ ] Exactly one composition event is published for every accepted backend
      request, immediately before `backend.chat()`.
- [ ] Voice duration is derived from the accepted `UtteranceChunk`; future
      multi-audio requests can use the same total-duration field.
- [ ] Screenshot and clipboard metadata appear only when each source is in
      the request that begins.
- [ ] Empty and busy-rejected input produces no request-composition state.
- [ ] UI transport snapshot/deltas expose the latest typed summary without
      content or fake success.
- [ ] Pure tests cover accepted voice, accepted clipboard, voice plus pending
      screenshot, rejected input, timestamp injection, and transport shape.
- [ ] `python -m pytest` passes.

## Stop Conditions

- Stop if the exact request composition cannot be known at the backend-call
      boundary without duplicating orchestration or changing media semantics.
- Stop if the proposed event needs user content or binary payloads to support
      the panel.
- Stop if this becomes a retained interaction log rather than latest-state
      projection; the metadata log is a later, separately scoped feature.
