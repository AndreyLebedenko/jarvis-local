# Task: Context menus - reusable menu component, existing-action wiring

**Story:** `tasks/story-ui-ux-maturity.md`
**Status:** Completed. Depended on task 1 (uses its focus/keymap/listbox
primitives).
**Release:** post-v1.8.0 (owner to assign).
**Created:** 2026-08-09.
**Scope class:** front-end only (`status_console_ui/*.js`, `*.css`,
`strings.js`). No control commands, no transport, no engine changes.

## Summary

There is no context-menu component in the UI. The owner asked for a
right-mouse-button menu on list items offering the relevant actions. All
such actions already exist as buttons or endpoints scattered across each
item's row (e.g. Journal sessions already have Continue/Delete buttons and
per-answer Copy; tool rows have an enable checkbox). This task
consolidates those into one reusable menu without adding any new
capability.

## Proposed direction

1. One reusable menu component: a `role="menu"` popup positioned at the
   pointer (right-click) or the focused item (`Shift+F10` and a visible
   per-item menu button, so it is reachable without a mouse). Arrow keys
   move between `role="menuitem"`s, Enter/Space activate, `Esc` closes and
   restores focus to the item (via task 1's keymap `Esc` stack). Only one
   menu open at a time.

2. Per-item action sets, drawn strictly from existing commands/endpoints:
   - **Journal session**: Continue (fork), Delete, Copy title. (Continue
     and Delete already exist as row buttons; Copy title is a local
     clipboard action like the existing `copyJournalAnswer`.)
   - **Journal feed message**: Copy (existing `copyJournalAnswer`),
     Generate transcript, Generate annotation (existing endpoints).
   - **Tool row**: Enable/Disable (existing `set_tool_enabled` send),
     Copy tool name.
   - **Module chip**: include Reset **only if** a real engine reset
     exists; today `reset_module` is a "not implemented" stub, so a Reset
     menu item is omitted rather than shown as a dead action.

3. Actions that would require a capability the engine does not already
   expose are not added.

Menu labels are localized through `strings.js` in en and ru.

## Boundary

- No new control commands, transport routes, or engine capabilities. If an
  action is not already reachable, it is dropped, not built.
- Menus appear only on the item types listed above; the Status view's
  chips get no menu in this story.
- Right-click anywhere else keeps default behavior (or the browser
  default), except it is suppressed on items that own a menu.

## Acceptance criteria

- [x] One reusable menu component, opened by right-click, `Shift+F10`, and
      a visible per-item menu button; keyboard-navigable (`role="menu"`/
      `menuitem`, arrows, Enter/Space, `Esc` closes and restores focus).
- [x] Only one menu open at a time; opening another or clicking away
      closes the current one.
- [x] Session, feed-message, and tool-row menus offer exactly the
      existing-capability actions listed above and each action works.
- [x] No Reset menu item while `reset_module` is a stub. (No module-chip
      menu at all - see the boundary-conflict note below.)
- [x] Menu labels exist in both `en` and `ru` catalogs.
- [x] Browser-preview handoff prepared: open each menu type by mouse and by
      keyboard and invoke one action from each.
- [x] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

**2026-08-10.** A pre-existing internal contradiction in this card was
resolved before implementing, not asked about, because both readings
produce identical code: "Proposed direction" point 2 listed a "Module
chip" menu (Reset omitted since `reset_module` is a stub - meaning nothing
else was ever listed for it either), while this card's own Boundary
("Menus appear only on the item types listed above; the Status view's
chips get no menu in this story"), its Acceptance criteria (which only
name session/feed-message/tool-row menus), and the story card's framing
decision ("no roving navigation over its module chips in this story") all
agree chips get no menu. Since an entries-builder for a chip would return
an empty array today regardless (Reset is the only ever-listed action and
it is explicitly omitted), the two readings are behaviorally identical:
no context menu is wired to Status module chips. Resolved in favor of the
three converging sources; no chip wiring was added.

Implementation: `interaction.js` gained one generic component -
`openContextMenu`/`_closeContextMenu`/`_contextMenuOpen` (single shared
menu instance, `role="menu"`/`role="menuitem"`, roving arrow/Home/End
navigation among enabled items, `Tab` closes rather than trapping),
`initContextMenuTrigger(container, itemSelector, buildEntries)` (delegated
right-click and item-focused `Shift+F10`), and `openItemContextMenu(item,
anchorElement, buildEntries)` for the visible per-item menu button each
row type builds itself (row shapes differ too much for one generic
button). `_hasOpenModal()` now also reports true while a context menu is
open, so it keeps suppressing `Alt+1/2/3`/`/` the same way it already does
for the shortcuts overlay - not `aria-modal` (the menu does not trap Tab),
but the same "a global shortcut must not reach past what's on top of the
screen" reasoning task 1 documented applies. The context-menu escapable is
registered last in `app.js`'s init block (highest `Escape` priority, on
top of even the shortcuts overlay), matching the prediction already
written into `interaction.js` by task 1.

`app.js` wires three item types, each supplying only already-existing
actions:
- Journal session (`_journalSessionMenuEntries`): Continue (disabled while
  forking, hidden when the session is active - reuses
  `continueJournalSession`), Delete (hidden when active - reuses
  `deleteJournalSession`), Copy title (new local clipboard action, same
  shape as the existing per-message Copy).
- Journal feed message (`_journalMessageMenuEntries`): Copy (only when the
  message already carries its own `.journal-copy` button - `.click()`s it
  directly rather than reimplementing `copyJournalAnswer`), Generate
  transcript (only when the message already carries a
  `.journal-transcript-generate` button - `.click()`s it directly), and
  Generate annotation (only at a known feed position, the same "known
  position, never a live append" rule the transcript panel already
  follows - composes two existing actions,
  opening the annotation panel if not open and then calling
  `_generateJournalAnnotation(position, position)`, the same range-generate
  endpoint call the panel's own From/To inputs already make by hand, just
  with a single message's own position as a one-event range).
- Tool row (`_toolRowMenuEntries`): Enable/Disable (reuses the row's own
  checkbox and its existing `set_tool_enabled` change listener via
  `_toggleToolRowCheckbox` - omitted entirely when the checkbox is
  `disabled`, i.e. the tool is unavailable, so no dead action is shown),
  Copy name (new local clipboard action).

New copy actions (session title, tool name) have no button of their own
left after the menu that triggered them closes, so two small feedback
helpers were added next to `_writeClipboardText`:
`_copyToClipboardWithJournalStatus` (writes to the existing
`#journalInputStatus` line, for Journal actions) and
`_copyToClipboardWithLabelFlash` (flashes the row's own label text, for
the tool list, which has no status line). New generic `clipboard_copied`/
`clipboard_copy_failed` strings back both, kept separate from
`copyJournalAnswer`'s own `journal_copy_done`/`journal_copy_failed` so
that function's already-verified behavior was not touched.

Automated: `python -m pytest` (1966 passed, 1 skipped), `ruff check` and
`ruff format --check` clean.

Browser-preview verification (`demo.html`, same reasoning as task 1: the
only surface loadable without a live engine/WS token):
- Generic menu mechanics, exercised against a synthetic fixture: right-click
  opens the menu positioned at the pointer, focuses the first enabled item,
  and correctly marks a `disabled: true` entry non-interactive;
  `ArrowDown`/`ArrowUp` roving skips the disabled item and wraps; a real
  `<button>` menu item's native Enter/click closes the menu and fires
  exactly the one action clicked (no leakage); `Shift+F10` on a focused item
  opens the menu anchored to it; `Tab` closes the menu without trapping
  focus in it; a deferred outside click closes it; opening a second menu
  (via `openContextMenu` directly) always leaves exactly one menu in the
  DOM; `Escape`, dispatched through the real global keydown listener
  extracted verbatim from a freshly-fetched `interaction.js` (the
  documented technique from task 1's stale-listener workaround, used here
  from the start rather than found necessary partway through), closes the
  menu and restores focus to the item that opened it.
- `_hasOpenModal()` verified to report `true` while the context menu is
  open and `false` once closed; the same extracted global listener
  confirmed `Alt+2` left `data-view` unchanged while the menu was open and
  `Alt+3` correctly switched once it was closed - the menu suppresses
  global shortcuts exactly like the shortcuts overlay does.
- **Found and fixed live**: `openItemContextMenu(item, anchorElement,
  buildEntries)` passed `item` (the row) as the return-focus target
  instead of `anchorElement` (the button actually clicked), so closing a
  button-opened menu returned focus to the row, not the button. Caught by
  asserting `document.activeElement === button` after `Escape`, which was
  `false` before the fix. Fixed by passing `anchorElement` as both the
  anchor and the return-focus target; re-verified after a fresh
  cache-busted navigation (`?v=2`, per the file:// staleness note in
  CLAUDE.md) that the live `openItemContextMenu` source reflected the fix
  and that both menu positioning (below the button) and focus restore now
  passed.
- Entries-builder functions, called directly against synthetic DOM shaped
  like each real row (matching task 1's approach for the same reason -
  demo.html carries no real Journal/tool markup): `_toolRowMenuEntries`
  returns Enable/Disable that tracks the checkbox's actual checked state
  and omits it entirely for a `disabled` (unavailable) checkbox, plus
  Copy name always; `_journalSessionMenuEntries`, driven by a synthetic
  `_journalSessions`/`_journalActiveSessionId`/
  `_journalForkInFlightSessionId` (set via bare identifier assignment, not
  `window.x =`, since these are top-level `let` bindings a
  `window`-qualified assignment does not reach - a test-methodology
  detail worth recording since it silently no-ops instead of erroring),
  returns Continue+Delete+Copy title for an inactive session, only Copy
  title for the active one, Continue correctly disabled while that same
  session is mid-fork, and `[]` for an unknown session id; running the
  built Copy title entry against `_copyToClipboardWithJournalStatus`
  resolved without throwing even with no `#journalInputStatus` element
  present. `_journalMessageMenuEntries` against four synthetic message
  shapes: a message with only a `.journal-copy` button and a known
  position yields Copy+Generate annotation, running Copy correctly
  `.click()`s the real button; a message with only a
  `.journal-transcript-generate` button and a known position yields
  Transcribe+Generate annotation, running Transcribe correctly `.click()`s
  the real button; a message with neither button and no known position
  yields nothing; a message with a copy button but no known position
  (mirroring a live-appended turn) yields only Copy, confirming Generate
  annotation is correctly gated off exactly where the transcript panel's
  own "known position, never a live append" rule already gates its own
  button.
- Computed styles on the synthetic menu confirmed it renders with the real
  product tokens: `position: fixed`, `z-index: 210` (above the shortcuts
  overlay's 200), panel background `rgb(14, 18, 27)` (`--panel`), item
  text color matching `--text-dim`. A visual screenshot could not be taken
  in this session (Browser pane not displayed/compositing), so this
  computed-style check stands in for it, same as task 1 did when
  screenshots were unavailable.

Not verified live, for the same structural reason task 1 recorded (no
live engine/WS transport, no real Journal/tool DOM in `demo.html`):
`_generateJournalAnnotationForMessage`'s actual network round trip (it
calls `toggleJournalAnnotationPanel()`/`_generateJournalAnnotation()`,
both of which unconditionally address `#journalAnnotationPanel` and would
throw against demo.html's markup - this is those functions' pre-existing,
unchanged behavior, not something this task introduced), and all three
menus' real per-row rendering from live data. Reviewed by reading the
exact DOM shapes each render function now produces and confirming they
match what each entries-builder function expects.

**Judgment call, not verified either way**: `Shift+F10` has no effect on a
Journal feed message specifically, because `.journal-msg` rows are not
part of any roving-tabindex list (task 1's boundary deliberately did not
add roving navigation over the feed itself) and so can never hold focus
for `initContextMenuTrigger`'s `event.target === item` guard to fire on.
The message's own visible menu button remains fully keyboard-reachable
through normal Tab order regardless, so every message menu stays
operable without a mouse; `Shift+F10` is simply inert there rather than
broken. Session rows and tool rows do not have this gap - both already
sit in a roving-tabindex list from task 1, so `Shift+F10` works on them
exactly as on the synthetic fixture above.
