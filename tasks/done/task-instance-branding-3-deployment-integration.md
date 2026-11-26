# Task instance-branding-3: Deployment integration

Status: Completed. Owner ran the Windows handoff on 2026-11-26 and reported it
working as specified (card approved by the orchestrator; blocking question 1
resolved as option B, see "Blocking questions").

Story: `tasks/story-instance-branding.md`, task 3 (Size: L in practice: seven
modules touched, two new tools modules, a PowerShell transport, a real-renderer
Windows test and a human handoff; the card first said M-L).

## Summary

Make `deploy.cmd` (and, in task 4, the wizard) able to give a new home its brand,
and make a deployed home leave the deployment with a consistent identity:

1. A brand request (`-Name`, `-Monogram`, `-Accent`, `-Icon <png>`, plus the reset
   switches of question 1) is validated with the task-1 and task-2 rules before
   anything is written, merged with the source's stored `[brand]` in Copy mode,
   and written to the destination `config.toml` with the existing
   preserve-formatting-and-verify-with-`tomllib` mechanism.
2. The user PNG is copied into the destination home (`brand-source/icon.png`) and
   `[brand].icon` records that relative path. Copy mode carries the source `brand/`
   directory and the referenced icon file by value.
3. A new deployment stage generates `brand/brand.png` and `brand.ico` by calling the
   task-2 `regenerate_home_icons` for the destination. It sits after `ready` and
   before the installer, so a failure is retried with `-Resume` without recopying
   anything, and it works before the destination `.venv` exists.
4. The wizard shortcut takes its file name and icon from the destination's resolved
   brand: sanitising and the icon choice are pure Python; the deployment tool prints
   the result and `wizard.ps1` uses it. The wizard UI itself is unchanged.

Without brand flags, and from a source without `[brand]`, every deployment is
byte-for-byte what it is today.

## Current state (commit `b47388f`)

- `deploy.cmd` -> `tools/install/deploy.ps1` (params `-Target -Mode -Resume -Yes
  -Preview -NonInteractive`) -> `python -m tools.deployment` run with the SOURCE's
  `.venv` Python or `Find-Python311`, `PYTHONPATH=<source>\src`, cwd = source. The
  destination `.venv` does not exist yet and is built by the installer later.
- `tools/deployment.py`: `deploy()` runs `plan_deployment` then `_prepare` (manifest
  `preparing`, application files, Copy snapshot, manifest `ready`), then
  `_install_prepared` (installer, then manifest `complete`). `-Resume` accepts only
  `ready`, checks the manifest by exact dict equality, never reads the source. The
  wizard offers its Resume page when the manifest says `ready` after a non-zero exit
  (`Get-DeploymentWizardPhase` in `wizard_worker.ps1`), so any failure that leaves
  `ready` already gets the retry action in the UI.
- Clean mode writes no `config.toml`: the installer's `create_config` copies
  `config.example.toml` later, and skips if the file exists. Clean never reads the
  source config (a test pins that a broken source `config.toml` is ignored).
- `tools/deployment_toml.py` has one operation, `patch_paths`: line-based replacement
  of single-line quoted string values under an explicit `[table]` header, each edit
  verified by `tomllib` equality with the expected document. `deployment_snapshot.py`
  uses it on both layers; `config.ui.toml` holding `[brand]` already stops Copy because
  `load_settings` of the source raises ("belongs in config.toml").
- `core/brand_render.py` (task 2): `regenerate_home_icons(home, renderer=...)` reads
  `<home>/config.toml` via `load_brand`, answers "Default identity: nothing to
  generate" for a default brand and for a missing `config.toml`, validates the PNG
  (`validate_icon_png(home, relative)`, containment inside `home`), renders through
  Windows PowerShell 5.1 and publishes atomically. It needs only the standard library,
  `jarvis.core` and `powershell.exe`; `RENDER_SCRIPT` is found relative to the imported
  module (`Path(__file__).parents[3] / tools / generate_brand_icons.ps1`). It also
  returns success for a `home` that does not exist (the CLI prints "nothing to
  generate"), so deployment must check the directory itself.
- `APPLICATION_FILES` carries the two icon scripts (task 2). `brand/` is not in the
  inventory (nothing outside the explicit list and `src/jarvis` is copied), so a Clean
  deployment from a branded source already inherits nothing: a test must pin it.
- `core/config.py`: `BrandSettings`, `_build_brand_section` (private), `load_brand`.
  There is no public way to validate a brand dict that is not a file.
- `wizard.ps1` shortcut action (about lines 213-228): `Jarvis - <leaf of destination>.lnk`,
  `IconLocation = <dest>\src\jarvis\launcher\assets\jarvis.ico,0`, target
  `<dest>\Jarvis.cmd`.
- `tools/create_launcher_shortcut.ps1`: `Jarvis Launcher.lnk`, `.venv\Scripts\pythonw.exe
  -m jarvis.launcher`, packaged icon.
- `tests/test_clean_deployment.py::test_cli_loads_source_code_and_reaches_installer_in_final_directory`
  builds a fake source home from a hard-coded list of repository files (the deploy
  scripts, `tools/deployment*.py`, a few `src/jarvis/core` modules). New modules the
  deploy tool imports must be added to that list.
- Measured on this machine (Windows PowerShell 5.1, OEM and ANSI code pages 65001):
  a name passed `deploy.ps1 -Name` -> `& $python @arguments` keeps Cyrillic, `&`, `%`,
  `^`, `!`, `'` and a trailing backslash, but silently DROPS embedded double quotes
  (`Say "hi"` arrives as `Say hi`, `back\"q` as `back"q`). The brand name may legally
  contain quotes (task 1), so a command-line transport would corrupt a valid name
  without any error. Code pages other than UTF-8 were not measured.

## Design

### A. Request, validation, merge (pure logic, `tools/deployment_brand.py`)

`BrandRequest(name, monogram, accent, icon, no_icon, default_brand)`: every field
optional; "no flags" is `None`/an empty request. Parsed from JSON (see D); exactly the
task-1 types (strings), unknown keys rejected, `default_brand` combined with any other
field and `icon` combined with `no_icon` rejected with a message naming both flags.

`plan_brand(source, mode, request) -> BrandPlan` is read-only and runs before
`_prepare` creates the destination (so "before anything is written" holds). It does not
live in `deployment_plan.py` because `deployment_toml` already imports that module
(circular otherwise). Steps:

1. Stored table: Clean -> empty (Clean never reads the source config). Copy -> the
   source `config.toml` `[brand]` table exactly as stored (`{}` when absent or no file).
2. Overlay the request: given keys replace stored keys; `-Icon` sets
   `icon = "brand-source/icon.png"`; `-NoIcon` removes `icon`; `-DefaultBrand` empties
   the table. A key the request does not mention keeps its stored line untouched (so a
   source with no `monogram` still derives it from the new name).
3. Validate the merged table with the public `brand_from_table` (new thin wrapper over
   `_build_brand_section`; messages are the task-1 ones naming `[brand].name`,
   `[brand].monogram`, ...). An unsupported first letter with no monogram gives the
   existing "set the monogram explicitly" message.
4. Validate icons before any write: the external `-Icon` file with the task-2 rules
   (new `validate_icon_file(path)` in `core/brand_icon.py`, shared body with
   `validate_icon_png`, no containment check because the file may be anywhere; message
   prefix `[brand].icon "<path as given>": ...`, same wording for every row of table D of
   the task-2 card); an inherited `icon` (Copy) with `validate_icon_png(source, icon)`
   only when a regeneration will happen (flags given); a faithful Copy keeps the old
   tolerance (a missing referenced file is not an error, as for the Personal Proxy files).
5. Result `BrandPlan`: final `BrandSettings`, the key/value changes to write or the
   reset, the external icon to copy, the inherited files to carry, the flag
   `carry_generated_assets` (true only for a Copy with no request), and the preview
   dict `{name, monogram, accent, icon, is_default, origin}` with `origin` one of
   `default`, `inherited`, `requested`.

The `brand` section is only ever written to `config.toml`. `config.ui.toml` holding
`[brand]` stays rejected by the existing source load; a test pins that the writer
never touches the ui layer and that a destination ui layer with `[brand]` stops the
deployment with the existing message.

### B. Writing the destination `[brand]` (`tools/deployment_toml.py`)

Three new generic operations next to `patch_paths` (the third, `remove_table_strings`,
deletes single keys such as `icon` for `-NoIcon`), same philosophy (line edits on plain
forms, `tomllib` equality as the proof, an error naming the key and file otherwise):

- `set_table_strings(content, table, values, origin)`: absent table -> append
  `[table]` and the assignments at the end (using the file's own line ending, adding a
  final newline when missing); existing plain `[table]` header -> replace the value of
  keys already present in place (reuses `_patch_scalar`) and insert missing keys right
  after the header line. A `brand = {...}` inline table, dotted keys (`brand.name = ...`),
  a quoted header, or a key that has to be edited but whose value is not a single-line
  quoted string (a multi-line value that stays unchanged is kept as it is, and the other
  keys are still edited) give "Cannot rewrite [brand] in <file>. Use a plain [brand]
  table with single-line quoted values." The same rewrite is dry-run in planning on the
  text the destination will be made from (the source `config.toml` in Copy when it exists,
  else the source `config.example.toml`; Clean never reads the source config), so the
  message names the SOURCE file and nothing has been written yet. Path rebasing and the
  brand rewrite touch disjoint lines and give the same text in either order
  (tests/test_deployment_brand.py::test_path_rebasing_and_the_brand_rewrite_give_the_same_text_in_either_order).
- `remove_table(content, table, origin)`: deletes the header and its body up to the next
  header; comments elsewhere survive; same verification.

Values are written as JSON strings (`json.dumps(..., ensure_ascii=False)`), which TOML
reads back identically, including quotes, backslashes and Cyrillic; the verification
step is `tomllib.loads(result) == expected document` where `expected` is the original
document with only `brand` changed. Comments inside the replaced table are kept for
keys that were edited in place and lost only when the table is removed.

Clean mode with a request: the base text is `config.example.toml` (the same bytes the
installer would copy) and `[brand]` is appended; the installer then reports
"already present" and its "Load settings" step re-validates the file. Copy mode: the
destination `config.toml` after the snapshot copy; when the source had no `config.toml`
the base is the copied `config.example.toml`, exactly as the installer would do.

### C. Files and where they go

| Item | Clean, no flags | Clean + flags | Copy, no flags | Copy + flags | Copy + `-DefaultBrand` |
| --- | --- | --- | --- | --- | --- |
| `[brand]` in destination `config.toml` | absent | request keys | source table verbatim | source table with the request keys replaced | removed |
| `brand/` (generated files) | not created | generated by the icon stage | copied by value, even if stale or hand-placed | NOT copied, generated by the icon stage | not copied |
| referenced icon file | - | `brand-source/icon.png` (copy of `-Icon`) | copied by value at its stored relative path | inherited file copied (kept) unless `-Icon` or `-NoIcon` replaces/drops it | not copied |

- **User PNG destination: `brand-source/icon.png`.** It follows the example already in
  `config.example.toml` (`icon = "brand-source/icon.png"`), keeps `brand/` purely
  generated output (safe to delete and regenerate), and `[brand].icon` stays a plain
  home-relative path like every other path in the config. The file is copied after
  validation; the icon stage validates it a second time inside the destination
  (`validate_icon_png(destination, ...)`), so a file changed between the two reads cannot
  reach GDI+.
- **Faithful Copy.** Copy without a request is a snapshot: the config table and the
  `brand/` directory (including a stale one, or a hand-placed `brand.ico` that the
  task-2 verifier accepts) are copied as they are, and the referenced icon file is
  copied by value so the Regenerate button works in the copy. Nothing is regenerated.
  With a request the old generated files are not carried, because they would look
  present and hide the staleness the request just created.
- **Clean from a branded source** inherits nothing (not in the inventory, config never
  read); a test with a branded source with `brand/` and an icon file pins it.
- `brand/` and `brand-source/` are never in `APPLICATION_FILES`; the copy happens only
  in the brand step, using the existing nested-link refusal (`_tree_entries`) for the
  directory and a plain file copy for single files.

### D. Transport from PowerShell to Python

`deploy.ps1` gets `-Name`, `-Monogram`, `-Accent`, `-Icon`, `-NoIcon`, `-DefaultBrand`.
It resolves `-Icon` against the caller's location (like `-Target`; Python runs in the
source directory) and passes only the bound parameters as ONE JSON object in the
environment variable `JARVIS_DEPLOY_BRAND` (set and restored in the existing `finally`).
`tools.deployment.main` reads it. No new command-line flags on the Python side.
Reason: the measured loss of embedded quotes in PowerShell 5.1 native arguments; an
environment block is Unicode and carries any valid name unchanged; escaping logic in
PowerShell would be untestable on non-Windows runs and easy to get subtly wrong. The
existing `JARVIS_DEPLOY_NONINTERACTIVE` is the precedent. The wizard (task 4) already
passes its inputs to `wizard_job.ps1` through `JARVIS_WIZARD_*` environment variables,
so it will feed `deploy.ps1` parameters the same way.

Through `deploy.cmd` the cmd.exe layer is in front of PowerShell; a name with `"` must be
written `\"` there (documented in the handoff, README is task 5). The wizard path has no
cmd.exe.

### E. State machine and the icon stage (decision)

Options considered for where generation sits:

- **A. Inside `_prepare`, before the manifest says `ready`.** A failure leaves
  `preparing`, whose only recovery is "remove the directory and start again", which for
  Copy means recopying the whole snapshot because of a one-second PowerShell failure.
  Rejected.
- **B. After `ready`, before the installer (recommended).** A failure leaves `ready`,
  `-Resume` regenerates and then runs the installer, nothing is recopied and the source
  is not read; the wizard already shows the retry page for `ready`; the check is fast and
  fails before the multi-minute pip install.
- **C. After the installer, before `complete`.** Same retry property, but the owner waits
  through the whole installation to learn that an icon is bad, and a Clean `config.toml`
  would exist only if the tool wrote it anyway.

B it is. `_install_prepared` becomes: icon stage, then installer, then `complete`. The
manifest schema is NOT changed (`_require_resumable` compares the whole payload and the
wizard reads `schema`/`phase`), so the stage must be decidable from the disk state:

> The icon stage runs when the destination brand is not the default brand and
> `brand/brand.png` or `brand/brand.ico` is missing. It generates both files.

Consequences: a flagged deployment never carries source icons, so the files are missing
and are generated; a faithful Copy of a source whose `brand/` exists skips the stage
(stale or hand-placed files stay, by design); a faithful Copy of a source whose `brand/`
was never generated gets icons generated (a non-default brand never ships without icons);
a Resume after a failed generation retries it; a Resume after a later installer failure
skips it (files exist). The stage prints the generator's message
(`Generated brand icons in <home>\brand`) on success and nothing when it was not needed; on failure
`[failed] Generate brand icons: <message>` plus `Use -Resume after addressing the error.`,
exit code 1, manifest stays `ready`, installer not run. The message is the task-2 error
text (names `[brand].icon` or the file).

Guards: the stage first checks that the destination home is an existing directory (a
DeploymentError otherwise) because `regenerate_home_icons` answers success for a missing
home; and it never runs for the default brand, which would also answer "nothing to
generate".

`deploy(..., brand: BrandRequest | None = None, renderer=run_powershell_renderer)`: the
renderer is the same seam the task-2 orchestration uses, so the tests drive the whole
state machine with the fake installer and a fake renderer on every platform.
`-Resume` together with brand parameters is rejected ("The brand was prepared with the
files and cannot be changed while resuming. Start a new deployment to change it."):
silently ignoring the flags would let the
owner believe an override applied. The wizard's own Resume request will simply not send
brand values (task 4).

### F. Which Python and PowerShell generate icons without a destination `.venv`

The icon stage runs inside the deployment process itself: the source `.venv` Python or
`Find-Python311`, with `PYTHONPATH=<source>\src`, so `jarvis.core.brand_render` is
imported from the source package. It starts only `%SystemRoot%\System32\WindowsPowerShell\
v1.0\powershell.exe` (PowerShell 5.1, System.Drawing) and runs the SOURCE's
`tools\generate_brand_icons.ps1` (the same file the destination received through the
inventory). Nothing of the destination `.venv`, of its Python or of its installed package
is needed, and the installer's `PYTHONPATH` clearing is irrelevant because the stage runs
before the installer. A deployed home used later as a source works the same way (its own
scripts and package are the source). Tests: fake renderer (any platform); one Windows-only
test runs the real renderer with the fake installer into a temporary destination that has
no `.venv`.

### G. Shortcut name and icon (`tools/deployment_shortcut.py`)

- Name: `<brand name> - <destination folder name>.lnk`. For the default brand this is
  exactly today's `Jarvis - <folder>.lnk`. The pure function `shortcut_file_name` removes
  what a Windows file name cannot hold: `< > : " / \ | ? *` and control characters become
  `_`; trailing dots and spaces and leading spaces are removed; a stem whose part before
  the first dot is a reserved device name (CON, PRN, AUX, NUL, COM0-9, LPT0-9 with the
  superscript digits, CONIN$, CONOUT$) gets a trailing `_`; the stem is cut to 120
  UTF-16 code units without splitting a surrogate pair, after which trailing dots and
  spaces are removed again; an empty result becomes `Jarvis`. The dialog's own
  validation stays as the last line of defence.
- Icon: `shortcut_icon(home)` uses the launcher's `load_launcher_identity` (one rule for
  tray and shortcut: a default brand ignores a stale `brand/`, an unusable `brand.ico`
  falls back); when the result is the packaged icon of the running package it is mapped to
  the destination's own `<home>\src\jarvis\launcher\assets\jarvis.ico` (today's value), so
  the shortcut never points into the source.
- Delivery: after a successful deployment, `deploy()` prints one line
  `JARVIS_DEPLOY_RESULT:{"target": ..., "shortcut_file": ..., "shortcut_icon": ...}`
  (same pattern as `JARVIS_DEPLOY_PREVIEW:`). `wizard_worker.ps1` gets a small parser
  function (tested through PowerShell like its neighbours); `wizard.ps1` stores the last
  result and its shortcut action uses `shortcut_file` and `shortcut_icon`, falling back to
  today's literals when no result line arrived. No page, control or XAML changes.
  The line is printed by Resume runs too, so the Finish page after a retry has it.

### H. Preview

`--preview` validates the request exactly like a deployment (same `plan_brand`, nothing
written) and adds `"brand"` to the JSON (`name`, `monogram`, `accent`, `icon`,
`is_default`, `origin`) for the task-4 review screen. The wizard does not read it yet.
The Resume preview is unchanged.

### I. The tray launcher's desktop shortcut (`create_launcher_shortcut.ps1`): out of scope

It stays `Jarvis Launcher.lnk` with the packaged icon. Reason: the launcher is one
per-user supervisor (own mutex, one `%LOCALAPPDATA%\JarvisLauncher` preferences file) and
its identity follows whichever home is selected in its Settings at run time (task 2), so
a shortcut named after the home that created it would mislead as soon as another home is
selected. Naming it per home would also need a per-home file name and a rule for the
existing "unrelated shortcut" collision check, which is a product decision, not
deployment integration. Revisit only if the owner wants one launcher shortcut per home.

### J. Inventory

- `APPLICATION_FILES` gains `tools/deployment_brand.py` and `tools/deployment_shortcut.py`
  (a deployed home must be able to deploy). A test pins that every `tools/deployment*.py`
  of the repository is in the inventory.
- `brand/` and `brand-source/` are copied only by the brand step, never by the file
  inventory. Updating `APPLICATION_FILES` also means the fake-home file list in
  `test_clean_deployment.py` gets the new tools modules and the `jarvis.core` and
  `jarvis.launcher` modules they import.

## Boundary

In: `core/config.py` (one public wrapper `brand_from_table`); `core/brand_icon.py`
(`validate_icon_file`, shared body); `tools/deployment_toml.py`; new
`tools/deployment_brand.py` and `tools/deployment_shortcut.py`; `tools/deployment.py`;
`tools/deployment_plan.py` (inventory entries only); `tools/install/deploy.ps1`;
`tools/install/wizard_worker.ps1` and `wizard.ps1` (result line and shortcut action only);
`PROJECT.md` (deployment and branding sections, same change); tests; the human handoff
`manual/instance-branding-3-handoff.md`.

Out: the wizard Identity screen and live preview, passing brand values from the wizard
(task 4); README, `README.ru.md`, release handoff (task 5); the tray launcher shortcut
(I); any technical identifier; the single-instance guard; `wizard_job.ps1` and the
worker's start function; regeneration policy of the running launcher; a Status Console
brand editor; changes to the manifest schema, CI or `requirements.txt`; per-key reset of
`name`, `accent` or `monogram` (see question 1).

## Acceptance criteria

- [x] `deploy.cmd -Target <dir> -Mode clean|copy` without brand flags behaves exactly as
  before (same files, same `config.toml` presence, no `brand/`, no `brand-source/`), from a
  default and from a branded source in Clean mode. Proof: tests/test_brand_deployment.py::test_clean_without_flags_is_unchanged_by_the_brand_work, ::test_clean_from_a_branded_source_inherits_nothing, ::test_a_default_brand_never_reaches_the_renderer_in_any_mode; the pre-existing tests/test_clean_deployment.py and tests/test_copy_deployment.py pass unchanged in behaviour (only the CLI helper moved to tests/deploy_cli_support.py).
- [x] Clean + flags: destination `config.toml` is `config.example.toml` plus a `[brand]` table holding exactly the requested keys; icons are generated; the installer sees both. Proof: tests/test_brand_deployment.py::test_clean_with_flags_is_the_example_plus_the_brand_with_icons_before_install, ::test_clean_with_a_user_png_copies_it_and_renders_that_image; tests/test_deployment_brand.py::test_clean_with_flags_is_the_example_plus_the_brand_table; tests/test_brand_deploy_cli.py::test_flags_produce_a_branded_home_with_real_icons_and_no_venv.
- [x] Copy without flags inherits `[brand]`, the referenced icon file and the `brand/` directory by value (hashes equal), including a stale `brand/` and a hand-placed `brand.ico`; nothing is regenerated unless `brand/` lacks a file. Proof: tests/test_brand_deployment.py::test_a_faithful_copy_keeps_a_stale_brand_directory_and_never_regenerates, ::test_a_faithful_copy_of_a_brand_that_was_never_generated_gets_its_icons; tests/test_deployment_brand.py::test_a_faithful_copy_keeps_the_config_bytes_and_carries_files_by_value, ::test_existing_icons_are_kept_even_when_stale, ::test_a_home_missing_either_file_is_completed; tests/test_brand_deploy_cli.py::test_a_copy_inherits_overrides_and_resets_through_the_command. (Equal "by value" is compared by bytes, not by a hash call.)
- [x] Copy + flags replaces only the given keys (comments and layout of the rest preserved), does not carry the source `brand/`, and regenerates; `-Icon` replaces an inherited icon; `-NoIcon` drops it; `-DefaultBrand` removes `[brand]`, `brand/` and the icon file. Proof: tests/test_brand_deployment.py::test_a_copy_override_regenerates_and_does_not_carry_the_source_icons, ::test_a_copy_can_be_reset_to_the_default_brand, ::test_the_source_is_never_modified_by_a_branded_copy; tests/test_deployment_brand.py::test_an_override_changes_only_its_keys_and_keeps_comments_and_other_tables, ::test_no_icon_removes_the_key_and_the_file_is_not_carried, ::test_default_brand_removes_the_table_and_everything_it_referenced, ::test_a_new_icon_replaces_the_inherited_one.
- [x] Invalid values (empty or over-long name, bad monogram, bad accent, unsupported first letter, missing/non-PNG/tiny/huge/sliver/truncated `-Icon`, conflicting flags) fail with the task-1 and task-2 messages naming `[brand].<key>` before the destination directory exists, in a deployment and in `--preview`. Proof: tests/test_deployment_brand.py::test_invalid_values_name_the_brand_key, ::test_an_unusable_user_icon_is_refused_before_anything_is_planned (six PNG defects), ::test_a_missing_user_icon_is_refused, ::test_a_malformed_or_conflicting_request_is_refused; tests/test_brand_deployment.py::test_an_invalid_request_fails_before_the_destination_exists, ::test_an_unusable_user_png_fails_before_the_destination_exists, ::test_an_invalid_copy_override_fails_before_the_destination_exists, ::test_the_preview_validates_and_describes_the_brand_without_writing, ::test_main_reports_a_bad_brand_as_an_error_line_and_exit_code_one; tests/test_brand_deploy_cli.py::test_an_invalid_value_fails_with_the_key_and_creates_no_destination, ::test_an_unusable_png_fails_before_the_destination_exists. The agent also ran the nine rejection commands of the handoff Case 1 against the real `deploy.cmd` (scratch paths).
- [x] A hostile name (quotes, backslashes, markup, `%`, `&`, Cyrillic, 32 characters) reaches the destination `config.toml` unchanged and `load_brand` of the destination returns it. Proof: tests/test_deployment_toml_brand.py::test_hostile_values_round_trip_through_toml; tests/test_deployment_brand.py::test_a_hostile_name_reaches_the_destination_unchanged; tests/test_brand_deploy_cli.py::test_a_hostile_name_arrives_in_the_config_unchanged (through the real `deploy.cmd` and PowerShell 5.1: `Say "hi"`, `50% off`, `R & D`, Cyrillic, `it's ^ ok`, a trailing backslash).
- [x] `[brand]` is written only to `config.toml`; `config.ui.toml` is never touched and a `[brand]` in a ui layer stops the deployment. Proof: tests/test_deployment_brand.py::test_a_brand_in_the_destination_ui_layer_stops_the_deployment, ::test_a_brand_in_the_source_ui_layer_is_not_something_a_copy_can_start_from.
- [x] An unsupported `[brand]` form (inline table, dotted keys) in the source config is refused in planning, by `--preview` and by the deployment, naming `[brand]` and the SOURCE file, with the destination directory never created (also with `-DefaultBrand`); a faithful Copy of such a source still works; the same refusal exists as a second line of defence when writing the destination. An inherited icon that is a generated brand file (`brand/brand.png`) is refused when a regeneration will replace it; `icon = "config.toml"` cannot exist (task 1 requires a `.png` name). Proof: tests/test_brand_deployment.py::test_an_unsupported_source_brand_form_is_refused_before_the_destination_exists, ::test_a_faithful_copy_of_an_unsupported_brand_form_still_works; tests/test_deployment_brand.py::test_an_unsupported_source_form_is_refused_naming_the_source_file, ::test_a_faithful_copy_of_an_unsupported_form_is_still_planned, ::test_clean_never_reads_the_source_config_for_the_dry_run, ::test_an_unsupported_brand_form_in_the_example_is_refused_for_clean, ::test_path_rebasing_and_the_brand_rewrite_give_the_same_text_in_either_order, ::test_an_icon_cannot_be_named_like_a_managed_file, ::test_an_icon_that_is_a_generated_brand_file_is_refused_when_regenerating. Destination-side proof, as before: tests/test_deployment_toml_brand.py::test_unsupported_forms_are_refused_naming_the_table_and_file, ::test_removing_an_unsupported_form_is_refused; tests/test_deployment_brand.py::test_an_unsupported_destination_form_is_refused_and_nothing_is_written.
- [x] Icon generation failure: exit code 1, output `[failed] Generate brand icons: ...` and the `-Resume` hint, manifest `ready`, installer not run; `-Resume` (source changed or absent) regenerates, runs the installer, reaches `complete`, and recopies nothing (Clean and Copy; in Copy the source is deleted before the resume and the copied journal stays intact). Proof: tests/test_brand_deployment.py::test_a_failed_icon_stage_is_resumable_without_recopying_or_the_source[clean, copy], ::test_a_rejected_png_in_the_destination_is_reported_at_the_stage_and_retried, ::test_a_resume_after_an_installer_failure_does_not_generate_again.
- [x] A nonexistent destination home never reaches the generator; a default brand never calls it. Proof: tests/test_deployment_brand.py::test_a_missing_home_is_refused_before_the_generator_is_called, ::test_a_default_brand_never_reaches_the_generator; tests/test_brand_deployment.py::test_the_stage_stops_for_a_destination_home_that_does_not_exist, ::test_a_default_brand_never_reaches_the_renderer_in_any_mode.
- [x] `-Resume` with brand parameters is rejected with an explanatory message. Proof: tests/test_brand_deployment.py::test_resume_refuses_brand_options_and_leaves_the_destination_alone, ::test_the_resume_preview_refuses_brand_options; tests/test_brand_deploy_cli.py::test_resume_refuses_brand_parameters.
- [x] Icon generation works with no destination `.venv` (real renderer test on Windows). Proof: tests/test_brand_deploy_cli.py::test_flags_produce_a_branded_home_with_real_icons_and_no_venv (real `deploy.cmd`, real Windows PowerShell renderer, fake bootstrap that creates no `.venv`; asserts a 512x512 RGBA `brand.png` and a standard nine-frame `brand.ico`, skipped off Windows).
- [x] The shortcut name is sanitised (invalid characters, reserved names, trailing dots/spaces, length, empty), the default brand gives exactly today's name, and the icon is the destination's `brand.ico` for a branded home and the destination's packaged icon otherwise. Proof: tests/test_deployment_shortcut.py (every rule; ::test_the_default_brand_gives_exactly_the_name_the_wizard_always_used, ::test_a_branded_home_uses_its_generated_icon_and_name, ::test_a_default_brand_ignores_stale_generated_icons, ::test_a_branded_home_without_a_usable_icon_falls_back_to_its_packaged_one); tests/test_brand_deployment.py::test_clean_without_flags_is_unchanged_by_the_brand_work (the result line). Shortcut appearance is human-run (handoff Cases 6, 8, 9).
- [x] `JARVIS_DEPLOY_RESULT` is printed after success and after a resumed success, parsed by the wizard worker helper; the wizard shortcut action uses it. Proof: tests/test_brand_deployment.py::test_a_failed_icon_stage_is_resumable_without_recopying_or_the_source (result line after the resume) and ::test_clean_with_flags_is_the_example_plus_the_brand_with_icons_before_install; tests/test_deployment_wizard.py::test_wizard_worker_reads_the_deployment_result_line (PowerShell parser); the `wizard.ps1` shortcut action itself is UI code, parse-checked and human-run (handoff Cases 6, 8, 9).
- [x] The new tools modules are in the deployment inventory and a deployed home can deploy. Proof: tests/test_deployment_plan.py::test_every_deployment_tool_module_is_in_the_inventory; tests/test_brand_deploy_cli.py runs the scripts and modules of a fake source that holds only the repository files named in tests/deploy_cli_support.py (a Windows run of the deploy tool from a copied tree), and the agent ran a Copy deploy from a deployed scratch home with the fake installer.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` green; the human handoff is prepared, not run. Proof: see "Verification" below; the handoff is manual/instance-branding-3-handoff.md (not run).

## Implementation plan (TDD order)

1. `tests/test_deployment_toml_brand.py`, then `set_table_strings` and `remove_table`: append to
   LF/CRLF files with and without a final newline; in-place value replacement keeping comments;
   key insertion after the header; table removal; unsupported forms; hostile values round trip.
2. `core/config.py` `brand_from_table` and `core/brand_icon.py` `validate_icon_file`, with tests
   next to the existing ones (every task-2 message row for a file outside any home; a link
   to a file elsewhere is accepted; messages quote the given path).
3. `tests/test_deployment_brand.py`, then `tools/deployment_brand.py` request parsing, merge
   table (Clean/Copy x flags x stored keys), validation messages, the plan's no-write guarantee,
   the preview dict, `carry_generated_assets`.
4. `tests/test_deployment_shortcut.py`, then `tools/deployment_shortcut.py`: every sanitising rule,
   default-brand name equals today's, icon selection with a branded/stale/corrupt `brand/`.
5. `tests/test_brand_deployment.py` (fake installer, fake renderer, every platform): Clean and Copy
   flows of section C, resume and failure semantics of E, the missing-home guard, the
   ensure-rule table, ui-layer `[brand]`, clean-from-branded-source, `JARVIS_DEPLOY_RESULT`.
   Then `deployment.py` / `deployment_brand.py` wiring.
6. `deploy.ps1` parameters and the JSON environment variable; extend the CLI test (fake bootstrap,
   file list) with a name containing quotes and Cyrillic; a Windows test for the worker result
   parser; `wizard.ps1` shortcut action.
7. Windows-only test: real renderer, fake installer, temporary destination without `.venv`.
8. Inventory entries and their pin test; `PROJECT.md`; handoff; `python -m pytest`,
   `ruff check`, `ruff format --check`.

Automated, pure logic on every platform: A, B, C, E, G, the transport parsing. Windows only
(skipped elsewhere, run on `windows-latest` CI): the `deploy.cmd` round trip with a hostile name,
the PowerShell result parser, the real renderer. Human-run: how the shortcut looks, the wizard
shortcut dialog, a real installer run.

## Human handoff outline

`manual/instance-branding-3-handoff.md`, self-sufficient per CLAUDE.md Testing protocol 4:
literal commands, source references for every default, explicit starting state, a temporary
parent folder for destinations, `deploy.cmd` `-Yes` (a real installer run needs network and
Python 3.11: say so, and that the first case takes minutes), state-independent cleanup, and the
README debt (flags are not in the README until story task 5). Cases:

1. `deploy.cmd -Target <tmp>\Work -Mode clean -Name "Work" -Monogram W -Accent "#E0A03F"`: both
   `brand\` files exist, `config.toml` holds only the requested keys, `.jarvis-deployment.json`
   `complete`; look at `brand\brand.ico` and the generated `brand.png`.
2. Same with `-Icon <a test PNG>`: `brand-source\icon.png` exists, `[brand].icon` is relative.
3. Invalid inputs (tiny/non-PNG PNG, `-Monogram AB`, `-Name` of 33 characters): exact messages, the
   destination does not exist afterwards.
4. Copy from the case 1 home (the deployed home is the source; run its own `deploy.cmd`):
   inherited brand and files; then Copy with `-Name Home`, `-DefaultBrand`, `-NoIcon` variants.
5. Hostile name with quotes and Cyrillic through `deploy.cmd` (how to quote `"`).
6. Failure and Resume: needs a state-independent way to make generation fail on a real run
   without touching system files (candidate: a destination left in `ready` whose
   `brand-source\icon.png` is replaced by a text file before `-Resume`; the stage then reports the
   `[brand].icon ... is not a PNG file` message and keeps `ready`; restoring a valid PNG and
   `-Resume` completes). The exact recipe is finalised with the implementation; if no safe
   recipe exists the case is dropped from the handoff because the automated state-machine tests
   already cover it.
7. Wizard shortcut: run `DeploymentWizard.cmd` from the case 1 home, Copy mode, finish, `Create
   shortcut`: file name `Work - <folder>.lnk`, Explorer shows the amber `W` icon (small and large),
   it launches the copy; repeat from a default-brand home: `Jarvis - <folder>.lnk`, packaged icon.
   A brand name with `:`/`?` in the file name dialog; a reserved name such as `CON`.

## Blocking questions

1. **RESOLVED (orchestrator decision, 2026-11-26; the owner can reverse it at the pre-commit
   review): option B.** `-DefaultBrand` and `-NoIcon`; no per-key clearing; setting the default
   value explicitly neutralises one key. Original question, kept for the record:
   **How does the owner clear a brand in Copy mode (CLI contract the wizard will reuse)?** A
   Copy inherits the source's `[brand]`; the flags can only set a value. Options:
   - A. `-DefaultBrand` only (whole table, `brand/` and icon file dropped). Cannot say "keep my
     name but drop the PNG".
   - B (recommended). A plus `-NoIcon` (remove only `icon`). Covers the realistic override cases
     (new name/monogram/accent over an inherited PNG, or leave the PNG for a monogram) with two
     switches that are safe through cmd.exe and PowerShell 5.1.
   - C. An empty value clears the key (`-Icon ''`, `-Monogram ''` derives it again, `-Name ''`
     falls back to `Jarvis`). Uniform, but empty arguments are fragile through `deploy.cmd`
     (cmd quoting) and the wizard would need a "set vs empty" distinction for every field.
   Not decided by the story. I need the answer before implementing because it fixes the
   transport JSON, the flags and the wizard contract of task 4. Clearing `name`, `accent` or
   `monogram` individually is not offered under A and B (set them to the default values
   explicitly; the launcher treats a brand equal to the default as the default).

No other question blocks the work. The two story/contract points below were checked and are
recorded as decisions, not conflicts:

- "Clean mode creates default settings" versus Clean brand flags: Clean + flags is default
  settings plus the requested `[brand]` (the story's design says Clean starts from the default
  brand and applies the wizard's identity). Without flags Clean is unchanged. `PROJECT.md` states it.
- Resume "without reading source files": the icon stage reads only the destination and the
  deployment tool's own scripts, so the contract holds.

## Decisions taken without a question (reverse any of them if wrong)

- Brand values reach Python in `JARVIS_DEPLOY_BRAND` (JSON), not as command-line flags, because
  PowerShell 5.1 silently drops embedded double quotes from native arguments (measured).
- User PNG stored as `brand-source/icon.png` (the convention of `config.example.toml`), validated
  twice (external file before any write, destination copy inside the stage).
- Faithful Copy (no flags) carries the source `brand/` as is, stale or hand-placed, and generates
  only when a file is missing; flagged deployments never carry source icons. Alternative if the
  owner prefers it: always regenerate for a non-default brand (a copy never carries stale icons,
  but a hand-placed `brand.ico` would be overwritten, and the story's "copied by value" would
  no longer be literal).
- Icon stage after `ready`, before the installer; no manifest change; decided from disk state.
- `-Resume` with brand parameters is an error.
- Shortcut file name shape `<brand name> - <folder>.lnk` (default brand = today's name). The
  alternative `<brand name>.lnk` is shorter but collides when a Copy inherits the same name;
  reserved-device-name handling is implemented generically either way.
- Shortcut data travels as `JARVIS_DEPLOY_RESULT:` on stdout; the icon rule is the launcher's
  `load_launcher_identity`, so tray and shortcut cannot disagree.
- Preview carries a `brand` object; the wizard ignores it until task 4.
- `tools/create_launcher_shortcut.ps1` stays unbranded (section I).
- New public helpers in task-1/2 code are the minimum needed: `brand_from_table`,
  `validate_icon_file`; no behaviour of existing functions changes.
- Source `[brand]` inside `config.ui.toml`, an unsupported `[brand]` form in the destination, and a
  missing destination home are errors, never silent skips.
- No new Python dependency; `requirements.txt` and CI unchanged.

## Verification (2026-11-26)

- `python -m pytest` (after review round 1): `6994 passed, 2 skipped, 40 warnings in 161.25s` (the skips: one older, and `tests/test_brand_icon_png.py::test_an_outside_file_may_be_reached_through_a_link_to_elsewhere`, which skips where symbolic links are not permitted, as on this machine). Before the review fixes: 6977 passed, 2 skipped.
- `ruff check`: `All checks passed!`
- `ruff format --check`: `665 files already formatted`
- Human handoff prepared, not run: `manual/instance-branding-3-handoff.md`.
- Agent runs outside pytest (fake installer or planning-only, scratch folders, real Windows
  PowerShell renderer, the repository as read-only source): the output sequence and file lists of
  a Clean deployment with flags, of Copy inherit / override / reset / `-NoIcon` from a deployed
  scratch home, the rejection and preview commands of the handoff through the real `deploy.cmd`,
  and the quoting of `Say \"hi\"`, `R & D`, `Work: R&D?`, `50% off` and a Cyrillic name through
  `deploy.cmd` and PowerShell 5.1. No real installer, wizard window, shortcut or tray was run, and
  neither the repository's `config.toml`, `config.ui.toml` or `brand/` nor a running launcher or
  runtime was touched.

## Implementation notes (2026-11-26)

- Changes versus the plan above: (1) `plan_deployment` is unchanged; `deploy()` calls
  `plan_brand` itself (the circular import the card predicted); (2) the card named two TOML
  operations, a third (`remove_table_strings`) was needed for `-NoIcon`; (3) `deployment_snapshot`
  gained two thin public wrappers (`check_directory_tree`, `copy_directory_by_value`) instead
  of making its private helpers public, because an existing test patches `_copy_tree`;
  (4) the icon stage prints only the generator's message, no separate "Generating" line;
  (5) the CLI helpers of `tests/test_clean_deployment.py` moved to `tests/deploy_cli_support.py`
  (it also copies the two icon scripts into the fake source, so the real renderer runs in the CLI
  tests).
- The stage rule "either file missing: generate both" means a faithful Copy of a source whose
  `brand/` holds only one file gets both regenerated (the present one is replaced). Noted, not
  prevented: such a `brand/` is already broken for the launcher.
- Names containing both a double quote and an unquoted `&` cannot go through `deploy.cmd` (cmd.exe
  quote tracking ignores `\"`); the wizard path is not affected. The CLI test uses a space-containing
  `R & D` for that reason.
- Review round 1: `plan_brand` now dry-runs the destination rewrite on the source text, so an
  unsupported `[brand]` form fails in planning naming the source file (it used to fail after the
  snapshot copy, leaving a `preparing` directory). Other late checks were reviewed for the same
  defect: the user PNG, an inherited icon and the brand directory are validated in planning;
  the `config.ui.toml` `[brand]` check is already made when the source settings load; the
  result of the dry run is re-parsed and compared with the planned brand (the same check the
  destination makes afterwards); the shortcut name cannot fail; the env variable carries at
  most four short values (name 32 characters) plus one path; the icon-stage preconditions
  (Windows PowerShell, the renderer script) are deliberately NOT pre-checked: a failure there is
  exactly what the retryable stage is for, and a pre-check would bypass the renderer seam the
  tests use. An inherited icon equal to `brand/brand.png` or `brand/brand.ico` is refused in
  planning when a regeneration will replace it (a `.png` name rules out `config.toml`,
  `config.ui.toml` and the manifest, so `brand/brand.png` was the only managed-file collision).
- Agent tooling lesson: this environment's Bash tool halves backslashes in heredocs; edits with
  backslashes were made with the Edit tool.

## Noticed, left out of scope

- The wizard review page does not show the brand and the wizard sends no brand parameters
  (story task 4); `--preview` already returns the `brand` object it will need.
- README and README.ru do not mention the new options (story task 5); the handoff and
  `PROJECT.md` carry the documentation until then.
- `tasks/story-instance-branding.md` still says tasks 1-2 are complete (the orchestrator updates
  the story card and moves this card on acceptance).
- A faithful Copy carries a stale `brand/` by design (decision above); regenerating it needs the
  launcher button or `python -m jarvis.core.brand_render --home <dir>`.
- `tools/create_launcher_shortcut.ps1` is unbranded on purpose (section I).
