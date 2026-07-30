# Task v1.8.0-19: Historical annotation generator

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-18-annotation-overlay-store.md`
- `task-v1.8.0-17-transcript-api-ui-and-consumers.md`
- completed v1.7.3 reasoning-prompt work

## Summary

Implement an explicitly invoked local service that generates compact,
source-grounded annotations for inactive journal sessions.

## Context you need

- the task 18 annotation repository
- effective transcript reads from task 17
- `src/jarvis/dialog/backend.py`
- reasoning-prompt ownership established by v1.7.3

## Current boundary

- In scope: annotation generation, validation, pure tests, and a manual
  live-Ollama handoff.
- Out of scope: API/UI operations, search integration, and automatic
  retention.

## Requirements

- Read a bounded set of raw events and effective transcripts through the
  history API.
- Reject the active session.
- Use a narrow non-dialog inference boundary that does not publish response
  tokens or affect dialog history.
- Ask for source-grounded annotations and require returned source
  references.
- Validate output size, count, session ownership, and source references
  before persistence.
- Preserve existing user-edited annotations when generation is retried.
- Write only complete validated results and leave old data intact on
  cancellation or failure.
- Limit concurrency with normal dialog and transcription work.
- Provide a human-run live-Ollama verification command and expected report.

## Acceptance criteria

- [ ] Pure tests cover valid output, fabricated references, oversize output,
  cancellation, backend failure, active-session rejection, and preservation
  of user edits.
- [ ] Generated annotations always point to readable source ranges.
- [ ] No annotation generation output appears as a normal assistant response.
- [ ] Manual verification reports model, prompt size, latency, and annotation
  usefulness without logging private source text by default.

## Stop conditions

- Stop if annotations require a second independent prompt-ownership system.
- Stop if the configured model cannot reliably return valid source
  references in the agreed format; report the manual evidence.

## Verification

- Focused annotation generator tests with a fake backend.
- Prepare, but do not run, the live-Ollama verification command.
- `python -m pytest`
- Ruff checks.
