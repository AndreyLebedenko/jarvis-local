# Task instance-branding-1: Brand settings and runtime consumption

Status: Completed. Owner ran the Windows handoff on 2026-11-26: normal paths and rejection cases behaved as specified.

Story: `tasks/story-instance-branding.md`, task 1 (Size: M).

## Summary

Add a `[brand]` section to `config.toml` (keys `name`, `monogram`, `accent`,
`icon`), validate it in `core/config.py`, deliver the resolved brand to the
Status Console and the touchstrip through the existing UI state snapshot, and
make every runtime consumer in this slice use it: the header brand mark and
name, the document titles, the native window titles, the `{brand}` placeholder in
`strings.js`, and the "already running" MessageBox title. Resolve the
`<home>/brand/` asset locations as path logic only. With no `[brand]` section
every visible name and shape stays exactly as today.

## Current state (commit `5a72c01`)

- `core/config.py` is stdlib-only (a test pins it), parses `config.toml` and
  `config.ui.toml` as two layers, rejects unknown sections and keys per file,
  and builds each section through `_SECTIONS` / `_SECTION_BUILDERS`. Home is the
  directory of `config.toml`; at runtime that is the process cwd
  (`DEFAULT_CONFIG_PATH = Path("config.toml")`).
- `config.ui.toml` is machine-owned: `write_ui_config()` rewrites the whole
  file from the Settings form and never writes a `[brand]` section.
- `test_example_config_matches_documented_defaults` requires
  `config.example.toml` to load equal to `Settings()`.
- UI delivery (PROJECT.md, v1.2.10 and v1.2.11): `UiStateStore` in
  `ui/transport.py` holds one JSON state projection. `app.py`
  (`run_with_status_console`) builds it with constructor arguments
  (`language`, `debug`, `run_mode_policy`, ...). Every client gets the whole
  projection as `state/snapshot` on `control/hello`; later changes are
  `state/delta`. `app.js` `_applyStateSnapshot` and `touchstrip.js`
  `_applyStateSnapshot` each fan the snapshot out to `applyXxx` functions;
  `strings.js` `applyUiLanguage` re-stamps all `data-i18n*` elements. Values
  fixed for the whole process (`debug`, `run_mode`) are projected exactly this
  way: set once in the constructor, present in every snapshot, no delta.
- The native window titles are Python literals: `StatusConsoleWindow(title=
  "Jarvis - Status Console")` and `TouchstripWindow` (`"Jarvis - Touchstrip"`),
  created in `app.create_live_status_console()` before the transport exists.
  `index.html` / `touchstrip.html` carry matching `<title>` literals.
- Header: `<div class="brand-mark">J</div>` (24px, 1.5px `--cyan` border,
  6px radius, i.e. a rounded square) and `<div class="brand-name">JARVIS
  <span>Status Console</span></div>`. `--cyan` is `#3FE0D0` in both
  `style.css` and `touchstrip.css`.
- `strings.js`: 12 strings per language contain "Jarvis" (`run_mode_mcp_hint`,
  `confirm_shutdown_text`, `pending_restart_text`, `journal_source_assistant`,
  `journal_external_answer_status_muted`, `journal_search_label`,
  `journal_search_no_results`, `journal_input_placeholder`,
  `journal_input_busy`, `journal_new_context_busy`,
  `journal_memory_self_description`, `journal_fork_busy`). `uiString(key)`
  returns the raw text and call sites substitute other placeholders with
  `String.replace("{x}", value)`.
- `main()` takes the single-instance guard before any settings are loaded. On
  refusal it prints `ALREADY_RUNNING_MESSAGE` and, with `--status-console`,
  calls `show_already_running_message_box(message)`, whose title is the
  constant `_MESSAGE_BOX_TITLE = "Jarvis"`. The launcher passes a stderr print
  instead of a box.

## Design

### Settings and validation (`core/config.py`)

`BrandSettings` (frozen dataclass, in `Settings.brand`, section `brand` in
`_SECTIONS`) holds the validated, final values:

| Field | Default | Rule |
| --- | --- | --- |
| `name` | `"Jarvis"` | string; NFC-normalized and stripped; 1 to 32 code points; no character of Unicode category C* (control, format, surrogate, private use, unassigned) or Z* other than the plain space U+0020. Markup characters and quotes are allowed because the value is only ever rendered as text. |
| `monogram` | first character of `name` | exactly one code point after NFC; Latin letter, Cyrillic letter or ASCII digit; stored upper-cased when the upper-case form is still one character. Explicit empty, longer, or other-script values are rejected. If absent and the first character of `name` is not allowed, the error names `[brand].monogram` and says to set it explicitly. |
| `accent` | `"#3FE0D0"` | `#RRGGBB` only (6 hex digits), stored upper-case. Equals `--cyan` today; a test pins it to `style.css` and `touchstrip.css`. |
| `icon` | `None` | optional string path relative to the home: not empty, not absolute (no drive, no UNC, no leading separator), no `..` segment, ends with `.png` (case-insensitive), no control characters. Existence and PNG content are not checked here (task 2/3: deployment validates the source file; the runtime only consumes the generated `brand/` files, so a deleted source PNG must not stop startup). |

Errors are `ConfigError` messages that name the key, for example
`[brand].monogram must be exactly one Latin or Cyrillic letter or digit, got 'AB'`.
Wrong types use the existing `_matches_type` wording. Unknown keys in `[brand]`
are rejected by the existing per-file check. A `[brand]` section in
`config.ui.toml` is rejected with a message saying the section belongs in
`config.toml`, because the Settings form rewrites that file wholesale and would
silently drop it. `load_brand(path, ui_path=None) -> BrandSettings` reads only
the `[brand]` tables through the same builder (no other section is validated),
so the MessageBox path cannot fail on an unrelated setting.
`config.example.toml` gets a commented `[brand]` example (an active section would
still equal the defaults, but a commented one makes "no `[brand]`" the shipped
state).

### Asset directory resolution (`core/brand.py`, path logic only)

`brand_asset_directory(home) -> home / "brand"` and
`resolve_brand_assets(home) -> BrandAssets(png, ico)`: for each of `brand.png`
and `brand.ico`, the file in `<home>/brand/` when it exists, otherwise the
package default in `jarvis/launcher/assets/` (`jarvis.png`, `jarvis.ico`). Pure
`Path` logic, no image reading, nothing is generated or written. Nothing in task 1
calls it in production (the launcher and generator are task 2); it exists so
task 2 and 3 share one resolution rule, and the tests pin the precedence.
The module stays free of UI imports so the launcher can reuse it.

### Delivery to the UI

Mechanism: the existing state snapshot. A new process-fixed projection key
`brand`, built from `settings.brand`, is passed to `UiStateStore(brand=...)`
exactly like `debug` and `run_mode`, and is part of every snapshot:

```
"brand": {"name": "Work", "monogram": "W", "accent": "#3FE0D0", "is_default": false}
```

`is_default` is `brand == BrandSettings()` (see question 1). No delta is ever
sent (the brand cannot change in a running process; rebranding is edit and
restart), so no transport command or protocol change is needed; `app.js` and
`touchstrip.js` additionally register `brand: applyBrand` in their delta table
for symmetry with `ui_language`. A store built without a brand argument reports
the default brand, so existing tests and the demo harness are unaffected.
`brand_payload(brand)` lives next to `run_mode_payload` in `ui/status_console.py`.

Native window titles are set at window construction, before the transport
exists, so they come from the settings in `create_live_status_console()`:
`status_console_title(name)` and `touchstrip_title(name)` (`"{name} - Status
Console"`, `"{name} - Touchstrip"`) in `ui/status_console.py`;
`TouchstripWindow` gains a `title` parameter with the current default.

### Web layer (`strings.js`, `app.js`, `touchstrip.js`, CSS)

- `strings.js` keeps the brand name (default `"Jarvis"`) and exposes
  `applyBrand(payload)`: stores the name, re-stamps all `data-i18n*` elements,
  sets `document.title` to `"<name> - <suffix>"` where the suffix is declared by
  the page (`data-title-suffix` on `<body>`: `Status Console` /
  `Touchstrip`), and, when present, fills the header: `#brandMark` letter and
  `--brand-accent`, `#brandName`. `uiString(key)` substitutes `{brand}` in one pass with a
  function replacer, so the name is inserted unchanged and cannot expand `$&`,
  `$1` or a later `{x}` placeholder; it never declines the name in Russian. Every
  write is `textContent` / `document.title` / `style.setProperty`, never
  `innerHTML`.
- Order in `_applyStateSnapshot`: `applyBrand` before `applyUiLanguage`
  (both re-stamp, so either order ends consistent).
- The 12 "Jarvis" strings per language become `{brand}` strings (the Russian ones
  keep the surrounding Russian words, the name stays as typed). A test forbids a
  string that combines `{brand}` with another placeholder.
- `index.html`: `<div class="brand-mark" id="brandMark" data-brand="default">J</div>`
  and `<div class="brand-name"><span class="brand-name-text" id="brandName">Jarvis</span>
  <span>Status Console</span></div>`. The suffix span stays classless, so the
  existing `.brand-name span` dim rule (and the demo harness, which has the same
  classless span) is unchanged; `.brand-name .brand-name-text` overrides it for
  the name (inherit colour, weight and size, no margin) and applies
  `text-transform: uppercase`, so the default still reads `JARVIS` while the text
  content stays "Jarvis". Inline text flow is kept; `.brand-name` gets
  `min-width: 0; overflow: hidden; text-overflow: ellipsis` so a 32-character name
  is clipped with an ellipsis instead of breaking the topbar.
- `style.css`: `.brand-mark` reads `--brand-accent` (default `var(--cyan)`) for
  border and letter colour; only this element reads it, so the accent never
  recolours the theme. Shape per question 1.
- `demo.html` / `demo.js` (dev-only English harness) stay unchanged.

### MessageBox title (`core/single_instance.py`, `app.py`)

Feasible without touching the guard. On refusal only, `main()` calls
`load_brand()` (the same layered loader, cwd `config.toml`), falling back to the
default name on any `Exception` (deliberately: the title is cosmetic and no config
failure may change the exit code the launcher checks; tomllib can raise
`RecursionError` or `MemoryError`; tested with `ConfigError`, `UnicodeDecodeError`
and `RecursionError`), and passes the name as the box title.
`show_already_running_message_box(message, title=DEFAULT_TITLE)` gains the title
parameter and `main()`'s `show_message_box` seam becomes `(message, title)`;
the existing tests for the seam are updated. The body text and the stderr line
stay exactly as today ("Jarvis is already running. Only one instance may run at
a time."): the mutex is per user, not per home, so the running instance may
belong to another home with another brand, and a body naming the attempting
brand would be wrong. Mutex name, exit code, acquisition order and release are
untouched.

## Boundary

In: the items above, `config.example.toml`, a short "instance branding" section
in `PROJECT.md` (config contract, snapshot key, `{brand}` rule, title rules;
required now by CLAUDE.md "Project context" 2, extended in task 5), tests, a
UI handoff.

Out (later cards): icon generation and PNG validation and conversion (task 2),
the launcher tooltip and tray and window icons (task 2), `deploy.cmd` flags,
TOML rewrite, shortcut name and filename sanitizing (task 3), the wizard (task
4), README, release handoff (task 5). Also out: any technical identifier
(mutexes, `JarvisLauncher`, package name, `Jarvis.cmd`), the persona, system
prompt and `self.md` content, the single-instance guard logic, the journal,
memory, config layering or path contract, and the demo harness. No Settings-form
editing of the brand.

## Acceptance criteria

- [x] No `[brand]` section: `Settings().brand` equals the defaults
      (`tests/test_config_brand.py::test_without_a_brand_section_the_defaults_are_the_current_identity`),
      every `strings.js` string renders character for character as before (golden
      table of the 24 old strings:
      `tests/test_brand_ui_assets.py::test_with_the_default_name_every_branded_string_reads_as_before`),
      window titles read `Jarvis - Status Console` / `Jarvis - Touchstrip`
      (`tests/test_brand_ui_delivery.py::test_window_titles_of_the_default_brand_are_the_current_titles`,
      `tests/main_split/test_main_brand.py::test_live_console_windows_of_an_unbranded_app_keep_the_current_titles`),
      the header mark is the same rounded-square `J` in `--cyan` and the name reads
      `JARVIS` (markup and CSS pinned in `test_brand_ui_assets.py`; pixel look is the
      human handoff Case A), the MessageBox title is `Jarvis`
      (`tests/test_single_instance.py::test_refused_main_without_a_brand_titles_the_box_jarvis`).
- [x] With `name`, `monogram`, `accent`: the snapshot carries them
      (`test_brand_ui_delivery.py::test_the_snapshot_carries_the_brand_the_store_was_built_with`,
      `test_main_brand.py::test_the_transport_state_is_built_with_the_settings_brand`),
      the header mark, header name, `document.title` and every `{brand}` string in
      English and Russian take the brand unchanged
      (`tests/test_brand_js_behavior.py`, Node), both native window titles
      (`test_main_brand.py::test_live_console_windows_are_titled_from_the_app_brand`).
- [x] The monogram defaults to the first letter and can be overridden; empty,
      multi-character, unsupported-character, over-long, control-character and empty
      names, malformed accent and bad icon paths raise `ConfigError` naming the key
      (`tests/test_config_brand.py`, parametrized).
- [x] Hostile names: rejected naming `[brand].name` when over 32 characters or
      containing control characters (`test_config_brand.py`); markup, quotes, `$&`,
      `{max}` are accepted and kept literally
      (`test_markup_quotes_and_placeholders_are_kept_literally`) and rendered as text
      (`test_brand_js_behavior.py::test_a_hostile_name_is_inserted_literally_everywhere`,
      which fails if the replacer is not a function; `test_brand_ui_assets.py::test_brand_code_never_writes_markup`).
- [x] The accent colours only the brand mark
      (`test_brand_ui_assets.py::test_only_the_brand_mark_reads_the_brand_accent`);
      the default equals `--cyan` in both CSS files
      (`test_the_default_accent_equals_the_cyan_of_both_stylesheets`).
- [x] `[brand]` in `config.ui.toml` is rejected
      (`test_config_brand.py::test_a_brand_section_in_the_ui_layer_is_rejected`); the
      example config still loads equal to `Settings()`
      (`test_config.py::test_example_config_matches_documented_defaults`,
      `test_config_brand.py::test_the_example_config_carries_a_commented_brand_block_that_is_valid`).
- [x] `resolve_brand_assets` prefers `<home>/brand/` files over the package defaults
      per file and never writes (`tests/test_brand_assets.py`).
- [x] A refused second start passes the brand name as the MessageBox title and
      leaves the message text, exit code and mutex name unchanged; a malformed
      config falls back to `Jarvis`; the brand is not read before the guard decides
      (`tests/test_single_instance.py`).
- [x] `python -m pytest` (6579 passed, 1 skipped), `ruff check`, `ruff format
      --check` green. Human visual handoff prepared:
      `manual/instance-branding-1-handoff.md` (not run).

## Implementation plan (TDD order)

1. `tests/test_config_brand.py` then `BrandSettings`, `_build_brand_section`,
   `load_brand`, `[brand]`-in-UI-layer rejection, example comment.
2. `tests/test_brand_assets.py` then `core/brand.py`.
3. `tests/test_status_console.py` / transport tests for `brand_payload`, the
   window title helpers, `UiStateStore(brand=...)` snapshot key and default,
   `create_live_status_console` titles; wire `run_with_status_console` and
   `create_live_status_console`.
4. `strings.js` `{brand}` conversion, golden table test, no-combined-placeholder
   test, `applyBrand`; Node behaviour test (skipped without Node, like the other
   `*_js_behavior` tests); `index.html`, `touchstrip.html`, CSS, `app.js`,
   `touchstrip.js` wiring; extend `test_ui_i18n.py` / `test_ui_qa.py` where they
   enumerate keys or files.
5. `single_instance.py` title parameter, `main()` refusal path, update
   `tests/test_single_instance.py` and the launcher stub signature.
6. `PROJECT.md` section; `manual/instance-branding-1-handoff.md`.
7. `python -m pytest`, `ruff check`, `ruff format --check`; refresh the graph
   with `tools/graphify.ps1 update` is optional and not committed.

## Human handoff (prepared, not run by the agent)

`manual/instance-branding-1-handoff.md`: self-sufficient per the Testing
protocol: it names the config file (`config.toml` in the app home), the exact
`[brand]` blocks to paste (default, `name = "Work"` with `monogram = "W"` and
`accent = "#E0A03F"`, a Russian name, a hostile name), the start command
(`Jarvis.cmd`, source: repository root), what to compare (header mark, header
name, both window titles, a `{brand}` string such as the journal input
placeholder in English and Russian via `[ui].language`, the touchstrip title),
the second-start MessageBox title, and the state-independent way back (delete
the `[brand]` block). It states that README does not yet document `[brand]`
(task 5 debt); the keys are documented in `config.example.toml` and
`PROJECT.md`. The tray icon, launcher window and shortcut are explicitly not
part of this handoff (task 2 and 3).

## Implementation notes (2026-11-26)

- The catalog placeholder is `{brand}`, not `{name}`: `journal_attachment_persist_saved`
  ("Saved as {name}") already uses `{name}` for a file name, replaced at its call
  site, and a global `{name}` substitution would have turned the file name into the
  brand name. `{brand}` avoids touching that unrelated string and its call site
  (a test pins that it still renders the file name). The story's wording
  "`{name}` placeholder" is therefore realised as `{brand}`.
- Existing tests adjusted for the new behaviour: `tests/conftest.py` and
  `tests/test_single_instance.py` (message box seam takes `(message, title)`),
  `tests/main_split/test_main_mcp_mode.py` and `test_main_personal_proxy.py`
  (the fake `StatusConsoleWindow` factory accepts `title`),
  `tests/test_journal_view_ui.py` (the markup fallback text is the catalog text
  with the default brand name substituted). `src/jarvis/launcher/runtime.py`: its
  message box stub takes the new `title` argument.
- `_read_toml_file` (`core/config.py`) now converts `UnicodeDecodeError` into a
  `ConfigError` naming the file ("... is not valid UTF-8"). This changes
  `load_settings()` for every non-UTF-8 `config.toml` or `config.ui.toml`: it used
  to end in a raw `UnicodeDecodeError`, it now ends in a `ConfigError`
  (`tests/test_config_brand.py`: the undecodable config and UI-layer tests).
- Header layout keeps inline text flow (no flex on the name) so the default stays
  pixel-identical in intent; long names are clipped with an ellipsis on the
  container. Visual confirmation is the human handoff.

## Resolved questions

1. **Brand mark shape versus "exactly as today": option B.** The mark is a
   rounded square for the default brand and a circle for any non-default brand
   (`is_default` flag in the payload, one CSS rule). Decided by the
   orchestrator; the owner can reverse it at pre-commit review (switching to
   "always a rounded square" means deleting that one CSS rule).

## Decisions taken without a question (reverse any of them if wrong)

- Maximum name length: 32 code points, counted after NFC and strip. The header
  also ellipsizes, and the Windows tray tooltip limit (127 characters) leaves
  room for a state suffix in task 2.
- Name may contain markup characters and quotes (rendered as text); only
  control and other invisible or non-space-separator characters are rejected.
  Windows file-name sanitizing for the shortcut is task 3's job.
- `[brand]` is `config.toml`-only (rejected in `config.ui.toml`).
- Monogram is upper-cased; if the name's first character is not an allowed
  monogram character the user must set `monogram` explicitly (no skipping to
  the first allowed character).
- Missing `icon` file is not an error at config load; only the path shape is.
- `journal_memory_self_description` ("Jarvis persona and self-knowledge") also
  uses `{brand}`: it is UI text about the assistant, not the persona file.
- MessageBox body stays "Jarvis ..." (reason above); only the title is branded.
- `PROJECT.md` gets the contract in this task, not only in task 5.
