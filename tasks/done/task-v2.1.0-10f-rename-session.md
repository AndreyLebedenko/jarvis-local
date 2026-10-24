# Task v2.1.0-10f: Rename a session

Status: Completed.

Story: `tasks/story-v2.1.0-personal-proxy.md`, task 10f. Origin: owner request after the first live
proxy run (2026-10-23): "a feature to rename a session"; all sessions sharing one Journal list make
the list hard to use, and automatic titles ("New context", "Personal proxy session DATE") say
little.

## Summary

A Journal feature for every session kind (assistant, voice-only, MCP, proxy): the user gives a
session a title of their own. The title is session metadata, kept apart from the event records
(which stay immutable), edited from the session's "..." menu, and shown wherever the session
title is shown today: the list, the feed header, search results, "copy title", session info.

## Boundary

The Journal store (a new per-session metadata file and its reader/writer), the title resolution
on the server, the session list/search/info payloads, the Status Console menu entry, an inline
or dialog editor, strings (en, ru), tests, `PROJECT.md`. No change to the event records, to
the Orchestrator, to the proxy pipeline, or to what is sent anywhere. No projects, no paths
or URLs in the metadata yet (see Design). Never read the title into the main model's context
or into the external proxy request.

## Owner decisions (2026-10-24)

1. **Storage: a separate per-session metadata file** next to the session, not a new event in
   the immutable log. The owner expects the file to grow into the place for other session
   metadata (a project id once projects exist, relevant paths/URLs, and so on), so the
   structure must be extensible: a versioned JSON object where the title is one optional
   field, unknown fields are preserved on rewrite, a missing file or missing field means "no
   user metadata". Deleting a session deletes its metadata file.
2. **The user title wins everywhere; an empty title resets to the automatic one.** List,
   header, search, copy title and info show the user title verbatim; clearing the field
   restores the automatic localized title (with the date stamp for proxy sessions).
3. **Any session can be renamed, including the live one.** Limits: at most 80 characters,
   no line breaks or other control characters, leading and trailing spaces trimmed. A longer
   title is cut to 80 (or refused with a message; the developer picks one and states it).

## Design (to be refined by the developer, then reported to the lead before coding)

- A metadata module in the Journal package: a small immutable dataclass (`SessionMetadata`
  with `title: str | None`, plus an `extra` mapping that preserves unknown keys), a reader
  that never raises on a broken or missing file (falls back to "no metadata"), an atomic
  writer (write to a temp file, replace), and a rule to keep the file out of the event log
  and out of fork/consolidation copies unless the developer shows a reason to copy it.
- One place resolves the display title: user title if present, else the automatic one. The
  server function that builds list/search/info rows (`_journal_session_title_and_kind` and
  its callers) uses it; the JS mirror only renders what the server sends.
- Search: the user title is searchable like the automatic ones are today. Decide in the
  design whether the search projection stores it or the list is filtered after the lookup; do
  not rebuild a whole projection on a rename if a cheaper update exists.
- Transport: a rename request on the Journal HTTP API for the session (same style and the same
  access rules as the other session actions, such as delete); it is refused with a clear
  reason when the Journal is unavailable. A rename never goes through the Orchestrator.
- UI: a "Rename" entry in the session's "..." menu (and the context menu that uses the same
  entries); an inline editor in the row or a small dialog, whichever the existing code makes
  simpler; Enter saves, Escape cancels; the field shows the current title and a character
  counter or hard limit; saving an empty value resets. Keyboard reachable, localized.
- Privacy: the title is user-typed text and stays local; it must not appear in logs at INFO
  or above in full, and must not be added to the proxy Journal records or the proxy request.

## Required behavior

1. A session can be renamed from the menu, for each session kind including the live one and a
   proxy session; the new title shows in the list, the feed header, search and "copy title"
   immediately and after a restart.
2. An empty title resets to the automatic title (date stamp for proxy sessions).
3. The 80-character and no-control-character limits hold on the server, not only in the UI.
4. The metadata file is separate from the event records, atomic, tolerant of a missing or
   corrupted file, keeps unknown fields, and is deleted with its session.
5. Event records are unchanged by a rename (a test compares the log bytes before and after).
6. Tests first, including mutation checks by the developer on the limits, the reset, the
   unknown-field preservation and the atomic write; a Node behavior test for the menu entry
   and the editor.
7. `PROJECT.md` states the metadata file, its fields and extension rule.
8. A short human-run handoff (self-sufficient, passing
   `tools/check_handoff_self_sufficiency.py`) for a live check in the Status Console: rename,
   reset, restart, search, a proxy session.

## Acceptance criteria

- [x] Rename works for every session kind and is persistent; reset restores the automatic
      title.
- [x] The title lives in a separate, extensible metadata file; event records are untouched.
- [x] Limits enforced on the server; corrupted or missing metadata never breaks the list.
- [x] Search and "copy title" use the user title; deleting a session deletes its metadata.
- [x] The title never reaches the model context or the proxy request; not in INFO logs.
- [x] The live-check handoff is prepared.
- [x] `python -m pytest`, `ruff check` and `ruff format --check` are green.
