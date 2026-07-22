# Story v1.6.3: Status Console UI reorganization

**Status:** Completed 2026-07-22. All four task cards are done and the
human verification run passed, on the combined checklist in
`tasks/done/task-v1.6.4-3-docs-and-release-verification.md`. That run
found one defect this story had introduced - the relocated configuration
form was clipped at the top on a short window, because `align-self:
center` changed meaning when the panel moved from a column flex to a row
flex - fixed in the same change, with a regression test.
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.6.3 section, added
2026-07-20 by owner decision from the UI review dialog).
**Created:** 2026-07-20.

## User-facing goal

Replace the current scatter of buttons and inline forms with three
tabs - Status, Journal, Settings - so the console reads as one coherent
surface: live engine state where you glance, conversation where you
talk, cold configuration where you rarely go.

## Boundaries

- Layout-only story: no new features, no new engine state, no
  transport/contract changes beyond what moving existing controls
  between views strictly requires. Every control that exists before
  this story exists after it (except the two removals below, which are
  deduplications, not feature removals).
- The organizing principle is the nature of the data, not the widget
  inventory (owner-agreed, 2026-07-20):
  - **Status** = live engine state and controls that act immediately;
  - **Journal** = the conversation surface (cross-cutting rule 10
    keeps growing it: memory, attachments);
  - **Settings** = cold configuration, rarely touched.
- Honesty indicators (LOCAL / LOCAL SOURCES) and the Open/Hidden
  switch live in the global header, visible on every tab - the honesty
  axis never disappears behind tab switching.
- Hidden mode semantics are unchanged; the reorganization must not
  create any new path that exposes journal or memory content in
  Hidden mode.
- Localization: all moved/renamed strings go through the existing UI
  language catalog; no hardcoded text.

## Design decisions (agreed in the 2026-07-20 dialog)

- **Three tabs: Status, Journal, Settings.** "Status" (not "Control"):
  the tab primarily answers "what is happening now"; its toggles are
  secondary to that.
- **Runtime state stays on Status:** avatar and engine state, module
  health chips (the v1.6.2 camera chip will join them), reasoning
  level selector, the MCP module toggle with the tool list (v1.6.1
  adds builtin tools and per-tool toggles there - operational state,
  not config), the system events panel, and Shutdown as the single
  destructive action, placed at the bottom, away from frequent
  controls.
- **The settings form moves wholesale to the Settings tab:** model,
  microphone, UI language, TTS voices, and VAD - the complete former
  inline form. The MCP on/off toggle and tool list are runtime and stay
  on Status. The current "Settings" button that merely scrolls to the
  inline form disappears entirely.
- **MCP server configuration stays in `config.toml`** (owner decision,
  2026-07-21, correcting this story's original wording). The story was
  drafted assuming server configuration - commands, adapters - was part
  of the inline form and only needed relocating. It never had any UI:
  it is edited in `config.toml` directly. Building that form is new
  feature work, not relocation, and is out of scope for a layout story.
  Nothing about MCP server configuration changes in v1.6.3.
- **"Last request to model" is compressed, not deleted** (owner
  decision, 2026-07-21). The Journal duplicates most of it through its
  per-message source labels, but has no equivalent for
  `last_request_screenshot` and never shows audio duration. Deleting
  the panel would remove the only place in the UI that answers "was a
  screenshot sent to the model" - an honesty-axis fact. It becomes a
  chip strip under the orb (task-v1.6.3-4). Moving the record into the
  system events panel is the right long-term shape but needs a typed
  event and a contract change, so it belongs to story v1.6.4, not here.
- **Context reset lives only in the Journal.** "Сбросить контекст" on
  the console duplicates the Journal's explicit "Новый контекст"
  (task-v1.5.3-8 made that the canonical, explicit action). The
  console copy is removed; resetting context is a dialog action and
  belongs beside the dialog.

## Scope (ordered task cards)

- `tasks/done/task-v1.6.3-1-tab-shell-and-header.md` - the three-tab
  navigation and the global header (honesty indicators, Open/Hidden).
- `tasks/done/task-v1.6.3-2-content-migration.md` - move the settings form
  to Settings, trim Status to runtime state, remove the duplicate
  context reset, split MCP runtime controls from server config.
- `tasks/done/task-v1.6.3-4-status-vertical-density.md` - fit Status into a
  900 px window by fixing the cause: the "Last request to model"
  section becomes a chip strip under the orb, the column rhythm
  tightens, the MCP tool list gets a bounded height, and the window
  height raised during task 2 is reverted (added 2026-07-21).
- `tasks/done/task-v1.6.3-3-docs-and-verification.md` - docs, localization
  audit, human-run visual review checklist. Runs last, after card 4.

## Acceptance criteria

- [x] The console presents exactly three tabs (Status, Journal,
      Settings); the header with honesty indicators and Open/Hidden is
      visible on all of them.
- [x] Status contains only live state and immediate controls listed
      above; no inline configuration form remains there.
- [x] Settings contains the full configuration form previously inlined
      under the console; the scroll-to-settings button is gone. MCP
      server configuration is not part of this - see the design
      decision above.
- [x] Context reset exists only as the Journal's "Новый контекст";
      behavior of the action itself is unchanged.
- [x] The MCP toggle and tool list remain functional on Status;
      engine-state events keep every moved control honest (no control
      renders stale state after the move).
- [x] Hidden mode presents exactly as before the reorganization.
- [x] All UI text comes from the language catalog in both languages.
- [x] Status fits the default window without an initial scrollbar, and
      a growing MCP tool list cannot displace Shutdown.
- [x] `python -m pytest` and Ruff checks are green; visual review is a
      prepared human-run handoff (WebView review is hardware-scope per
      the testing protocol).

## Stop conditions

- Stop if any control turns out to require new backend state or a
  transport contract change to survive the move - that is scope
  growth beyond a layout story and needs an explicit decision.
- Stop if the Status/Settings split forces duplicating a control on
  both tabs to stay usable - duplication is what this story exists to
  remove, so a case where it seems necessary is a design question,
  not a compromise to make silently.
