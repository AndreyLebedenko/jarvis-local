# Task: Tool rows name capabilities, not identifiers

**Status:** Completed.
**Verified:** owner-run visual check, 2026-07-25.
**Raised by:** owner, 2026-07-25, reviewing the split tool panels: "why
should a user know the option is called `capture_camera_image`, when all
he needs is to find the checkbox for camera access?"
**Follows:** `tasks/task-tool-row-states-and-refresh.md` and
`tasks/task-local-and-external-tool-panels.md`. Those made the rows
truthful; this one makes them readable.

## Summary

The tool list is a permission list, so each row should name a capability
in the user's language. The identifier is a developer artifact and moves
to a hover tooltip, alongside the tool's own description.

## Context you need

- `src/jarvis/ui/status_console_ui/app.js`, `renderToolList()`: a row is
  currently `name - provider - unavailable`, where `name` is the raw
  registry identifier.
- `src/jarvis/tools/registry.py:18`, `RegisteredTool.description`: this
  is model-facing text. For MCP tools it is the server author's, unless
  the owner overrode it in `tool_adapters`
  (`src/jarvis/tools/provider_adapter.py:60`:
  `adapter.description or declaration.description`).
- `src/jarvis/ui/status_console_ui/strings.js`: `en` and `ru` key sets
  must stay identical, and `tests/test_ui_i18n.py` asserts it, including
  a dedicated test for keys app.js builds dynamically.
- The events panel keeps printing raw tool names, because it is an audit
  record of what actually ran.

## Boundary

- The Status tab's tool rows. No change to what any switch does, to the
  registry, or to the model-facing tool surface.
- No new config. Reuses the description that already reaches the UI.
- The touchstrip has no tool list, so hover-only is acceptable here and
  this card does not touch that surface.

## Requirements

- A builtin tool shows a curated label naming what it lets Jarvis do, in
  both interface languages, one to three words. Name the capability, not
  the subsystem, so a row cannot be confused with the module chip beside
  it: "Camera access", not "Camera".
- An MCP tool keeps its raw name. Do not invent a friendly label for a
  third-party tool: a wrong friendly name on something that reaches the
  network is worse than an ugly true one, and this is the same honesty
  axis as the data-source badge. A missing curated label falls back to
  the raw name, never to a guess.
- Every row carries a mouse-only tooltip with the identifier and the
  tool's description. One rule for both kinds - builtin descriptions are
  just as model-facing as MCP ones, so a special case would only hide
  that fact. The native `title` attribute is hover-only already; no
  tooltip component is needed.
- The description does not go into `aria-label`: a screen reader would
  read a whole model instruction aloud. Accessible naming stays the human
  label plus the identifier.
- `capture_camera_image`'s privacy hint is removed. "Camera access" is
  that statement, so the extra words and their catalog string go.
- Automated tests: a builtin tool renders its curated label and not its
  identifier; an MCP tool renders its raw name; a tool with no curated
  label falls back to the raw name; the label keys exist in every
  language; the tooltip carries identifier and description.

## Acceptance criteria

- [x] No raw identifier is visible in the Status tab's tool rows for
      builtin tools; hovering a row still reveals it.
- [x] MCP rows are unchanged in naming and are never given an invented
      label.
- [x] `python -m pytest` and Ruff are green.
- [x] Owner-run visual check in both languages, hover included.

## Outcome

Landed as specified. Labels are "Camera access", "Memory writes",
"Reasoning level" in both languages; the identifier and the description
travel in a native `title`, which is hover-only already, so no tooltip
component was written.

The fallback needed a new helper. `uiString()` throws on an unknown key,
which is right for a programming error but wrong here, where a missing
label is the expected answer for a third-party tool. `optionalUiString()`
returns null instead, so the row falls back to the real name rather than
to an invented one.

`is_privacy_switch` was removed along with the last marker on the camera
row. A violet tint went first, then a brightened row; both were codes that
cannot say what they mean, and "Camera access" is the statement they were
reaching for - which left the payload field with no consumer.

Both decisions below are recorded in `PROJECT.md`.

Not exercised live: MCP rows kept their real names in the code path, but
no MCP server was connected during the check, so the fallback has only
automated coverage so far. It will show itself the first time a server
comes up.

## Decision recorded in PROJECT.md

The console deliberately carries two vocabularies: capability labels in
the permission list, raw identifiers in the events panel. The audit
record must keep saying exactly what ran, so the tooltip is the bridge
between them rather than a reason to rename either surface.

Second decision, and the one worth guarding: `description` now has two
audiences - the model that reads it to decide when to call a tool, and
the human who hovers a row. This is accepted deliberately rather than
solved with a second field, because the owner writes his own config and
one field is less ceremony than two. The boundary that keeps it honest:
the text stays optimized for the model, and the tooltip shows whatever
that happens to be. If the two audiences ever genuinely conflict, the
answer is a separate `ui_description`, never a rewrite of the
model-facing string into UI copy.
