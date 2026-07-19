# Task v1.5.2-5: Image thumbnails in the feed

**Status:** Backlog.
**Story:** `tasks/story-v1.5.2-journal-ux-pack.md`
**Depends on:** task-v1.5.2-4 (screenshot media must be recorded in
the journal first).

## Summary

Show images that were sent to the model (screenshots today) as
thumbnails in the Journal feed, served through the existing
authenticated media transport - the same pattern audio tiles already
use.

## Context you need

- task-v1.5.2-4's outcome: the media reference shape for screenshot
  png files on user events (`src/jarvis/journal/events.py`,
  `recorder.py`).
- `src/jarvis/ui/transport.py`: `_journal_media_handler()`,
  `_journal_media_url()`, `_resolve_journal_media_path()` - the serving
  path and its traversal guards; extend content-type handling for PNG
  if needed, do not add a second serving path.
- `src/jarvis/ui/status_console_ui/app.js`: audio tile rendering in the
  feed - the shape to mirror for image tiles.

## Boundary

- Rendering plus, if necessary, content-type support in the existing
  media handler. No new endpoints, no `file://` URLs, no image
  processing/resizing on the backend - "thumbnail" is a CSS-constrained
  rendering of the original file.
- Feed layout stays; an image tile occupies the same kind of slot as an
  audio tile.

## Requirements

- Feed events with an image media reference render an inline thumbnail
  loaded via the authenticated media URL (token pattern identical to
  audio).
- A missing/unloadable media file degrades to a localized placeholder,
  not a broken-image icon or a JS error.
- Thumbnails are size-capped by CSS so a full-resolution screenshot
  cannot blow up the feed; clicking is not required scope (no lightbox).
- Hidden mode behavior is unchanged: no feed, no media requests.

## Acceptance criteria

- [ ] Tests cover media-URL construction for image events and the
      content-type returned by the media handler for PNG (alongside the
      existing audio case).
- [ ] Human-run manual handoff covers: a screenshot turn produces a
      thumbnail in the live feed and after reload, and the missing-file
      placeholder renders when the media file is removed on disk.
- [ ] `python -m pytest` and Ruff checks are green.
