# Task: Visual language pass - hierarchy, typography, honesty fixes

**Story:** `tasks/story-ui-ux-maturity.md`
**Status:** Completed.
**Release:** post-v1.8.0 (owner to assign).
**Created:** 2026-08-09 (from the owner's live-interface review).
**Scope class:** front-end only (`status_console_ui/*.css`, minimal
`*.js`/`index.html` for control-type swaps and hiding dead affordances).
No engine, transport, or control-command changes.

## Scope narrowed on close (2026-08-11)

This card originally carried both the objective fixes (1-3) and the
subjective design items (4-7). The owner approved the mockup for 4-7 but
asked to close and merge this card for its objective scope only, splitting
the (already-approved) subjective restyle into its own follow-up card:
`tasks/task-ui-ux-5-visual-restyle.md`. Items 4-7 below are kept verbatim
for history/context; they are no longer this card's acceptance criteria -
see the new card for those.

## Summary

A review of the running app (Status, Journal, Settings) found the visual
language reads as a debug console rather than a mature product, and
carries a few objective defects. This task raises the visual maturity with
a *specific* checklist, not a vague "make it nicer", and separates
objective fixes (which need no design taste) from subjective design
choices (which do, and go through a mockup the owner signs off first).

## Objective fixes (no design judgment needed)

1. **Dead reset affordances.** Every Status module chip shows a `↺` reset
   button, but `reset_module` only publishes a "not implemented"
   `SystemEvent`. Hide the reset control until a real per-module reset
   exists (consistent with task 2 omitting a Reset context-menu item).
   Do not remove the underlying wiring - only the affordance.
2. **Native form controls break the dark theme.** Checkboxes (Status tool
   lists) and `<select>`s (Settings, e.g. the Piper/Silero engine and
   yes/no dropdowns) render with OS light styling. Theme them to match the
   dark surface (custom checkbox styling; dark-styled selects with a
   themed dropdown affordance), keeping full keyboard operability from
   task 1.
3. **Inconsistent local-tool labels.** "Локальные инструменты" mixes human
   labels ("Доступ к камере", "Запись в память") with raw identifiers
   (`read_history`, `read_history_ranges`). Adopt one rule: a human label
   as the primary line with the identifier secondary/dimmed (the existing
   `_tool_payload` already carries `name` and a model-facing
   `description`; a `ui_description`/label source may be needed rather
   than reusing the model-facing text - decide in the mockup).

## Subjective design (moved to `task-ui-ux-5-visual-restyle.md`)

4. **Monospace scope.** Reserve the monospace face for genuinely technical
   or tabular data (timestamps, byte sizes, model ids, log lines) and move
   section labels, buttons, and headings to the proportional UI face.
5. **Accent-emphasis scale.** Introduce 2-3 emphasis tiers (primary /
   secondary / ghost) so a primary action reads as primary. Reconcile the
   lone purple selected reasoning-level chip with the otherwise-cyan accent
   system (either fold it into the cyan scale or make purple a deliberate,
   repeated semantic - not a one-off).
6. **Icon set.** A light, consistent inline-SVG icon set for the recurring
   actions (new, continue, delete, memory, annotations, consolidation,
   copy) to cut text weight and pair with the task-2 context menus.
7. **Session-card weight.** Invert the card hierarchy so the title (the
   session's identity) is primary and the timestamp/size are secondary.
   (Derived, non-distinguishing "New context" titles remain a separate,
   out-of-scope limitation.)

## Boundary

- Front-end only; no engine/transport/control changes and no new engine
  capability. Hiding the reset affordance does not remove `reset_module`.
- No editable session titles, no command palette, no Status-chip roving
  navigation (those belong to other tasks or are out of story scope).
- Subjective items (4-7) are out of this card's closed scope; see
  `task-ui-ux-5-visual-restyle.md`.

## Acceptance criteria

- [x] An annotated before/after mockup (Status, Journal sidebar/feed,
      Settings TTS section) is produced and approved by the owner
      (2026-08-11) - implementation moved to `task-ui-ux-5-visual-restyle.md`.
- [x] Module-chip reset affordances are hidden while `reset_module` is a
      stub; wiring is untouched.
- [x] Checkboxes and selects match the dark theme in all three views and
      remain fully keyboard-operable.
- [x] Local-tool rows use one consistent label rule.
- [x] New/changed user-facing strings exist in both `en` and `ru`.
- [x] Browser-preview handoff prepared covering all three views in light
      and dark surfaces where applicable.
- [x] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

**Objective fixes (2026-08-11):**
- `reset_module` (status_console.py) confirmed to only publish a "not
  implemented" `SystemEvent`; `.chip-reset` hidden via CSS
  (`display: none`), `app.js`'s `requestModuleReset()`/`reset_module`
  wiring untouched.
- Native checkboxes: `accent-color: var(--cyan)` + `color-scheme: dark`
  on `:root`. Native selects: `appearance: none` with a CSS two-gradient
  chevron (no image asset, keeps the "no network-loaded assets"
  guarantee tests/test_status_console.py and tests/test_ui_qa.py already
  enforce - an initial SVG data-URI attempt with an `xmlns="http://..."`
  namespace tripped those tests and was replaced).
- Local-tool labels: `search_history`/`read_history`/`read_history_ranges`
  (`jarvis.tools.history`) had no `tool_label_*` entry and fell back to
  their raw snake_case name - the actual mechanism behind the story's
  "mixes human labels with raw identifiers" finding (BuiltinToolProvider's
  3 tools already had labels; HistoryToolProvider's 3 did not). Added all
  6 entries (en+ru) to `strings.js`; added
  `test_every_history_tool_has_a_capability_label_in_every_language` to
  `tests/test_ui_i18n.py` as a regression guard, mirroring the existing
  builtin-tool guard.
- Stop-time review (Codex) caught that the fix was incomplete: item 3's
  "one rule" is human label primary, identifier secondary/dimmed - only
  the label-source *question* ("a `ui_description` field may be needed")
  was deferred to the mockup, not the display rule itself. Filling in the
  missing translations alone did not make the identifier visible, only
  the tooltip/aria-label carried it. Fixed in `renderToolList()` (app.js):
  each row now renders `.tool-row-name` (primary, full-brightness) plus a
  `.tool-row-id` suffix (dimmed, shown only when the label differs from
  `tool.name`, so unlabelled third-party MCP tools do not repeat their own
  name). CSS reuses the existing `--text`/`--text-faint` hierarchy
  (`.chip-label`/`.chip-meta`'s pattern) and does not touch font-family -
  the row stays in its current inherited monospace; swapping that face is
  item 4, still mockup-gated.
- Verified live in the Browser pane against `index.html` (seeded via the
  exposed `apply*()` functions) across Status, Settings, and Journal:
  reset buttons absent, tool-row checkboxes and Settings
  checkboxes/selects (including the previously-unstyled Piper/Silero
  engine picker) render dark-themed, local-tool labels human-readable.
  No console errors.
- `python -m pytest`: 2019 passed, 1 skipped (pre-existing, hardware).
  `ruff check` and `ruff format --check`: clean.
- `tools/graphify.ps1 update` run after the source changes.

**Subjective design mockup (2026-08-11):** annotated before/after mockup
built and published as an Artifact, covering items 4-7 across Status,
Journal sidebar/feed, and Settings TTS, plus reference specimens for the
accent-emphasis scale and icon set. Verified rendering in both light and
dark themes. Owner reviewed and approved the mockup (2026-08-11), then
asked to close this card for its objective scope only and split
implementation of 4-7 into `tasks/task-ui-ux-5-visual-restyle.md`. No
CSS/JS for items 4-7 was touched under this card.

**Closed 2026-08-11.** Merged to `main`.
