# Task v1.8.0-16: Historical transcription service

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-15-transcript-overlay-store.md`

## Summary

Implement an explicitly invoked local service that transcribes eligible
historical voice events through the configured Ollama backend and writes only
successful results to the transcript overlay.

## Context you need

- `src/jarvis/dialog/backend.py`
- `src/jarvis/journal/`
- the task 15 transcript repository
- `PROJECT.md` verified audio-through-`images` contract
- existing backend fake/test patterns

## Current boundary

- In scope: the transcription service, pure tests, and a manual verification
  script.
- Out of scope: UI, HTTP routes, and automatic background work.

## Requirements

- Define a narrow transcription backend protocol rather than duplicating
  Ollama HTTP code.
- Send historical audio through the verified `images` field contract.
- Suppress normal response-token publication, speech output, and dialog
  history effects.
- Reject the active session and ineligible events.
- Support one event and bounded sequential batches.
- Write an overlay only after a complete, validated transcription result.
- Leave existing transcript data intact on cancellation or failure.
- Serialize or limit work so it cannot create uncontrolled concurrent Ollama
  requests.
- Provide an exact human-run command for live Ollama verification.

## Acceptance criteria

- [ ] Pure tests prove payload construction, successful persistence,
  cancellation,
  backend failure, invalid output, active-session rejection, and bounded
  batching.
- [ ] The service reuses the production backend boundary without publishing
  dialog output.
- [ ] Failed jobs do not create partial transcript records.
- [ ] Manual verification instructions include Russian speech and report
  latency
  plus returned text.

## Stop conditions

- Stop if the backend cannot support non-dialog inference without changing
  response publication semantics for normal turns.
- Stop if live verification contradicts the settled audio payload contract;
  report the conflict instead of changing it.

## Verification

- Focused transcription service tests with a fake backend.
- Prepare, but do not run, the hardware/live-Ollama verification command.
- `python -m pytest`
- Ruff checks.
