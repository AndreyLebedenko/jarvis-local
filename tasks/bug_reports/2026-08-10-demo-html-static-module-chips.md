# Edge case: demo.html module chips are static markup, not driven by renderModules()

**Commit:** 0da702a (branch task-ui-ux-3-tts-toggle, discovered while verifying
task-ui-ux-3's Status TTS toggle in the browser preview)

## Symptom

In `status_console_ui/demo.html`, none of the module-chip demo controls
visibly update anything. Concretely: clicking the "backend health: degraded"
(or error/ok/unavailable) button, or any future per-module control such as
task-ui-ux-3's new `tts: enable/mute/load failed` buttons, calls
`applyModuleHealth()`/`applyTtsState()` correctly, but the on-screen chip
never changes state or content.

## Suspected cause

`index.html` (the real production shell) renders the module strip
dynamically: `<div class="chip-row" id="modulesPanel"></div>`, populated by
`app.js`'s `renderModules()`, which itself is invoked by `applyModuleHealth()`
and friends. `demo.html` still has the pre-refactor markup: five/six
hardcoded `<div class="chip" id="chip-tts">...</div>` elements with no
`#modulesPanel` container at all. `renderModules()` starts with
`const panel = document.getElementById("modulesPanel"); if (!panel) return;`,
so on demo.html it is a silent no-op every time - the static chips it should
be replacing are never touched.

This is not new in task-ui-ux-3; it reproduces identically for the
pre-existing "backend health" buttons, so the divergence between
`demo.html`'s markup and `index.html`'s dynamic-panel refactor predates this
task. `demo.html`'s config-values/pending-restart/thinking-mode/visibility
demo controls are unaffected - they target their own dedicated elements, not
the module chip strip.

## Temporary decision

Not fixed as part of task-ui-ux-3. Verifying the new TTS toggle/module-health
distinction was instead done directly against `index.html` (calling
`applyTtsState()`/`applyModuleHealth()` from devtools), which uses the real
dynamic rendering path and confirmed the feature works correctly. Fixing
`demo.html` itself means replacing its five static chip divs with the same
`id="modulesPanel"` container `index.html` uses - a small, mechanical,
but unrelated-to-TTS change, better scoped as its own task so it does not
get silently folded into task-ui-ux-3's diff.

## Future considerations

- Replace demo.html's static chip block with `<div class="chip-row"
  id="modulesPanel"></div>`, matching index.html.
- Once fixed, task-ui-ux-3's already-added `tts: enable / mute / load
  failed` demo buttons (demo.js) will start working without further changes.
- Worth a quick audit for any other demo.html elements that may have drifted
  the same way during the index.html chip-row refactor.
