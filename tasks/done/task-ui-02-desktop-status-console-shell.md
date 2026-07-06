# Task UI-02: Desktop Status Console shell

**Story:** story-status-console-ui.md
**Статус:** Completed.
**Приоритет:** высокий
**Зависимости:** [task-ui-01-state-and-event-contract.md](done/task-ui-01-state-and-event-contract.md)

## Summary

Build the first desktop Status Console shell: top-level window, status orb,
module chips and basic layout. This is a status surface, not a settings app.

## Scope

- Main status orb with runtime state label and concise substatus.
- Module chips for model/backend, microphone, TTS, memory and vision/screen.
- Data locality indicator for current supported backend mode.
- Space reserved for Think/reset controls and system events panel.
- Responsive layout that works on ordinary desktop and narrow widths.

## Stop Condition (resolved before implementation)

If choosing the GUI framework has architectural consequences not settled in
PROJECT.md or story docs, stop and ask before implementing the shell.

**Triggered and resolved via human decision:** `pywebview` over a local
HTML/CSS/JS front-end (WebView2 on Windows, future QtWebEngine/PySide6 on
Linux), UI as a thin client over engine state via `pywebview`'s in-process
`evaluate_js` bridge, no networked transport yet. Recorded in
`story-status-console-ui.md`'s Open Questions and `PROJECT.md`'s
Architecture v1.3 section before any code was written.

## Implementation

- `status_console_ui/index.html` + `style.css` + `app.js` - the production
  shell: orb (runtime state label/substatus), five module chips (backend,
  microphone, TTS, memory, vision), a data-locality badge, and disabled
  placeholder elements for the Think toggle, reset button, and system
  events panel (wired for real by task-ui-04/task-ui-03 - this task only
  proves the layout has room for them without overlap).
- `status_console_ui/demo.html` + `demo.js` - a dev-only QA harness (not
  part of the production surface) with buttons for every
  `RuntimeState`/`HealthStatus`/`DataLocality` value, used to visually
  verify every contract state renders correctly in an ordinary browser
  (verified via the Preview tools against `.claude/launch.json`'s
  `status-console-static` static file server) before the pywebview-specific
  parts were even written.
- `status_console.py` - `StatusConsoleWindow`, an injectable-`window_factory`
  wrapper around `webview.create_window()` plus `push_runtime_state()`/
  `push_module_health()`/`push_data_locality()`/`push_model_label()`, each
  translating a `ui_contract.py` value into the JSON `app.js`'s functions
  expect via `evaluate_js`.
- `manual_check_status_console.py` - hardware-dependent handoff: opens the
  real window, pushes the real `config.py` `backend.model` value, cycles
  every `RuntimeState` every 2 s. Not run automatically - see CLAUDE.md's
  testing protocol.
- `requirements.txt` gained `pywebview>=6.2`.

## Acceptance Criteria

- [x] UI can render all contract states from task UI-01. Verified two ways:
      automated (`tests/test_status_console.py`'s `runtime_state_payload`
      coverage of all six `RuntimeState` values) and manual-in-browser via
      `demo.html` (all six states render with distinct color/label/ring
      animation - confirmed live through the Preview tools during
      implementation).
- [x] No hardcoded model name; model/backend label comes from config/runtime.
      `index.html`'s backend chip starts as a placeholder (`...`); the real
      value only ever arrives via `push_model_label()`, which
      `manual_check_status_console.py` feeds from `load_settings().backend.
      model`. Automated: `test_index_html_has_no_hardcoded_model_name`,
      `test_create_passes_index_html_url_and_no_hardcoded_model_name`.
- [x] No Google Fonts or network-loaded assets. System font stack only
      (Segoe UI/Consolas, both ship with Windows 11). Automated:
      `test_index_html_has_no_google_fonts_or_cdn_reference`,
      `test_style_css_has_no_network_loaded_assets`.
- [x] `WARMING` styling is distinct from cloud/network warning. `WARMING`
      uses its own `--amber-warm` shade (distinct from `SPEAKING`'s
      `--amber`) plus a dashed/faster ring animation and an explicit
      "(локально)" qualifier in the label text - v1.0 has no cloud
      indicator yet to clash with, but the distinctness is real and
      automated-tested
      (`test_style_css_gives_warming_a_distinct_color_from_error_and_
      speaking`) rather than left to chance.
- [x] Layout remains readable at narrow widths without overlapping text.
      A `@media (max-width: 720px)` rule switches from the two-column
      grid to a single stacked column. Verified live at 360x700 through
      the Preview tools (no chip/orb-sub/log-panel bounding-box overlaps,
      no horizontal overflow) after adding the missing
      `<meta name="viewport">` tag, without which the browser's default
      980px virtual viewport silently defeated the media query on a
      narrow window. Structural check also automated
      (`test_style_css_has_a_narrow_width_media_query`).

## Test Boundary

Pure logic (`status_console.py`'s payload functions, `StatusConsoleWindow`
against a fake window, and static-file content assertions against
`index.html`/`style.css`) is covered by `tests/test_status_console.py` - 20
tests, no real WebView2/display required. The real window
(`manual_check_status_console.py`) is hardware/environment-dependent per
CLAUDE.md's testing protocol and is a handoff, not an automated test.
