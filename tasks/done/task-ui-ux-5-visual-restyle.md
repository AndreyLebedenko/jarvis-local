# Task: Visual language pass - subjective restyle (monospace scope, accent scale, icons, session-card weight)

**Story:** `tasks/done/story-ui-ux-maturity.md`
**Status:** Completed.
**Release:** post-v1.8.0 (owner to assign).
**Created:** 2026-08-11 (split from task-ui-ux-4-visual-pass.md).
**Scope class:** front-end only (`status_console_ui/*.css`, `*.js` for
control-type/markup swaps needed to attach icons and restructure the
session card). No engine, transport, or control-command changes.

## Summary

`task-ui-ux-4-visual-pass.md` separated objective fixes (no design taste
needed - done, closed) from subjective design (gated on an owner-approved
mockup). The owner approved that mockup on 2026-08-11. This card
implements exactly what it showed - four items, none of them requiring
further design judgment since the design decisions are already made and
signed off.

## Design reference

The approved mockup (annotated before/after for Status, Journal
sidebar/feed, and Settings TTS, plus accent-scale and icon-set specimens)
was published as a Claude Artifact during task-ui-ux-4's work and reviewed
live by the owner. The decisions below are the mockup's content, recorded
here so this card does not depend on that artifact's URL staying
reachable.

## Requirements

1. **Monospace scope.** Move to the proportional face (matching the
   existing `.chip-label`/card-title convention): section labels/headings
   (`MODULES`, `SESSIONS`, `SPEECH SYNTHESIS (TTS)`, `VOICE DETECTION
   (VAD)`), segmented-toggle button labels (view toggle, visibility
   toggle, reasoning-level toggle), all standalone action buttons (Apply,
   Send, New context, Attach, Memory/Annotations/Consolidation toolbar,
   Shut down), and local/MCP tool-row primary labels (`.tool-row-name`,
   added in task-ui-ux-4). Keep monospace for genuinely technical/tabular
   data: `.chip-meta`, log timestamps/entries, journal session
   timestamp+size, journal usage total, `.tool-row-id` (the identifier
   suffix task-ui-ux-4 already added), VAD numeric inputs, the `level:
   off` tag.
2. **Accent-emphasis scale.** Three tiers, reused across every view:
   - **Primary** (solid `--cyan` fill, dark text): the one commit/create
     action per view - Settings "Apply", Journal input dock "Send",
     Journal sidebar "New context".
   - **Secondary** (today's default look: `--cyan-tint` fill + `--cyan-
     dim` border + `--cyan` text): standing toggles' selected state,
     panel togglers (Memory/Annotations/Consolidation), Enable/Disable,
     MCP Enable/Disable, Attach.
   - **Ghost** (transparent, dim text, border appears on hover): Copy
     actions, Close buttons, session-row icon actions.
   - **Reasoning-level chip:** fold the selected pill's color from
     `--violet` to `--cyan`, matching the View and Open/Hidden segmented
     toggles it sits next to (all three are "one selected option in a
     row" controls and should share one selected-state color). Do not
     remove `--violet` from the palette - Hidden mode keeps it.
3. **Icon set.** Inline-SVG, outline style (24px viewBox, `currentColor`,
   ~1.75px stroke, round linecap/linejoin, no fill) matching the console's
   existing thin-line vocabulary (chip borders, ring, dots). Seven icons,
   wired to their existing actions (no new engine capability - these
   attach to commands that already exist):
   - **New** - Journal sidebar "+ New context" (primary button)
   - **Continue** - session row continue-conversation action (replaces
     the `&#8618;` glyph)
   - **Delete** - session row delete action (replaces the `&times;` glyph)
   - **Memory** - Journal toolbar Memory panel toggle
   - **Annotations** - Journal toolbar Annotations panel toggle
   - **Consolidation** - Journal toolbar Consolidation panel toggle
   - **Copy** - Journal feed copy-answer / copy-title / copy-name actions
4. **Session-card weight.** Invert `_journalSessionElement()`'s reading
   order: session title first (proportional face, full `--text`
   brightness, not dimmed by default), then one combined secondary line
   below it (date, time, duration, size - dimmed, monospace, single line
   in place of today's separate `.journal-session-when`/
   `.journal-session-size` rows). Selection state keeps its current
   border/tint treatment; the timestamp no longer needs to turn cyan to
   signal selection. Derived, non-distinguishing "New context" titles
   remain a separate, already-recorded, out-of-scope limitation.

## Boundary

- Front-end only; no engine/transport/control changes and no new engine
  capability - icons attach to commands that already exist
  (`deleteJournalSession`, `continueJournalSession`, the panel togglers,
  the copy actions).
- No editable session titles, no command palette, no Status-chip roving
  navigation (out of story scope).
- No further design review needed for the four items above - the mockup
  already carries owner approval. A genuinely new visual decision not
  covered by the mockup (not expected, but possible once real markup is
  touched) still stops for a question per this repo's standing rule
  (`CLAUDE.md` section 0.4/0.2).

## Acceptance criteria

- [x] Monospace is confined to technical/tabular data; the labels,
      buttons, headings, and tool-row primary labels listed above use the
      proportional face.
- [x] The three-tier accent-emphasis scale is applied per the mapping
      above; the reasoning-level selected chip is cyan, not violet.
- [x] The seven-icon set is implemented and wired to its existing action
      in each of the seven locations listed above, including all three
      Copy actions (copy-answer, copy-title, copy-name).
- [x] Session cards lead with the title (full brightness, proportional);
      date/time/duration/size are one dimmed monospace line beneath it.
- [x] New/changed user-facing strings (if any icon needs an accessible
      name beyond what already exists) are in both `en` and `ru`.
- [x] Browser-preview handoff prepared covering Status, Journal
      sidebar/feed, and Settings TTS in light and dark surfaces where
      applicable.
- [x] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

**Copy icon in context menus (2026-08-11, corrected after stop-time
review):** an earlier pass of this card left "Copy title" (session menu)
and "Copy name" (tool-row menu) text-only, reasoning that the shared
`openContextMenu()` dropdown (interaction.js) had never carried icons and
adding one to only 2 of its several entries would be an unreviewed
decision. Stop-time review (Codex) correctly flagged this as not meeting
requirement 3 as written, which names copy-title/copy-name explicitly.
Re-read against the requirement: the icon set is deliberately selective
(only Continue/Delete/Memory/Annotations/Consolidation/Copy exist as
icons at all - Generate transcript/Generate annotation/Enable/Disable are
not in the set and were never going to get one), so "only some menu
entries carry an icon" is the intended shape, not an inconsistency to
avoid. Implemented properly: `openContextMenu()` (interaction.js) now
accepts an optional `entry.icon` (a prebuilt DOM node) and prepends it to
the menu item, without interaction.js gaining any knowledge of what an
icon is or where its path data lives - the same separation the file
already keeps for `uiString()`/engine calls (see its header comment,
extended here rather than broken). `_toolRowMenuEntries` (Copy name),
`_journalSessionMenuEntries` (Copy title), and `_journalMessageMenuEntries`
(Copy answer, for parity with its own standalone iconed button) now pass
`icon: _icon("copy")`. Verified in the Browser pane: the copy icon
renders on all three menu entries while Continue/Delete/Generate
annotation stay text-only in the same menus, exactly matching the
icon set's actual (selective) scope.

**Implementation notes (2026-08-11):**
- `.config-section-label` ("Speech synthesis (TTS)" / "Voice detection
  (VAD)") and `.journal-input-dock button` (Attach/Send) turned out to
  already have no `font-family` override - already inheriting the
  proportional body font before this task touched anything. No CSS change
  needed there; only Send's *color* changed (secondary -> primary).
- Extended the proportional-face rule to `.confirm-row button` (the
  shutdown confirmation's Cancel/Shut down) even though it is not named in
  the requirements list above: it is the direct continuation of
  `.btn-shutdown`, which is named, and leaving it in monospace would have
  made the same flow visibly inconsistent between the trigger and its own
  confirmation.
- New icon helper `_icon(name)` (app.js) builds via a throwaway
  `innerHTML` wrapper rather than `document.createElementNS` - the HTML
  parser enters SVG insertion mode on its own for an `<svg>` start tag, so
  no XML namespace URI string is ever written into the file. An initial
  `createElementNS("http://www.w3.org/2000/svg", ...)` attempt tripped the
  same "no network-loaded assets" tests task-ui-ux-4's select-arrow CSS
  hit (literal `http://` substring, never an actual fetch) - same class of
  false positive, same fix shape (avoid the literal), different mechanism.
- Fixed a latent bug while wiring the Copy icon: `copyJournalAnswer()`'s
  "flash to Copied, then restore" used to read/write the whole button's
  `textContent`. Adding an icon child would have meant the first copy
  click permanently deleted it (textContent flattens, so "restoring the
  original" restores flat text, not the icon+span structure). Moved the
  flash onto a dedicated inner label `<span>` instead - verified in the
  Browser pane that the icon survives a flash-and-restore cycle.
- `_journalSessionElement()`, `toggleJournal{Memory,Annotation,
  Consolidation}Panel()` and their `_clear*Panel()` counterparts updated;
  the three toggle buttons' dynamic label writes now target an inner
  `.toggle-label` span (added in index.html) instead of the button's own
  `textContent`, for the same reason - a blind textContent write would
  delete the prepended icon. `data-i18n` moved from the buttons to the
  inner spans so `applyUiLanguage()`'s re-stamp does not do the same;
  verified a live `applyUiLanguage({language: "ru"})` round-trip keeps the
  icon and correctly localizes the label.
- Verified in the Browser pane (seeded via `apply*()` and, for Journal -
  which has no live transport in this static preview - by calling
  `_journalSessionElement()`/`_journalEventElement()` directly) across
  Status, Settings, and Journal: proportional headings/buttons/tool
  labels, cyan reasoning chip, solid-fill Apply/Send/New context next to
  unchanged cyan-tint Attach, cyan-tint Memory/Annotations/Consolidation
  toolbar with icons, session cards leading with title, session
  continue/delete icons, copy-answer icon. No console errors other than
  the expected `NotAllowedError` from `navigator.clipboard.writeText` in
  the sandboxed static-file preview (pre-existing, not touched here -
  confirmed unrelated by exercising the flash/restore logic directly).
- `python -m pytest`: 2019 passed, 1 skipped (pre-existing, hardware).
  `ruff check` / `ruff format --check`: clean. One existing test
  (`tests/test_journal_live_ui.py::test_assistant_copy_button_copies_
  recorded_text`) pinned the old `copyJournalAnswer(event.text, copy)`
  call site verbatim; updated to the new `copyLabel` argument.
- `tools/graphify.ps1 update` run after the source changes.

**Regression test for the Copy icon fix (2026-08-11, second stop-time
review):** the first pass of the fix above shipped without a test, so a
future edit could silently drop `entry.icon` from any of the three call
sites (or from `openContextMenu()` itself) with nothing to catch it -
exactly the shape of the regression this whole correction exists to fix.
Added `tests/test_context_menu_icons.py`: one test pins
`openContextMenu()`'s `if (entry.icon) item.appendChild(entry.icon);`
mechanism (ordered before the label is appended, so the icon leads), and
three tests pin `icon: _icon("copy")` on each call site's Copy entry
(`_toolRowMenuEntries`, `_journalSessionMenuEntries`,
`_journalMessageMenuEntries`). Verified the regression tests actually
regress: temporarily removed the `_toolRowMenuEntries` icon line, confirmed
only `test_tool_row_copy_name_entry_carries_the_copy_icon` failed, restored
it, reran - `python -m pytest`: 2023 passed, 1 skipped. `ruff check` /
`ruff format --check`: clean.
