# Task v1.8.0-17: Transcript API, UI, and consumers

**Status:** Proposed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`

**Depends on:**

- `task-v1.8.0-16-transcription-service.md`

## Summary

Expose transcript viewing, editing, and generation through the authenticated
Jarvis API and Journal UI, then make search and fork consumers use the
effective transcript.

## Context you need

- `src/jarvis/ui/transport.py`
- `src/jarvis/ui/status_console_ui/index.html`
- `src/jarvis/ui/status_console_ui/app.js`
- `src/jarvis/ui/status_console_ui/strings.js`
- journal view and transport tests
- current fork construction in `src/jarvis/app.py`

## Current boundary

- In scope: transcript API/UI integration and effective-transcript consumers.
- Out of scope: annotations and automatic retention.

## Requirements

- Add authenticated API operations to read, edit, delete, and explicitly
  generate transcript overlays.
- Apply existing Hidden-mode content suppression to transcript payloads.
- Show transcript state and safe edit/generate controls in the Journal UI.
- Render all historical text with safe text nodes and existing localization
  conventions.
- Define effective transcript precedence:
  - user-edited overlay;
  - generated overlay;
  - raw event transcript;
  - no transcript.
- Make fork provenance and history reads consume the effective transcript.
- Include effective transcript text in exact search and remove stale values
  after edits.
- Reject conflicting edits or generation jobs with explicit API outcomes.

## Acceptance criteria

- [ ] API authentication and Hidden-mode tests cover every new route.
- [ ] Editing a transcript immediately changes search and future fork input.
- [ ] Raw journal content remains unchanged.
- [ ] UI tests cover absent, generating, generated, edited, failed, and Hidden
  states.
- [ ] Concurrent edit/generate attempts cannot silently overwrite user work.

## Stop conditions

- Stop if the current UI transport has no consistent authentication boundary
  for the new operations.
- Stop if effective-transcript precedence conflicts with existing product
  behavior not resolved by the story.

## Verification

- Focused transport, Journal UI, search, and fork tests.
- Static JavaScript checks defined by the project.
- `python -m pytest`
- Ruff checks.
