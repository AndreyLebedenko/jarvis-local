# Task instance-branding-2: Icon generation and launcher identity

Status: Completed. Owner ran the Windows handoff on 2026-11-26 and reported it
working as specified. Owner decisions of 2026-11-26 recorded below
(regeneration is a user action: CLI and a launcher Settings button; no
self-healing).

Story: `tasks/done/story-instance-branding.md`, task 2 (Size: M).

## Summary

Turn a validated `[brand]` into the two icon files the story names, and make
the Windows tray launcher use the selected home's identity. Three parts:

1. Pure-logic icon code (`core/brand_icon.py`): user-PNG validation, dimension
   math, ICO verification. Stdlib-only, tested on every platform.
2. A Windows renderer (`tools/generate_brand_icons.ps1`, System.Drawing) that
   draws the monogram or fits the user PNG into `brand.png`, then builds
   `brand.ico` with the existing `tools/build_launcher_icon.ps1`; and a Python
   orchestrator (`core/brand_render.py`) that validates, runs it, verifies the
   outputs and publishes them atomically into `<home>/brand/`. It has a CLI
   (`python -m jarvis.core.brand_render --home <dir>`) that task 3 reuses.
3. The launcher reads the selected home's `[brand]` (`launcher/identity.py`) for
   tray tooltip, tray icon, Tk icons and window titles, refreshes them when the
   home changes, and offers a "Regenerate icons" button in its Settings window.
   A missing, unreadable or invalid brand falls back to the default Jarvis
   identity; the launcher never fails because of branding.

Without `[brand]` nothing changes: the package `jarvis.ico`, the name "Jarvis".

## Current state (commit `8d0a4cf`)

- `core/brand.py` `resolve_brand_assets(home)` returns `<home>/brand/brand.png`
  and `brand.ico` per file when they exist, else `launcher/assets/jarvis.png`
  and `jarvis.ico`. Path logic only; nothing calls it in production.
- `core/config.py` `load_brand(path)` reads only `[brand]` with the full
  validation; `BrandSettings(name, monogram, accent, icon)`; `icon` is only
  path-shape validated (relative, no `..`, `.png`).
- `core/config.py` is stdlib-only (pinned by `tests/test_config.py`), and
  `jarvis/__init__.py` and `jarvis/core/__init__.py` contain only docstrings.
  So the launcher can import `load_brand` without pulling in the engine: it
  already imports `jarvis.core.single_instance` the same way. No new option is
  needed. The launcher imports the module of its own installation and applies it
  to the selected home's `config.toml`; a home whose config the launcher's
  version rejects (for example a newer key) simply gets the default identity.
- `tools/build_launcher_icon.ps1`: PNG -> ICO with PNG frames at 16, 20, 24, 32,
  40, 48, 64, 128, 256 (System.Drawing, HighQualityBicubic, SourceCopy keeps
  alpha). It is not in the deployment inventory (`APPLICATION_FILES` in
  `tools/deployment_plan.py` lists only `tools/create_launcher_shortcut.ps1`
  from the icon tooling), and `PACKAGE_FILE_TYPES` has no `.ps1`, so a script
  placed under `src/` would not be deployed either.
- Launcher hard-codes the identity: `launcher/window.py` `ICON_PATH`, the dialog
  chrome (`window.title("Jarvis")`, label `JARVIS`), `"Jarvis - Settings"`,
  header label; `launcher/__main__.py` (`root.iconbitmap`, tray icon, dialog
  titles); `launcher/tray.py` (tooltips `Jarvis - ...`, `LoadImageW` once in
  `_create`, `WM_REFRESH` only re-sends the tooltip). The home is chosen at
  runtime in Settings (`LauncherController.set_home`, refused while a runtime
  is alive) and stored in `%LOCALAPPDATA%\JarvisLauncher\settings.json`.
- The Status Console mark (task 1) is a circle with a 1.5px accent ring and an
  accent letter for a non-default brand (`.brand-mark[data-brand="custom"]`,
  `border-radius: 50%`), a rounded square for the default.
- CI is `windows-latest` and already runs PowerShell tests
  (`tests/test_deployment_wizard.py`, `skipif(os.name != "nt")`).
- Measured: `powershell.exe` with `Add-Type System.Drawing` and a Cyrillic glyph
  path runs in about 0.3 s warm.

## Design

### A. Who generates the files, and when (owner decision)

Regeneration is always a user action; nothing regenerates by itself.

- **CLI:** `python -m jarvis.core.brand_render --home <dir>`. Task 3 calls the same
  code from `deploy.cmd`.
- **Button:** "Regenerate icons" in the launcher Settings window (the Tk window in
  `launcher/window.py`, in the Jarvis Home Folder block). It is in the launcher,
  not the Status Console Settings view, because `[brand]` is `config.toml`-only.
- A hand edit of `[brand]` is therefore: edit `config.toml`, click the button (or
  run the CLI). **The tray icon stays stale until the button or CLI is used**
  (known and accepted by the owner; the tray tooltip name still follows
  `config.toml` at the next mode start because it is read from the file, not from
  the generated assets). README wording for this is task 5's job.
- **Immediate, not deferred:** the click runs the generator for the saved home at
  once; there is no pending flag file and no "applies at next start".
- **Worker thread:** the generator (a PowerShell process, about 0.3-2 s) runs on a
  worker thread so Tk does not freeze; while it runs the button is disabled and the
  Settings status line reads "Working..."; the result is polled back onto the Tk
  thread with `window.after`, the button is re-enabled, and then the launcher
  identity is reloaded and the tray tooltip and icon and every open window icon
  refresh at once.
- **No runtime-state gating:** writing `<home>/brand/` while a runtime is alive is
  safe, because the runtime (Status Console and engine) never reads `brand.ico` or
  `brand.png`; only the launcher and shortcuts do. Files are replaced atomically
  (`os.replace`), so a concurrent reader sees the old or the new file, never a
  partial one.
- **Idempotent:** with the default brand (no `[brand]`, or one equal to the
  defaults) the button reports "Default identity: nothing to generate" and deletes
  nothing. With a valid brand it regenerates `brand.png` and `brand.ico`
  atomically every time.
- **Errors from an explicit click** are shown in a dialog with the exact messages
  of section D (they name `[brand].<key>` or the file) and are logged in
  `launcher.log`. They never break the launcher and never leave half-written
  files (temp directory, verify, then publish).
- Not in scope: showing the current brand name or an icon preview in Settings.

### B. Pipeline and modules

```
BrandSettings --(core/brand_render.py)--> validate source (core/brand_icon.py)
   -> RenderRequest (all art decisions in Python)
   -> powershell.exe -File tools/generate_brand_icons.ps1 ...   (Windows only)
        -> draws 512x512 brand.png (System.Drawing)
        -> tools/build_launcher_icon.ps1 -Source brand.png -Output brand.ico
   -> verify outputs (core/brand_icon.py) -> publish into <home>/brand/
```

- `core/brand_icon.py` (pure, stdlib-only, any platform): `BrandIconError`
  (a `ValueError`), `inspect_png`, `validate_icon_png`, `fit_inside_square`,
  `read_ico_frames`, `check_standard_ico`, size constants. Details in D and E.
- `core/brand_render.py` (stdlib-only; Windows only at the renderer seam):
  - `monogram_style(brand) -> MonogramStyle`: pure. The disc is the accent. The
    glyph colour is graphite `#0A0D14` or white, whichever has the higher WCAG
    contrast ratio against the accent (any `#RRGGBB` stays legible; the default
    accent gets a graphite letter, matching the default icon palette).
  - `MonogramRequest` / `ImageRequest` (pure) and `command_line(...)`.
  - `generate_brand_assets(home, brand, *, renderer=run_powershell_renderer)`:
    validates, renders into a temp directory inside `<home>/brand/`, verifies both
    outputs with the pure checks, then `os.replace`s `brand.png` and `brand.ico`.
    Any failure before publishing leaves the previous files untouched and removes
    the temp directory.
  - `regenerate_home_icons(home, *, renderer=...) -> GenerationOutcome(assets,
    message)`: `load_brand(<home>/config.toml)`, the default-brand answer
    ("Default identity: nothing to generate"), else `generate_brand_assets`. This
    is the one entry point for the CLI, the button and task 3.
  - `main()`: prints the outcome message and exits 0, or prints the `ConfigError`
    or `BrandIconError` text to stderr and exits 1.
  - The renderer seam is `Callable[[RenderRequest, Path, Path], None]`, so
    orchestration is tested with a fake on every platform.
- `tools/generate_brand_icons.ps1`: standalone drawing tool, no decisions:
  `-OutputPng`, optional `-OutputIco`, and either `-CodePoint -DiscColor
  -GlyphColor -GlyphHeightRatio -GlyphWidthRatio -DiscMargin` or `-Source -FitX
  -FitY -FitWidth -FitHeight`, plus `-Canvas` (512). The letter travels as a code
  point because a Cyrillic letter in a command line is an encoding risk; a Windows
  test with a Cyrillic letter pins it. Exit code 2 means "image could not be
  decoded", 1 any other failure (message on stderr). This is the cheap standalone
  entry the wizard preview (task 4) can call directly.
- `tools/build_launcher_icon.ps1` is reused unchanged; `jarvis.ico` and its
  regeneration are not touched.
- Windows PowerShell 5.1 is the host (`%SystemRoot%\System32\WindowsPowerShell\
  v1.0\powershell.exe`, `-NoProfile -NonInteractive -ExecutionPolicy Bypass`,
  `CREATE_NO_WINDOW`, stdin from `DEVNULL` because `pythonw` has no usable
  stdin, timeout 30 s). PowerShell 7 lacks System.Drawing by default.
- Inventory: `tools/generate_brand_icons.ps1` and `tools/build_launcher_icon.ps1`
  are added to `APPLICATION_FILES`, so a deployed home can regenerate. This is the
  only task-2 edit to deployment code.

### C. Monogram art and the visual match with the Status Console mark

Drawn at 512x512 RGBA, transparent outside the disc: a disc of diameter 496
(margin 8, so the anti-aliased edge never clips), filled with the accent; the
glyph (Segoe UI Semibold, upper-case letter or digit, from a `GraphicsPath`, so
it is centred by its measured bounds, not by font metrics) scaled to at most 50%
of the disc diameter in height and 62% in width, so wide letters (W, M, Zh, Sh)
clear the rim. `build_launcher_icon.ps1` then downsamples to the nine frames.

It must match the CSS mark in identity, not pixel for pixel: same shape (circle),
same accent, same letter, same default letter and accent (both come from
`BrandSettings`). It differs in fill: the header mark is an outline on the dark
header, the icon is a filled disc, because a ring plus a same-colour letter is
muddy at 16 px on an unknown taskbar colour, and a filled disc with a
contrast-picked letter is legible on any taskbar. How the match is kept: one
`MonogramStyle` in Python holds every art constant; the CSS cannot import it, so a
test pins what is pinnable (the CSS circle rule for `data-brand="custom"`; the
default accent equal to `--cyan` is already pinned) and `PROJECT.md` documents the
outline-versus-fill difference as intentional. The owner judges the look in the
human handoff; switching to the exact CSS look (graphite disc, accent ring and
letter) means changing `MonogramStyle` and the PowerShell drawing only.

### D. User PNG: validation rules (resolves story open question 2)

`validate_icon_png(home, relative_icon, key="[brand].icon")` runs before any
rendering and before any System.Drawing call (a hostile header never reaches
GDI+). Deployment (task 3) and the wizard (task 4) call the same function. The
file size is checked first, so at most 8 MiB is read. Pixel rows are not decoded,
but the zlib stream is inflated with its output capped at the size the header
promises: measured, GDI+ draws a corrupt stream as a blank image without any error,
so the renderer cannot be relied on to report it. A decompression bomb is bounded by
the dimension limit and the output cap. The render-time row stays as a last resort
for a file GDI+ cannot load at all.

Every message starts with `[brand].icon "<value>": `:

The checks run in the order of the rows below, and the first failure is the one reported:
the whole chunk structure is checked before the size limits, so a truncated 32x32 file
is reported as truncated or corrupt, not as `is 32x32`; the size limits run before the
image-data inflate check (a huge declared size is rejected from the header alone).

| Check | Rule | Message after the prefix |
| --- | --- | --- |
| containment | resolved path inside the resolved home | `resolves outside the app home` |
| existence | regular file | `file not found: <absolute path>` / `is not a file` |
| file size | 0 < size <= 8 MiB | `is empty` / `is <n.n> MiB; the limit is 8 MiB` |
| signature | first 8 bytes `89 50 4E 47 0D 0A 1A 0A` | `is not a PNG file (bad signature)` |
| IHDR | first chunk, length 13, type IHDR, CRC valid | `has no valid PNG header (IHDR)` |
| IHDR fields | legal colour type and bit depth pair, compression 0, filter 0, interlace 0 or 1 | `has an unsupported PNG header: <detail>` |
| chunk walk | lengths fit the file, CRCs valid, IDAT present, PLTE for colour type 3, IEND last with nothing after | `is truncated or corrupt (<detail>)` |
| minimum size | shorter side >= 64 px | `is <w>x<h>; the shorter side must be at least 64 px` |
| maximum size | longer side <= 2048 px | `is <w>x<h>; the longer side must be at most 2048 px` |
| aspect | longer / shorter <= 2 | `is <w>x<h>; it must be at most twice as wide as high (or the reverse)` |
| image data | the zlib stream inflates to exactly the size the header promises (bounded output) | `is truncated or corrupt (image data does not decode)` |
| render time | GDI+ cannot load the file | `could not be decoded as an image` |

Decisions: minimum 64 px on the shorter side; maximum 2048 px (4.2 million
pixels, about 16 MiB as 32-bit; the bomb guard); file cap 8 MiB (the shipped
`jarvis.png`, 1254 px, is 1.5 MB). Non-square: accepted up to 2:1 and centred,
never cropped or stretched: it is scaled to fit a 512x512 transparent canvas
(`fit_inside_square(w, h, 512)`, integer maths, both axes centred); beyond 2:1 it
is rejected, because such an image would shrink to a sliver at 16 px and an
explicit message serves the owner better. Transparency is accepted and preserved
(colour types 4 and 6, and a `tRNS` chunk); there is no matte or flattening, and a
fully transparent image is not detected (it would need decoding). A square source
smaller than 512 px is upscaled for `brand.png`.

### E. ICO verification (the container writer stays in PowerShell)

The ICO writer stays in `build_launcher_icon.ps1`: moving it to Python would still
need the scaled frames from System.Drawing and would duplicate a shipped, proven
writer. Python gets a verifier: `read_ico_frames(data)` raises `BrandIconError`
when the header is not `00 00 01 00`, there are no entries, an entry or frame lies
outside the file, or a PNG frame's IHDR size differs from its directory entry (0
means 256). Non-PNG (DIB) frames are bounds-checked only, so a hand-placed classic
`brand.ico` is not rejected. `check_standard_ico(data)` additionally requires the
nine standard sizes; the orchestrator uses it on generated files. The launcher
uses `read_ico_frames` before handing a file to Win32 or Tk.

### F. Launcher identity

`launcher/identity.py` (stdlib-only, no tkinter, no engine):

```
@dataclass(frozen=True)
class LauncherIdentity: name: str; icon: Path
DEFAULT_IDENTITY = LauncherIdentity("Jarvis", PACKAGE_ASSETS / "jarvis.ico")
def load_launcher_identity(home: Path) -> LauncherIdentity   # never raises
```

- Read `load_brand(home / "config.toml")`. Any `Exception` from it (`ConfigError`,
  `OSError`, `RecursionError`, `MemoryError`, as in the task-1 message-box path)
  yields `DEFAULT_IDENTITY` and one warning in `launcher.log` naming the home and
  the reason. No dialog: branding is cosmetic, and an invalid config is reported by
  the runtime itself on start.
- A default brand (`== BrandSettings()`) gives `DEFAULT_IDENTITY`; `<home>/brand/`
  is ignored. This refines the task-1 precedence rule at the consumer: after the
  owner deletes `[brand]`, stale generated files must not keep showing a custom
  icon under the name Jarvis.
- A non-default brand gives its `name` and `resolve_brand_assets(home).ico` if
  `read_ico_frames` accepts it (and it is at most 8 MiB), else the packaged icon
  with the brand's name (per-field fallback).
- `tray_tooltip(name, mode, exiting)` builds the tooltip in one place:
  `<name> - waiting for a mode`, `<name> - Assistant`, `<name> - Mcp`, `<name> -
  shutting down`. The 32-character name cap keeps the longest under the 127 usable
  characters of `szTip`; a test pins the worst case.

When the identity is reloaded (the decision the owner asked for): at launcher
start, immediately after a successful `set_home` (Settings, Save folder), before
each mode start (cheap read, no write: the tooltip name follows `config.toml`),
and after the Regenerate button. It is not polled while a runtime runs. On a
reload the tray tooltip and icon, the hidden root's icon and the open Settings
window title, header and icon refresh immediately. Applying only at the next
launcher start was rejected: the launcher would label and start an instance with
the previous home's identity, which defeats the story's purpose.

Tray mechanics: `WindowsTray.set_identity(name, icon)` stores the pending pair
under a lock and posts `WM_REFRESH`; the tray thread loads the new icon with
`LoadImageW`, swaps `hIcon`, sends `NIM_MODIFY`, then destroys the old handle. If
the new icon cannot be loaded the packaged icon is loaded instead. Tk: one helper
`set_window_icon(window, path)` in `window.py` replaces the `iconbitmap` calls and
falls back to the packaged icon on `tk.TclError`.

Launcher surfaces (instance text uses the name; product and guard texts keep
"Jarvis", for the reason given in task 1: the mutexes are per user, not per home):

| Surface | Result |
| --- | --- |
| Tray tooltip, tray icon | name and brand icon |
| Tk root icon, Settings and dialog window icons | brand icon |
| Settings window title and header label | `<name> - Settings`, `<NAME>` |
| Dialog window title and header label | `<name>`, `<NAME>` |
| "Jarvis stopped unexpectedly" | `<name> stopped unexpectedly` (instance-specific) |
| "Jarvis is already running" (`RuntimeBusyError`), About body and its "Jarvis" heading, launcher-already-running dialog, "Launcher error", pre-guard dialogs and icon | unchanged, default identity (other instance, product text, or before the home is known) |
| Tray window class `JarvisLauncherTray`, hidden window text, mutex, `%LOCALAPPDATA%\JarvisLauncher`, autostart value | unchanged (technical identifiers) |

`dialog(...)` and `SettingsWindow` take `identity` with `DEFAULT_IDENTITY` as the
default, so existing call sites and tests keep working.

## Boundary

In: the modules and scripts above; two inventory entries in
`tools/deployment_plan.py`; launcher wiring; the Settings button; `PROJECT.md` (the
icon pipeline, the regeneration rule and the launcher identity policy, in the
"instance branding" section, same change per CLAUDE.md "Project context" 2);
`src/jarvis/launcher/assets/README.md` (one paragraph: brand icons are generated,
`jarvis.*` stay the defaults); tests; a human handoff.

Out (later cards): `deploy.cmd` flags, TOML rewrite and verification, Copy-mode
inheritance, shortcut name and icon, calling the generator from deploy (task 3);
the wizard screen and live preview (task 4); README and release handoff (task 5).
Also out: the Status Console, the touchstrip, the `{brand}` strings and the CSS
(task 1); any technical identifier; the single-instance guard; a Status Console
Settings brand editor; a current-brand or icon preview in launcher Settings;
automatic or self-healing regeneration, a manifest or staleness tracking; a
launcher dialog for a rejected `[brand]` at start; `jarvis.png`, `jarvis.ico` and
`build_launcher_icon.ps1` content; CI configuration. The runtime does not consume
the icons.

## Acceptance criteria

- [x] Without `[brand]` the launcher behaves as before: tooltips `Jarvis - ...`, packaged icon, titles `Jarvis` and `Jarvis - Settings`, header `JARVIS`. Proof: tests/test_launcher_tray_identity.py::test_the_default_name_keeps_the_original_tooltips, tests/test_launcher_identity.py::test_a_home_without_a_config_has_the_default_identity, tests/test_launcher_app_identity.py::test_an_unbranded_home_gives_the_tray_the_default_identity; the pre-existing tests/test_launcher*.py pass unchanged; window titles and header are Case A of the handoff.
- [x] `[brand]` with `name`, `monogram`, `accent` in the selected home: tray tooltip and icon, Tk icons, Settings and dialog titles and headers show the identity; a hostile name is shown literally and the tooltip never exceeds the `szTip` limit. Proof: tests/test_launcher_identity.py::test_a_branded_home_uses_its_name_and_generated_icon and ::test_a_hostile_name_is_kept_literally, tests/test_launcher_tray_identity.py (worst-case tooltip length, refresh and icon swap), tests/test_launcher_app_identity.py::test_a_branded_home_gives_the_tray_its_name_and_icon; pixels are human-run (Cases B, C, D).
- [x] Changing the home in Settings updates tray tooltip and icon at once; editing `[brand]` and starting a mode picks the name up; no launcher restart. Proof: tests/test_launcher_app_identity.py::test_a_home_change_reloads_the_identity_and_clears_the_icon_status, ::test_starting_a_mode_picks_up_a_name_edited_in_the_config, ::test_the_open_settings_window_is_re_skinned_on_reload; live tray is human-run (Case G).
- [x] A missing config, an invalid `[brand]`, an undecodable file, a corrupt `brand.ico` or a failing icon load leaves the launcher running with the default identity (per field), with a warning in `launcher.log`. Proof: tests/test_launcher_identity.py (missing, invalid, undecodable, RecursionError/MemoryError/PermissionError, corrupt and oversized icon, per-field fallback, warning logged), tests/test_launcher_tray_identity.py::test_an_icon_that_cannot_be_loaded_falls_back_to_the_packaged_one and ::test_when_no_icon_can_be_loaded_the_old_icon_and_the_tray_stay, tests/test_launcher_app_identity.py::test_a_window_icon_that_tk_rejects_falls_back_to_the_packaged_icon.
- [x] A default brand ignores a stale `<home>/brand/`. Proof: tests/test_launcher_identity.py::test_a_default_brand_ignores_stale_generated_files and ::test_deleting_the_brand_section_returns_the_default_although_files_remain.
- [x] The monogram renderer produces a 512x512 RGBA `brand.png` (transparent corners, accent disc, letter in the contrast colour) and a `brand.ico` with exactly the nine standard PNG frames, for a Latin letter, a Cyrillic letter and a digit. Proof: tests/test_brand_render_windows.py::test_a_monogram_is_a_transparent_cornered_accent_disc_with_the_letter (W, Cyrillic Zhe, 7; real System.Drawing, skipped off Windows) and ::test_a_dark_accent_gets_a_white_letter; the letter-colour rule: tests/test_brand_render.py.
- [x] A valid user PNG (square; non-square within 2:1; with transparency) becomes a 512x512 `brand.png` with the image centred and undistorted, and a matching `brand.ico`. Proof: tests/test_brand_render_windows.py::test_a_non_square_transparent_user_png_is_centred_and_undistorted and ::test_a_square_user_png_fills_the_whole_canvas; fit maths: tests/test_brand_icon_png.py.
- [x] Each invalid-PNG case in table D is rejected before System.Drawing runs, with the listed message naming `[brand].icon` and the value; limits are exact at the boundaries (63/64, 2048/2049, 2:1, 8 MiB). Proof: tests/test_brand_icon_png.py (every row of table D, boundaries 63/64, 2048/2049, 2:1, 8 MiB, hostile value quoting, validation before the data check) and tests/test_brand_render.py::test_an_invalid_user_icon_is_rejected_before_the_renderer_runs.
- [x] A failed or killed render leaves previous `brand/` files untouched and no temp directory behind. Proof: tests/test_brand_render.py::test_a_failing_renderer_keeps_the_previous_files_and_removes_staging and ::test_unusable_renderer_output_is_never_published; timeout and start failures: ::test_a_renderer_timeout_is_reported, ::test_a_renderer_that_cannot_start_is_reported.
- [x] The "Regenerate icons" button runs the generator for the saved home on a worker thread, shows "Working...", disables itself meanwhile, re-enables, then reloads the identity and refreshes tray and windows; the default brand answers "Default identity: nothing to generate" and deletes nothing; errors appear in a dialog with the exact message and in `launcher.log`. Proof: logic: tests/test_launcher_branding.py (worker thread, one job at a time, Working..., re-enable, identity reload, default-brand answer, exact error to the dialog) and tests/test_launcher_app_identity.py (tick polls the job, reload, branded error dialog); the Tk widgets themselves and the freeze-free feel are human-run (Cases A to E).
- [x] `core/brand_icon.py` imports only the standard library, `core/brand_render.py` only the standard library and `jarvis.core`; importing the launcher modules loads no engine module. Proof: tests/test_brand_icon_png.py::test_the_icon_validation_module_is_stdlib_only, tests/test_brand_render.py::test_the_render_module_imports_only_the_standard_library_and_jarvis_core, tests/test_launcher_identity.py::test_importing_the_launcher_modules_loads_no_engine_module.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` green; tests that need Windows PowerShell skip cleanly elsewhere. The human tray handoff is prepared, not run. Proof: `python -m pytest` 6790 passed, 1 skipped; `ruff check .` all checks passed; `ruff format --check .` 656 files already formatted; the handoff is manual/instance-branding-2-handoff.md (not run).

## Implementation plan (TDD order)

1. `tests/png_fixtures.py` (builds PNG bytes with `zlib` and `struct`; no binary
   files committed), `tests/test_brand_icon_png.py`, then `core/brand_icon.py`
   PNG part: `inspect_png`, `validate_icon_png`, `fit_inside_square`.
2. `tests/test_brand_icon_ico.py`, then `read_ico_frames`, `check_standard_ico`
   (includes parsing the shipped `jarvis.ico`).
3. `tests/test_brand_render.py` (fake renderer): `monogram_style` (contrast table),
   code points for Latin, Cyrillic, digits, `command_line`, orchestration, atomic
   publish and failure cleanup, renderer error mapping, default-brand outcome, CLI.
4. `tools/generate_brand_icons.ps1`, `run_powershell_renderer`,
   `tests/test_brand_render_windows.py` (skipped off Windows) with a test-only
   PNG pixel reader.
5. `tests/test_launcher_identity.py`, then `launcher/identity.py`; tooltip tests;
   a subprocess test that the launcher modules load no engine module.
6. Launcher wiring: `WindowsTray.set_identity` and the `WM_REFRESH` handler,
   `set_window_icon`, `LauncherApp` identity reload, `SettingsWindow` identity,
   home-changed hook, Regenerate button with the worker (a pure-logic helper for
   the worker result so the flow is testable without Tk).
7. Inventory entries; CSS pin test; `PROJECT.md`; assets README; handoff.
8. `python -m pytest`, `ruff check`, `ruff format --check`.

Automated (pure logic, every platform): D, E, `monogram_style`, request building,
orchestration with a fake renderer, identity rules, tooltip, tray message
handling with mocked `user32`, the button worker flow. Automated on Windows only
(skipped elsewhere; they also run on the `windows-latest` CI, which already runs
PowerShell tests): the real System.Drawing render and its output files.
Human-run: how the icons look, tray and taskbar rendering, Explorer icon views,
16 px legibility, the button and the Settings home switch with a live tray.

## Human handoff outline

`manual/instance-branding-2-handoff.md`, self-sufficient per CLAUDE.md Testing
protocol 4. It names literally, with source references: the start command
(`JarvisLauncher.cmd`, repository root) and the explicit state before each case
(launcher running or stopped; Jarvis runtime stopped; a running instance blocks a
second start before config loads, so stop it first), the launcher Settings field
and buttons (`Jarvis Home Folder`, `Save folder`, `Regenerate icons`,
`launcher/window.py`), the preferences file (`%LOCALAPPDATA%\JarvisLauncher\
settings.json`) and log (`launcher.log`), the CLI (`python -m
jarvis.core.brand_render --home <dir>`, source `core/brand_render.py`), the
`[brand]` blocks to paste, and the README debt (README does not yet document
`[brand]`, the button or the CLI). Cases:

- default home: tray default; button says "Default identity: nothing to generate",
  files unchanged;
- `name = "Work"`, `monogram = "W"`, `accent = "#E0A03F"`: button, then the tray
  icon and tooltip change at once without restarting the launcher; check dark and
  light taskbar, 100% and a higher scale, 16 px legibility, the Explorer large icon
  of `brand\brand.ico`;
- hand edit of `accent`: the tray stays stale until the button is clicked, then
  updates (the accepted behaviour);
- Cyrillic name and letter; a digit monogram; a user PNG square, a non-square
  transparent PNG;
- rejected PNGs (renamed text file, 32 px, 3000 px, truncated, 5:1): the dialog shows
  the exact listed message, the old files stay;
- button while a Jarvis runtime of that home is running: allowed, no effect on the
  running instance;
- Settings home switch between a default and a branded home with the tray
  updating live (the runtime must be stopped; the launcher refuses a home change
  otherwise);
- invalid `[brand]`: launcher keeps running with the default identity, warning in
  `launcher.log`;
- deleting `[brand]` returns the default icon although `brand\` remains.

## Implementation notes (2026-11-26)

- GDI+ does not fail on a corrupt PNG data stream (measured: a garbage IDAT and a
  bad filter byte both draw as a blank image with no exception), so the zlib
  stream check lives in `core/brand_icon.py` instead of relying on the renderer.
  The Windows decode-failure test of the first design was therefore dropped; the
  exit-code-2 path is covered with a fake process.
- `tray_tooltip` keeps the existing wording (`Jarvis - Mcp`, from `str.title()`).
- `WindowsTray.set_identity` always reloads the icon: after a regeneration the path
  is the same but the file is new.
- Review round 1: `IconRegeneration.click()` assigns the job only after `start()`
  returns, and a worker that cannot start ends in the error dialog instead of a
  permanently disabled button; a directory junction inside the home that points
  outside is pinned as rejected (`tests/test_brand_icon_png.py`, Windows only);
  the handoff writes ASCII `config.toml` files (PowerShell 5.1 `-Encoding UTF8`
  adds a BOM that `tomllib` rejects) and every case runs from a fresh window.
- Review round 2: the busy dialog (`RuntimeBusyError`), the About dialog and the
  "Launcher error" dialog now use `DEFAULT_IDENTITY` chrome as the surface table
  says (tests assert the `identity` kwarg against a branded home); the generator
  resolves the home, so its message always shows an absolute path;
  `validate_icon_png` maps every file-system failure (including `exists()` and
  `stat()`) to a prefixed `cannot be read: <reason>` error.
- Renderer stderr: the script now switches its console output to UTF-8 (best
  effort) and Python decodes it as UTF-8, so a non-ASCII path in a failure message
  is not garbled by an OEM or ANSI code page. Known limitation of the proof: on the
  development machine both system code pages are already UTF-8 (65001), so
  `test_a_non_ascii_path_in_a_renderer_message_reaches_python_intact` passes with or
  without the fix here; it pins the round trip and would fail on a machine with
  single-byte code pages if the fix were removed.
- The new Settings widgets and the tray icon swap are not exercised by an
  automated Tk test (no display in CI); the button logic is a plain class
  (`IconRegeneration`) tested without Tk.

## Blocking questions

None. Question 1 (regeneration policy) was answered by the owner: Option A plus the
Settings button.

## Decisions taken without a question (reverse any of them if wrong)

- Open question 2: minimum 64 px on the shorter side, maximum 2048 px, 8 MiB,
  non-square accepted up to 2:1 and centred without cropping or stretching,
  rejected beyond; transparency accepted and preserved.
- The generated icon is a filled accent disc with a graphite or white letter
  chosen by contrast; the CSS mark stays an outline (section C). The filled style
  is the owner's call at the human review of the tray rendering.
- All art and colour decisions live in Python; the PowerShell script only draws.
- The ICO writer stays in PowerShell; `build_launcher_icon.ps1` is reused
  unchanged; Python only verifies ICO files.
- `brand.png` is the 512x512 master, not a copy of the user's file.
- A default brand ignores `<home>/brand/` in the launcher.
- Launcher identity falls back silently (log only), per field.
- The button regenerates the saved home (not unsaved text in the folder field).
- Product and other-instance texts keep "Jarvis" (About, `RuntimeBusyError`,
  launcher-already-running); instance texts use the name.
- The two published files are each replaced atomically; if the second replace
  fails after the first succeeded (an OS-level failure), the error is reported and
  a second click repairs the pair.
- No new Python dependency and no change to `requirements.txt` or CI.
- The task-1 `[brand].icon` path-shape check is unchanged; content validation
  lives in `core/brand_icon.py`.
