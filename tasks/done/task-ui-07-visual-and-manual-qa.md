# Task UI-07: Visual and manual QA for Status Console

**Story:** story-status-console-ui.md
**Статус:** Completed.
**Приоритет:** средний
**Зависимости:** [task-ui-02-desktop-status-console-shell.md](done/task-ui-02-desktop-status-console-shell.md),
[task-ui-03-system-events-panel.md](done/task-ui-03-system-events-panel.md),
[task-ui-04-think-and-reset-controls.md](done/task-ui-04-think-and-reset-controls.md),
[task-ui-05-open-hidden-visibility-mode.md](done/task-ui-05-open-hidden-visibility-mode.md),
[task-ui-06-touchstrip-glance-surface.md](done/task-ui-06-touchstrip-glance-surface.md)

## Summary

Verify the first UI visually and manually where hardware/audio/window-system
behavior is involved.

## Scope

- Desktop screenshots at normal and narrow widths.
- Touchstrip layout screenshot or equivalent render.
- State transition walkthrough: idle, warming, listening, thinking, speaking,
  error.
- Manual checks for TTS mute/Hidden behavior and global hotkey interaction.
- Confirm no network-loaded UI assets.

## Stop Condition (evaluated)

If visual QA reveals that the first shell cannot fit the required controls
without redesign, stop and revise the UI task boundaries instead of adding
workarounds.

**Not triggered.** Every control (module chips + reset icons, Think switch,
reset zone, visibility toggle, events panel on desktop; glance/actions pages
on touchstrip) fits at both the normal desktop width, the narrow 360px
breakpoint, and the touchstrip's fixed 900x230, with no overlap and no
cramped/illegible text - verified live via the Preview tools with every
surface fully populated simultaneously (all controls active, Hidden mode on,
Think on, an error state, a full events panel), not just individually per
prior task card.

## Findings

**Real bug found and fixed:** `demo.html`'s inline `<style>` block set
`body{grid-template-areas}` to the wide "main log" two-column layout
unconditionally. Because it is declared in a `<style>` tag *after*
`style.css`'s `<link>`, it won the cascade over `style.css`'s own
`@media (max-width: 720px)` override at every width (same selector
specificity; later in document order wins) - `demo.html` silently never
exercised the responsive stacked layout its own narrow-width checks in
earlier task cards were supposed to be verifying. At 360px, `.main` was
squeezed to ~83px wide instead of stacking full-width under `.logpanel` -
not literal overflow (so the existing `bodyScrollWidth`-based checks never
caught it), just badly cramped. **`index.html` (the actual product surface)
was unaffected** - re-verified independently at 360px during this task and
confirmed correct (both `.main` and `.logpanel` full-width, stacked).
Fixed by wrapping `demo.html`'s override in the same media query, adding
just the extra "demo" controls row on top of whichever layout `style.css`
already picked, rather than replacing it outright. Regression test:
`test_demo_html_respects_style_css_narrow_width_breakpoint`.

**Smaller consistency fix:** `touchstrip.css` had `WARMING`'s `--live` color
hardcoded as the literal hex `#E8853F` instead of a `--amber-warm` custom
property (the same value `style.css` uses, just not referenced by name).
Same rendered color, but a real duplication smell caught by a new
cross-file test (`test_style_css_and_touchstrip_css_agree_on_every_
runtime_state_color`) - fixed by adding the missing `--amber-warm`/`-dim`/
`-tint` tokens to `touchstrip.css`'s `:root` and referencing them, matching
`style.css` exactly.

## Implementation

- `tests/test_ui_qa.py` (new) - the checks that only make sense once every
  surface exists together:
  - A directory-scan network-asset check iterating every file actually
    present in `status_console_ui/` (parametrized), plus a test asserting
    that file list matches the expected set - so a future new file cannot
    silently skip the "no CDN/Google Fonts" rule by never getting its own
    dedicated test.
  - All six `RuntimeState` values have a `--live` color rule on *both*
    `style.css` and `touchstrip.css` (not just the three - warming/error/
    speaking - task-ui-02 originally spot-checked for distinctness).
  - The two files agree on every single state's color value (caught the
    `--amber-warm` duplication bug above).
  - Regression coverage for the `demo.html` responsive-breakpoint bug
    above.
- `status_console_ui/demo.html`, `status_console_ui/touchstrip.css` -
  the two fixes described in Findings.

## Acceptance Criteria

- [x] No text overlap in desktop or touchstrip layouts. Verified live via
      the Preview tools with every control simultaneously populated
      (previous task cards mostly verified their own new control in
      isolation) at desktop width, 360px, and touchstrip's 900x230 -
      the `demo.html` bug above was found by this more thorough pass.
- [x] All state colors and labels match the story semantics. All six
      `RuntimeState` values produce a distinct `--live` color on both
      surfaces (verified live and by `test_ui_qa.py`); `WARMING` remains
      visually distinct from `SPEAKING`/`ERROR`/cloud-adjacent amber per
      task-ui-02/05's color-semantics decisions.
- [x] Hidden mode behavior is confirmed manually if audio/screen output is
      involved. Moot: task-ui-05's recorded human decision is that Hidden
      never touches audio/screen output in v1 (UI-display-only), so there
      is nothing here requiring a hardware handoff. `tasks/task-ui-privacy-
      and-touchstrip-requirements.md` already reflects this.
- [x] System events visibly report warmup, reset and Think transitions.
      Already true from task-ui-03/04 (`WARMUP`/`ENGINE`/`HOTKEY`-sourced
      `SystemEvent`s from `main.py`'s real call sites) - re-confirmed live
      by firing one event of each level in the desktop panel during this
      pass and reading them back correctly ordered/colored.
- [x] Manual handoff commands are documented - see below.

## Manual Handoff

Hardware/display-dependent per CLAUDE.md's testing protocol - run by the
human, not the agent:

1. **Full visual walkthrough, both windows, real WebView2:**
   ```
   python manual_check_status_console.py
   ```
   Confirms the desktop window and the touchstrip window side by side, on
   the real Windows/WebView2 renderer, not just a browser preview. The
   script already cycles every `RuntimeState` and fires a sample
   `SystemEvent` of each level automatically every 2s, and clicking Think/
   reset/Open-Hidden on either window updates both (they share one
   `StatusConsoleApi`). Confirm subjectively: text is legible at both
   window sizes, colors read as intended for each state (including
   `WARMING` not reading as a cloud/network warning), and Hidden replaces
   the desktop's vision-chip detail text without changing either window's
   locality display.
2. **Global hotkey interaction (optional, narrow scope):** with both
   windows open and one of them focused, confirm this project's existing
   global hotkeys still fire from an elevated terminal - e.g. run
   `python manual_check_capture.py` (lighter weight than the full voice
   pipeline: only needs `mss`/`keyboard`, no Ollama/microphone) alongside
   the Status Console windows and press its screenshot hotkey while a
   Status Console window has focus. `main.py` itself is not wired to a
   live Status Console window yet (see task-ui-03's "deliberately not
   done" note), so there is no real shared-process integration to test
   beyond this general "does a WebView2 window block global hotkeys"
   question - and PROJECT.md's existing verified fact already says
   elevated `keyboard`-package hotkeys are global regardless of focused
   window, so this step is confirmatory, not expected to surface anything
   new.

## Test Boundary

`tests/test_ui_qa.py` (14 tests, described above). 262 tests pass
project-wide. Full-population layout checks (every control active at once,
across desktop/narrow/touchstrip) were run live via the Preview tools during
this task, which is what surfaced both real findings above - static
per-file assertions alone had not caught either one.

## Human Review

Passed on 2026-07-07. The human confirmed the real WebView2 windows work and
the UI "looks stylish and beautiful."
