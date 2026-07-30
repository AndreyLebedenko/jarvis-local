# Task v1.8.0-6: Typed history event and range reads

**Status:** Approved.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-5.

## Summary

Add the typed read side of the Jarvis history API for events, surrounding
context, ordered ranges, sessions, and bounded batches. Search is a later
task.

## Context you need

- Task 1 reference types.
- Task 5 history-corpus repository and schema.
- `src/jarvis/journal/store.py`: existing whole-session replay.
- `src/jarvis/journal/fork.py`: a later consumer of effective event text.
- Existing typed result patterns in attachments and journal fork code.

## Current boundary

- In scope: domain query/result types, validation, range ordering, batching,
  and repository reads.
- Out of scope: FTS, transcription, annotations, HTTP routes, model tools,
  working context, and UI.

## Requirements

- Expose typed operations for:
  - one event by `JournalEventRef`;
  - several explicit references;
  - an inclusive ordered event-position range in one session;
  - a bounded number of events before and after a reference;
  - session metadata;
  - a bounded batch of ranges.
- Every returned event includes its reference, timestamp, role, source, raw
  text, media metadata, and event metadata.
- Preserve corpus order. No read operation silently reorders an explicit
  range by relevance.
- Unknown references and invalid ranges have typed outcomes; they are not
  empty-success ambiguities.
- Apply strict per-range, batch-count, and total-result limits from the
  approved history settings or domain constants owned by this API.
- Read methods use read-only SQLite connections and never fall back to
  scanning JSONL during normal operation.
- Keep HTTP/tool serialization out of the domain API.

## Acceptance criteria

- [ ] Single, surrounding, range, session, and batch reads return exact
      provenance and stable order.
- [ ] Invalid, unknown, cross-session, reversed, and over-limit requests have
      explicit tested outcomes.
- [ ] Total-result caps cannot be bypassed by splitting one request into many
      ranges.
- [ ] Reads do not modify the corpus or raw journal.
- [ ] Tests require no Ollama, UI, or hardware.

## Stop conditions

- Stop if one API shape cannot represent legacy and current-session events
  consistently.
- Stop if bounded batching requires returning partially truncated ranges
  without telling the caller.
- Stop if the corpus schema lacks information needed for lossless event
  reconstruction; revise task 5 rather than adding JSONL fallback here.

## Verification

- New pure/repository history-read tests.
- Existing journal replay tests.
- Ruff checks.
