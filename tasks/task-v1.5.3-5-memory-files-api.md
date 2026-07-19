# Task v1.5.3-5: Memory files API

**Status:** Backlog.
**Story:** `tasks/story-v1.5.3-memory-layer-a.md`
**Depends on:** task-v1.5.3-4 (files, caps, config).

## Summary

Expose memory.md and self.md for reading and writing through the
authenticated local transport so the UI can view and edit them.
Transport only; no UI.

## Context you need

- `src/jarvis/ui/transport.py`: journal endpoint auth
  (`_require_http_token`), Hidden gating, and routing style; the
  v1.5.2-1 POST endpoint as the precedent for write-style requests.
- task-v1.5.3-4's config (paths, caps) and loader seam.
- Cross-cutting rule 7: user-auditable, size-capped; the transport is
  the user's edit path in this release.

## Boundary

- Exactly two logical files (memory, self), addressed by fixed
  identifiers - the API must not accept arbitrary paths or filenames.
- No model/tool write path (v1.6.1), no history/versioning, no
  concurrent-edit resolution beyond last-write-wins.
- No UI changes.

## Requirements

- GET returns a file's current content plus its cap and current size;
  a missing file returns empty content, not an error.
- PUT (or POST - match v1.5.2-1's style) replaces a file's content:
  UTF-8, validated against the cap with a structured over-cap
  rejection (the API never writes a truncated version silently -
  unlike injection, editing is explicit and must round-trip exactly).
- Both endpoints are token-authenticated and suppressed in Hidden mode
  exactly like journal endpoints (memory content is at least as
  private as the journal).
- Writes are atomic (temp file + replace) so a crash cannot leave a
  half-written memory file.
- File identifiers are a closed enum; anything else is a structured
  bad-request, tested against traversal-style inputs.

## Acceptance criteria

- [ ] Transport tests cover: auth, Hidden suppression, read of missing
      and existing files, exact round-trip write/read (Russian text
      included), over-cap rejection, invalid identifier rejection, and
      atomic-write behavior at the seam level.
- [ ] No UI behavior changes.
- [ ] `python -m pytest` and Ruff checks are green.
