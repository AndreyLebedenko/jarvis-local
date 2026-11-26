# Instance branding, task 2: icons and launcher identity (visual handoff)

Human-run, per Testing protocol item 4 (`CLAUDE.md`). It draws real tray icons,
Tk windows and Explorer icon views, so the agent prepared it and ran none of it.
Card: `tasks/done/task-instance-branding-2-icons-and-launcher.md`.

What it answers: with a `[brand]` section in the selected home, the tray tooltip,
tray icon, launcher window titles and icons show the brand after you use the
`Regenerate icons` button; the generated icons look right and stay legible at 16
px; rejected PNGs show the exact messages; a broken or removed `[brand]` leaves
the launcher on the default Jarvis identity.

Known and accepted behaviour (owner, 2026-11-26): the tray icon does NOT change
when you hand-edit `config.toml`. Icons change only when you click `Regenerate
icons` in the launcher Settings (or run the CLI). The tooltip name is re-read from
`config.toml` when a mode starts, when the home changes, and after the button.

Out of scope here: the Status Console header and window titles (task 1 handoff,
`manual/instance-branding-1-handoff.md`), deployment flags and shortcuts (task 3),
the wizard (task 4). The README does not mention `[brand]`, the button or the CLI
yet (story task 5 debt, not crossed silently - do not look for them there). The
keys are in `config.example.toml` (section `[brand]`, commented) and `PROJECT.md`
("Architecture: instance branding").

## Names used below

- Repository root = the app home = the folder that holds `JarvisLauncher.cmd`,
  `config.toml` and `.venv`. All commands run there, in PowerShell.
- Launcher = `JarvisLauncher.cmd` (it starts `.venv\Scripts\pythonw.exe -m
  jarvis.launcher`; no console window appears). Its tray menu is `Assistant`, `MCP`,
  `Show Touchstrip`, `Settings`, `Exit` (`MENU_ITEMS` in `src/jarvis/launcher/tray.py`).
  The icon may sit under the `^` overflow arrow; drag it onto the taskbar to keep it
  visible.
- Launcher Settings = tray right-click, `Settings`. Window title `<name> - Settings`.
  Controls (`src/jarvis/launcher/window.py`): `Jarvis Home Folder` field, `Browse...`,
  `Regenerate icons`, `Save folder`, and a status line under the folder block.
- Launcher log = `%LOCALAPPDATA%\JarvisLauncher\launcher.log`. Launcher preferences
  = `%LOCALAPPDATA%\JarvisLauncher\settings.json` (key `home`).
- Stop the launcher = tray right-click, `Exit` (with no runtime alive it exits at
  once). Stop a runtime started from the launcher = close the Status Console window
  with its X (it shuts the runtime down; wait until the tooltip ends with `waiting
  for a mode`).
- A running Jarvis instance blocks a second start before any config is read
  (`Local\Jarvis.SingleInstance`), and a second launcher shows `Launcher is already
  running`. Every case below states the starting state: follow it, do not assume it.

## Preparation

Encoding rule for every `config.toml` edit in this handoff: save the file as UTF-8
WITHOUT a byte order mark (Windows 11 Notepad's default `UTF-8`; `UTF-8 with BOM` is
rejected by the TOML reader with `Malformed TOML ... Invalid statement (at line 1,
column 1)` and the launcher then shows the default identity). Windows PowerShell 5.1
`Set-Content -Encoding UTF8` writes a BOM, so the commands below use `-Encoding
ASCII` for ASCII content.

1. State: no launcher, no runtime. Exit the launcher from its tray menu if it runs
   and stop any runtime. Check (expect no output):

   `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'jarvis' -and $_.Name -match '^pythonw?\.exe$' } | Select-Object ProcessId, CommandLine`

2. State-independent clean slate for the repository root: make sure `config.toml`
   has no `[brand]` section (delete the block if present; TOML forbids a second
   one), and remove generated icons: `Remove-Item -Recurse -Force .\brand
   -ErrorAction SilentlyContinue` (the folder holds only generated `brand.png` and
   `brand.ico`).
3. Print what the launcher will use (source: `load_launcher_identity` in
   `src/jarvis/launcher/identity.py`):

   `.venv\Scripts\python.exe -c "from pathlib import Path; from jarvis.launcher.identity import load_launcher_identity; print(load_launcher_identity(Path('.').resolve()))"`

   Expected (forward slashes, as Python prints a `WindowsPath`): `LauncherIdentity(name='Jarvis',
   icon=WindowsPath('<repository root>/src/jarvis/launcher/assets/jarvis.ico'))`, for
   example `...icon=WindowsPath('D:/AI/Jarvis/src/jarvis/launcher/assets/jarvis.ico'))`.
4. Make the second home used in Case G (a folder with only the two marker files the
   launcher checks, `validate_home` in `src/jarvis/launcher/model.py`; it cannot run
   Jarvis, never start a mode there):

   ```powershell
   $other = "$env:TEMP\jarvis-brand-other"
   Remove-Item -Recurse -Force $other -ErrorAction SilentlyContinue   # leftovers of an earlier run, brand\ included
   New-Item -ItemType Directory -Force "$other\.venv\Scripts", "$other\src\jarvis\launcher" | Out-Null
   New-Item -ItemType File -Force "$other\.venv\Scripts\python.exe", "$other\src\jarvis\launcher\runtime.py" | Out-Null
   Set-Content -Encoding ASCII "$other\config.toml" "[brand]`nname = `"Other`"`nmonogram = `"O`"`naccent = `"#8040C0`"`n"
   ```

5. Test images used in Case E (state-independent; recreated every time):

   ```powershell
   Add-Type -AssemblyName System.Drawing
   New-Item -ItemType Directory -Force .\icon-tests | Out-Null
   function New-TestPng($name, $w, $h) {
       $b = [Drawing.Bitmap]::new($w, $h, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
       $g = [Drawing.Graphics]::FromImage($b); $g.Clear([Drawing.Color]::Transparent)
       $g.FillEllipse([Drawing.Brushes]::OrangeRed, 2, 2, $w - 4, $h - 4)
       $g.FillRectangle([Drawing.Brushes]::RoyalBlue, 0, 0, [int]($w / 6), [int]($h / 6))
       $b.Save((Join-Path (Resolve-Path .\icon-tests) $name), [Drawing.Imaging.ImageFormat]::Png)
       $g.Dispose(); $b.Dispose()
   }
   New-TestPng square.png 256 256; New-TestPng wide.png 300 150
   New-TestPng tiny.png 32 32; New-TestPng sliver.png 500 100; New-TestPng huge.png 3000 3000
   Set-Content .\icon-tests\notpng.png "this is text, not an image"
   $bytes = [IO.File]::ReadAllBytes((Resolve-Path .\icon-tests\square.png))
   [IO.File]::WriteAllBytes("$PWD\icon-tests\truncated.png", $bytes[0..($bytes.Length - 40)])
   ```

   Each image is an orange-red ellipse with a blue square in the top-left corner and
   transparent corners (a 2:1 ellipse in `wide.png`).

## Case A: default identity (regression)

State: no launcher, no runtime (Preparation step 1). Start `.\JarvisLauncher.cmd`.
In Settings open the `Jarvis Home Folder` field: it must hold the repository root;
if it does not, type the repository root and press `Save folder`.

Expect, exactly as before the change: tray icon = the packaged dark graphite tile
with the cyan mark; tooltip `Jarvis - waiting for a mode`; Settings window title
`Jarvis - Settings` and header `JARVIS`.

Click `Regenerate icons`: the status line reads `Default identity: nothing to
generate`; `Test-Path .\brand` is `False`; the tray icon is unchanged.

## Case B: monogram brand and the button

State: launcher running idle (end of Case A), Settings may stay open, no runtime.
Append to `config.toml`:

```toml
[brand]
name = "Work"
monogram = "W"
accent = "#E0A03F"
```

Before clicking: the tray icon and tooltip are still the default (accepted
behaviour). Click `Regenerate icons`:

- the button greys out and the status line shows `Working...` (the render takes
  about half a second, so you may only see it flash), the Settings window stays
  responsive (move it while it works);
- then the status line reads `Generated brand icons in <repository root>\brand`;
- the tray icon becomes an amber disc with a graphite `W`; hover shows `Work - waiting for a mode`;
- the Settings title reads `Work - Settings`, the header `WORK`, and the window's
  title-bar icon is the new one (close and reopen Settings too: same result).

Files: `Get-ChildItem .\brand` lists exactly `brand.ico` and `brand.png` (no
`.render-*` folder). Open `brand\brand.png`: a 512 px amber disc, a graphite `W`,
transparent corners. CLI alternative (same code): `.venv\Scripts\python.exe -m
jarvis.core.brand_render --home .` prints `Generated brand icons in <root>\brand`
(source: `src/jarvis/core/brand_render.py`).

Look at it, as the owner (the filled-disc style is your call): tray icon at 16 px
(is the `W` readable at 100% display scale?); the same at 150% or 200%
(Settings > System > Display > Scale); on a dark and on a light taskbar (Settings >
Personalization > Colors > `Choose your mode`: Dark, then Light); Explorer: open
`.\brand`, View > `Extra large icons` for `brand.ico`, and `Small icons`.

Style comparison: right-click the tray icon, `Assistant`. Tooltip `Work - Assistant`.
The Status Console header mark is an amber OUTLINED circle with `W`, the tray icon a
FILLED amber disc: the card (section C) says this difference is intended; judge
whether you accept it. Leave Jarvis running for Case C.

## Case C: button while a runtime of that home runs

State: Assistant running (end of Case B), Settings open. Expect: `Jarvis Home
Folder`, `Browse...` and `Save folder` are greyed out (the home cannot change while
a runtime is alive) but `Regenerate icons` is enabled.

Change `accent = "#E0A03F"` to `accent = "#2060E0"` in `config.toml`. The tray icon
does not change yet. Click `Regenerate icons`: the tray icon becomes a blue disc with
a WHITE `W` (white because it contrasts better than graphite on dark blue); the
running Status Console is unaffected and keeps working.

Now close the Status Console with its X and wait for `Work - waiting for a mode`.
State: launcher idle, no runtime.

## Case D: hand edits, name, Cyrillic, digit

State: launcher idle, no runtime. Set the block to:

```toml
[brand]
name = "Работа"
monogram = "Ж"
accent = "#3FE0D0"
```

Nothing changes in the tray (stale until the button). Click `Regenerate icons`: a cyan
disc with a graphite `Ж`; tooltip `Работа - waiting for a mode`; Settings header
`РАБОТА`. Then replace the block with `name = "7 Floor"` only (delete the monogram
and accent lines): click the button: a disc with `7` in the default cyan, tooltip
`7 Floor - waiting for a mode`.

Name follows the config at mode start. Change only `name = "Seven"` (do not click
the button), right-click the tray, `Assistant`: the tooltip reads `Seven - Assistant`
while the icon stays the old one. Close the Status Console with its X; wait for the
idle tooltip. State: launcher idle, no runtime.

## Case E: user PNG

State: launcher idle, no runtime, test images exist (Preparation step 5). For each row
set `[brand]` to `name = "Work"`, `monogram = "W"` plus the `icon` line, click
`Regenerate icons`.

| `icon = "..."` | Expect |
| --- | --- |
| `icon-tests/square.png` | status `Generated brand icons in ...`; tray icon = the ellipse (a circle here) filling the icon, blue square top-left, transparent corners (the taskbar shows through) |
| `icon-tests/wide.png` | the 2:1 ellipse stays a 2:1 ellipse, centred, empty bands above and below; not squeezed into a circle, not cropped |
| `icon-tests/tiny.png` | dialog `Could not complete the action`: `[brand].icon "icon-tests/tiny.png": is 32x32; the shorter side must be at least 64 px` |
| `icon-tests/huge.png` | `[brand].icon "icon-tests/huge.png": is 3000x3000; the longer side must be at most 2048 px` |
| `icon-tests/sliver.png` | `[brand].icon "icon-tests/sliver.png": is 500x100; it must be at most twice as wide as high (or the reverse)` |
| `icon-tests/notpng.png` | `[brand].icon "icon-tests/notpng.png": is not a PNG file (bad signature)` |
| `icon-tests/truncated.png` | `[brand].icon "icon-tests/truncated.png": is truncated or corrupt (` followed by a detail |
| `icon-tests/missing.png` | `[brand].icon "icon-tests/missing.png": file not found: <absolute path>` |

After each rejected row: the status line reads `Icon generation failed`, the button is
enabled again, the tray icon is the one from the last successful row, `Get-Item
.\brand\brand.ico | Select LastWriteTime` is unchanged, `Get-ChildItem .\brand` has no
`.render-*` folder, and `launcher.log` has a line `Launcher operation failed:` with the
same message. Two more rows come from the config check, before any file is read:
`icon = "../x.png"` gives `[brand].icon must stay inside the app home (no '..'), got
'../x.png'` and `icon = "C:/x.png"` gives `[brand].icon must be relative to the app
home, got 'C:/x.png'` (use forward slashes: a backslash in a TOML basic string needs
escaping).

## Case F: invalid `[brand]`, launcher stays up

State: launcher idle. Set `[brand]` to `monogram = "AB"` (nothing else). Click
`Regenerate icons`: dialog with `[brand].monogram must be exactly one Latin or
Cyrillic letter or digit, got 'AB'`. Then tray `Exit` and start `.\JarvisLauncher.cmd`
again: the launcher starts with the default tray icon and `Jarvis - waiting for a
mode`; `launcher.log` has a WARNING `Brand of <root> is not usable (...)`. State:
launcher idle.

## Case G: home switch with a live tray

State: launcher idle, no runtime. Put the Case B block back (`name = "Work"`,
`monogram = "W"`, `accent = "#E0A03F"`), click `Regenerate icons` (amber `W`). Print
the second home's path with `Write-Output "$env:TEMP\jarvis-brand-other"` (created in
Preparation step 4; it persists on disk, so any PowerShell window will do), type that
path into `Jarvis Home Folder` and press `Save folder`. At once, without clicking
anything else: tooltip `Other - waiting for a mode`, tray icon = the packaged icon (that home
has no generated icons yet), Settings title `Other - Settings`. Click `Regenerate
icons`: a violet disc with a white `O`. Type the repository root again and press `Save
folder`: the amber `W` and `Work - waiting for a mode` return at once.

## Case H: delete `[brand]`, stale files are ignored

State: launcher idle. Delete the `[brand]` block from `config.toml`. Tray `Exit`, start
`.\JarvisLauncher.cmd`: tray icon is the packaged default and the tooltip `Jarvis -
waiting for a mode` although `Test-Path .\brand\brand.ico` is still `True`. Click
`Regenerate icons`: `Default identity: nothing to generate`, and `.\brand` still holds
its files (nothing is deleted).

## Cleanup (state-independent)

Tray `Exit`. `Remove-Item -Recurse -Force .\icon-tests, .\brand,
"$env:TEMP\jarvis-brand-other" -ErrorAction SilentlyContinue` (a literal path, so it
works in a fresh window); make sure `config.toml` has no `[brand]` block; start
`.\JarvisLauncher.cmd` once more if you want the launcher running (Jarvis Home Folder =
repository root).

## Report back

For each case: pass or the exact difference (what you saw instead). The judgement
calls are yours: 16 px legibility of the generated icons, the filled disc versus the
Status Console outline mark, the `Working...` feel of the button.
