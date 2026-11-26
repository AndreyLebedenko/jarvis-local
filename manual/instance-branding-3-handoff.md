# Instance branding, task 3: deployment integration (human handoff)

Human-run, per Testing protocol item 4 (`CLAUDE.md`). It runs real deployments
(a real installer, `pip install`, Windows PowerShell, cmd.exe quoting) and looks
at real shortcuts and Explorer icons, so the agent prepared it and ran none of
the installer or UI cases. The agent did run, with a fake installer in a scratch
folder, the instant commands of Cases 1, 2 and 5 (Case 1 with a scratch folder for the PNGs)
and the sequence of output lines, config tails and file lists of Cases 3 and 7
(real renderer, real repository, fake installer); the outputs below are the ones it
printed (only the folder names differ). The installer lines, the wizard pages and
every icon's look are untested by the agent.
Card: `tasks/done/task-instance-branding-3-deployment-integration.md`.

What it answers: `deploy.cmd` accepts the brand options and rejects bad ones
before it writes anything; a Clean home gets the requested `[brand]`, generated
icons (without any `.venv` at that moment) and a user PNG stored home-relative; a
Copy inherits the source brand by value, can override it, and never touches the
source; the wizard's `Create shortcut...` names the shortcut after the brand and
uses its icon.

Out of scope here (do not look for them): the wizard Identity screen with the
live preview (story task 4: the wizard has no brand fields yet, so a wizard Copy
can only INHERIT a brand), the README (story task 5: it does not mention `-Name`,
`-Monogram`, `-Accent`, `-Icon`, `-NoIcon`, `-DefaultBrand`, `[brand]` or
`brand-source\` yet; this handoff and `PROJECT.md` section "Architecture:
instance branding" are the only documentation), the tray launcher shortcut
(`tools\create_launcher_shortcut.ps1` is deliberately unchanged:
`Jarvis Launcher.lnk`, packaged icon).

## Names and fixed paths

- Repository = `D:\AI\Jarvis` (the folder holding `deploy.cmd`, `DeploymentWizard.cmd`
  and `config.example.toml`). If yours is elsewhere, replace the prefix everywhere.
- Test area = `D:\AI\jarvis-brand3-tests` (outside the repository, so no destination
  can overlap a source). Every destination below is a new folder in it.
- All commands run in a fresh Windows PowerShell 5.1 window (`powershell.exe`);
  every case starts with its own `cd`.
- `deploy.cmd` options (source: `tools\install\deploy.ps1`): `-Target`, `-Mode clean|copy`,
  `-Yes`, `-Resume`, `-Preview`, and the brand options `-Name`, `-Monogram`, `-Accent`,
  `-Icon <png>`, `-NoIcon`, `-DefaultBrand`. `-Yes` lets the deployment install
  Python 3.11 through winget if none is found (without it you are asked). `-Preview`
  checks everything and prints one `JARVIS_DEPLOY_PREVIEW:{...}` line; it writes nothing.
- Quoting through `deploy.cmd` (cmd.exe sits in front of PowerShell): a value with
  spaces or `&`, `^`, `%` goes in quotes (`'Work: R&D?'` in PowerShell); a double
  quote inside a name is written `\"` inside single quotes (`'Say \"hi\"'`).
- Files written by this handoff: PNG images and shortcuts only. No `config.toml` is
  ever written by hand here (a PowerShell 5.1 `-Encoding UTF8` file would carry a BOM
  that the TOML reader rejects); `config.toml` files are only read.
- Running state. Clean cases and all `-Preview` runs of Clean do not care whether Jarvis
  runs. Every Copy case (preview or deploy) takes the runtime lock
  `Local\Jarvis.SingleInstance` (`MUTEX_NAME`, `src\jarvis\core\single_instance.py`
  line 18) for a moment and is refused while a Jarvis runtime
  (Assistant or MCP mode, started by anything) is alive: stop it first. The tray launcher
  may stay running idle (it holds a different lock). Never start Jarvis from a test home;
  never click `Launch Jarvis`.
- Time: each case that runs the installer takes several minutes (it creates a `.venv` and
  runs `pip install -r requirements.txt`) and needs network and Ollama installed (the
  installer checks for it). Cases that run the installer: 3, 4, 6, 7, and the optional 8.

## Preparation (state-independent; repeat it to start over)

1. No Jarvis runtime running. Check (expect no output):

   `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'jarvis' -and $_.Name -match '^pythonw?\.exe$' } | Select-Object ProcessId, CommandLine`

   If the launcher shows up in that list, that is fine for Clean cases; for Copy cases
   its runtime must not be running (tooltip `... - waiting for a mode`).
2. Fresh test area and images (one block; recreated every time):

   ```powershell
   Remove-Item -Recurse -Force D:\AI\jarvis-brand3-tests -ErrorAction SilentlyContinue
   New-Item -ItemType Directory -Force D:\AI\jarvis-brand3-tests\pictures, D:\AI\jarvis-brand3-tests\shortcuts | Out-Null
   Add-Type -AssemblyName System.Drawing
   function New-TestPng($name, $w, $h) {
       $b = [Drawing.Bitmap]::new($w, $h, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
       $g = [Drawing.Graphics]::FromImage($b); $g.Clear([Drawing.Color]::Transparent)
       $g.FillEllipse([Drawing.Brushes]::OrangeRed, 2, 2, $w - 4, $h - 4)
       $g.FillRectangle([Drawing.Brushes]::RoyalBlue, 0, 0, [int]($w / 6), [int]($h / 6))
       $b.Save("D:\AI\jarvis-brand3-tests\pictures\$name", [Drawing.Imaging.ImageFormat]::Png)
       $g.Dispose(); $b.Dispose()
   }
   New-TestPng square.png 256 256; New-TestPng wide.png 300 150; New-TestPng tiny.png 32 32
   Set-Content D:\AI\jarvis-brand3-tests\pictures\notpng.png "this is text, not an image"
   ```

   `wide.png` is a 2:1 orange-red ellipse with a blue square at the top-left and
   transparent corners.

## Case 1: rejected input, nothing is written (instant)

State: Preparation (step 2) done, so `pictures\tiny.png` and `pictures\notpng.png`
exist and `pictures\missing.png` does not (it must stay absent). The destination
`D:\AI\jarvis-brand3-tests\bad` must NOT exist, otherwise the existing-destination
rejection replaces the lines below; the first command of the block removes it. Window:
fresh. Run each line; each must print exactly the shown `ERROR:` line (stderr) and set
exit code 1 (`$LASTEXITCODE`); afterwards `Test-Path D:\AI\jarvis-brand3-tests\bad` is
`False` (no destination was created). The texts come from `src\jarvis\core\config.py`
(`_brand_name`, `_brand_monogram`, `_brand_accent`), `src\jarvis\core\brand_icon.py`
(`validate_icon_file`) and `tools\deployment_brand.py` (`BrandRequest`).

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-brand3-tests\bad -ErrorAction SilentlyContinue
cd D:\AI\Jarvis
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\bad -Mode clean -Monogram AB
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\bad -Mode clean -Name 123456789012345678901234567890123
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\bad -Mode clean -Accent red
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\bad -Mode clean -Name '!Bang'
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\bad -Mode clean -DefaultBrand -Name W
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\bad -Mode clean -Icon x.png -NoIcon
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\bad -Mode clean -Icon D:\AI\jarvis-brand3-tests\pictures\tiny.png
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\bad -Mode clean -Icon D:\AI\jarvis-brand3-tests\pictures\notpng.png
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\bad -Mode clean -Icon D:\AI\jarvis-brand3-tests\pictures\missing.png
```

Expected `ERROR:` lines, in order:

```
ERROR: [brand].monogram must be exactly one Latin or Cyrillic letter or digit, got 'AB'
ERROR: [brand].name must be at most 32 characters, got 33
ERROR: [brand].accent must be a #RRGGBB colour, got 'red'
ERROR: [brand].monogram cannot be taken from [brand].name '!Bang': its first character is not a Latin or Cyrillic letter or digit; set the monogram explicitly
ERROR: -DefaultBrand cannot be combined with other brand options
ERROR: -Icon and -NoIcon cannot be combined
ERROR: [brand].icon "D:\AI\jarvis-brand3-tests\pictures\tiny.png": is 32x32; the shorter side must be at least 64 px
ERROR: [brand].icon "D:\AI\jarvis-brand3-tests\pictures\notpng.png": is not a PNG file (bad signature)
ERROR: [brand].icon "D:\AI\jarvis-brand3-tests\pictures\missing.png": file not found: D:\AI\jarvis-brand3-tests\pictures\missing.png
```

## Case 2: preview shows the resolved brand (instant)

State: no preparation needed (nothing here reads the pictures); the destination
`D:\AI\jarvis-brand3-tests\preview` must not exist (the first command of the block
removes it). Window: fresh. Each command prints the brand block and creates nothing
(`Test-Path D:\AI\jarvis-brand3-tests\preview` stays `False`). The defaults in the second
output are `DEFAULT_BRAND_NAME = "Jarvis"` (`src\jarvis\core\config.py` line 1011),
`DEFAULT_BRAND_MONOGRAM = "J"` (line 1012) and `DEFAULT_BRAND_ACCENT = "#3FE0D0"`
(line 1013):

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-brand3-tests\preview -ErrorAction SilentlyContinue
cd D:\AI\Jarvis
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\preview -Mode clean -Preview -Name Work -Monogram W -Accent "#E0A03F" | ForEach-Object { $_.Substring('JARVIS_DEPLOY_PREVIEW:'.Length) | ConvertFrom-Json } | Select-Object -ExpandProperty brand | Format-List
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\preview -Mode clean -Preview | ForEach-Object { $_.Substring('JARVIS_DEPLOY_PREVIEW:'.Length) | ConvertFrom-Json } | Select-Object -ExpandProperty brand | Format-List
```

Expected, first command (second: `name : Jarvis`, `monogram : J`, `accent : #3FE0D0`,
`is_default : True`, `origin : default`):

```
name       : Work
monogram   : W
accent     : #E0A03F
icon       :
is_default : False
origin     : requested
```

## Case 3: Clean home with a generated monogram (installer, minutes)

State: Preparation done; Jarvis may run or not. Window: fresh.

```powershell
cd D:\AI\Jarvis
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\work -Mode clean -Name Work -Monogram W -Accent "#E0A03F" -Yes
```

Expect the output to begin (the icon line comes BEFORE the installer starts, and the
home has no `.venv` at that moment):

```
Preparing application files in D:\AI\jarvis-brand3-tests\work
Generated brand icons in D:\AI\jarvis-brand3-tests\work\brand
Installing Jarvis in D:\AI\jarvis-brand3-tests\work
```

then the installer output, which contains `[skipped] Create config.toml (already present)`
and `[done] Load settings` and ends with `Installation complete.`; the very last line is
(backslashes are doubled, it is JSON):

```
JARVIS_DEPLOY_RESULT:{"target": "D:\\AI\\jarvis-brand3-tests\\work", "shortcut_file": "Work - work.lnk", "shortcut_icon": "D:\\AI\\jarvis-brand3-tests\\work\\brand\\brand.ico"}
```

Then, in the same window:

```powershell
Get-Content D:\AI\jarvis-brand3-tests\work\config.toml -Tail 5
Get-ChildItem D:\AI\jarvis-brand3-tests\work\brand | Select-Object -ExpandProperty Name
Test-Path D:\AI\jarvis-brand3-tests\work\brand-source
(Get-Content D:\AI\jarvis-brand3-tests\work\.jarvis-deployment.json | ConvertFrom-Json).phase
```

Expected: the `config.toml` tail is an empty line, then
`[brand]`, `name = "Work"`, `monogram = "W"`, `accent = "#E0A03F"` (the rest of the file
is `config.example.toml` unchanged); the folder lists `brand.ico` and `brand.png` only
(no `.render-*` folder); `Test-Path` prints `False`; the phase is `complete`.

Look at the files as the owner: open `D:\AI\jarvis-brand3-tests\work\brand\brand.png`
(512 px amber disc, graphite `W`, transparent corners). In Explorer, View > `Extra large
icons` for `brand.ico` shows the same disc; `Small icons` shows the 16 px frame.

## Case 4: Clean home with a user PNG (installer, minutes)

State: Preparation done. Window: fresh.

```powershell
cd D:\AI\Jarvis
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\work-png -Mode clean -Icon D:\AI\jarvis-brand3-tests\pictures\wide.png -Yes
Get-Content D:\AI\jarvis-brand3-tests\work-png\config.toml -Tail 3
(Get-FileHash D:\AI\jarvis-brand3-tests\pictures\wide.png).Hash -eq (Get-FileHash D:\AI\jarvis-brand3-tests\work-png\brand-source\icon.png).Hash
Get-ChildItem D:\AI\jarvis-brand3-tests\work-png\brand | Select-Object -ExpandProperty Name
```

Expected: the output has the same three leading lines as Case 3 (with `work-png`),
the tail is an empty line, `[brand]`, `icon = "brand-source/icon.png"`; the hash
comparison prints `True` (the PNG was copied by value, the original is untouched); the
`brand` folder lists `brand.ico` and `brand.png`. Open `brand\brand.png`: the 2:1
ellipse is centred, empty transparent bands above and below, the blue square at the
ellipse's top-left; not squeezed into a circle, not cropped. The name stays `Jarvis`.

## Case 5: names with quotes, `&`, `%` and Cyrillic arrive intact (instant)

State: the destination `D:\AI\jarvis-brand3-tests\preview` must not exist (the first
command of the block removes it); nothing else is needed. Window: fresh. Previews only:

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-brand3-tests\preview -ErrorAction SilentlyContinue
cd D:\AI\Jarvis
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\preview -Mode clean -Preview -Name 'Say \"hi\"' -Monogram S | ForEach-Object { $_.Substring('JARVIS_DEPLOY_PREVIEW:'.Length) | ConvertFrom-Json } | Select-Object -ExpandProperty brand | Format-List name, monogram
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\preview -Mode clean -Preview -Name 'Work: R&D?' -Monogram W | ForEach-Object { $_.Substring('JARVIS_DEPLOY_PREVIEW:'.Length) | ConvertFrom-Json } | Select-Object -ExpandProperty brand | Format-List name, monogram
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\preview -Mode clean -Preview -Name 50%` off -Monogram F | ForEach-Object { $_.Substring('JARVIS_DEPLOY_PREVIEW:'.Length) | ConvertFrom-Json } | Select-Object -ExpandProperty brand | Format-List name, monogram
```

Expected `name` values: `Say "hi"`, `Work: R&D?`, `50% off`. (The third command escapes
the space with a backtick instead of quotes.) A Cyrillic check: `-Name 'Работа'` (no
`-Monogram`) previews as `name : Работа`, `monogram : Р`.

## Case 6: wizard Copy of the Work home, shortcut name and icon (installer + UI)

State: Case 3 done; no Jarvis runtime running (Copy). Window: fresh.

1. `D:\AI\jarvis-brand3-tests\work\DeploymentWizard.cmd` (the wizard window may take a
   moment; no console window appears).
2. The `Source installation` line shows `D:\AI\jarvis-brand3-tests\work`. Choose `Copy
   current Jarvis`. Set `Destination folder` to `D:\AI\jarvis-brand3-tests\wizard-copy`
   (type it). Click `Review`: the page lists the source, the destination and the
   journal/memory snapshots (it does not show the brand: story task 4). Click `Deploy`;
   wait for the page `Jarvis is ready`.
3. Click `Create shortcut...`. The Save dialog's file name field must read
   `Work - wizard-copy.lnk` (not `Jarvis - wizard-copy.lnk`). Navigate to
   `D:\AI\jarvis-brand3-tests\shortcuts`, press Save. The status line reads
   `Saved shortcut: D:\AI\jarvis-brand3-tests\shortcuts\Work - wizard-copy.lnk`.
4. Close the wizard (`Close`). Do NOT click `Launch Jarvis`. Then:

   ```powershell
   $link = (New-Object -ComObject WScript.Shell).CreateShortcut('D:\AI\jarvis-brand3-tests\shortcuts\Work - wizard-copy.lnk')
   $link.TargetPath; $link.WorkingDirectory; $link.IconLocation
   Get-Content D:\AI\jarvis-brand3-tests\wizard-copy\config.toml -Tail 5
   Get-ChildItem D:\AI\jarvis-brand3-tests\wizard-copy\brand | Select-Object -ExpandProperty Name
   (Get-FileHash D:\AI\jarvis-brand3-tests\work\brand\brand.ico).Hash -eq (Get-FileHash D:\AI\jarvis-brand3-tests\wizard-copy\brand\brand.ico).Hash
   ```

   Expected, in order: `D:\AI\jarvis-brand3-tests\wizard-copy\Jarvis.cmd`,
   `D:\AI\jarvis-brand3-tests\wizard-copy`,
   `D:\AI\jarvis-brand3-tests\wizard-copy\brand\brand.ico,0`; the same `[brand]` tail
   as Case 3 (the table was copied unchanged); `brand.ico` and `brand.png`; `True` (the
   generated icon was copied by value, not regenerated).
5. In Explorer open `D:\AI\jarvis-brand3-tests\shortcuts`: the shortcut shows the amber
   `W` disc (Extra large and Small icons). Judgement call: is it recognisable next to a
   normal Jarvis shortcut?

## Case 7: CLI Copy overrides the brand and leaves the source alone (installer)

State: Case 3 done (`D:\AI\jarvis-brand3-tests\work` holds a finished deployment) and
`D:\AI\jarvis-brand3-tests\home` does not exist; no Jarvis runtime running (a Copy takes
the lock `MUTEX_NAME = "Local\\Jarvis.SingleInstance"` in
`src\jarvis\core\single_instance.py` line 18, and is refused while a runtime holds it).
Window: fresh. One block (the hash is taken before and after in the same window):

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-brand3-tests\home -ErrorAction SilentlyContinue
cd D:\AI\jarvis-brand3-tests\work
$before = (Get-FileHash .\config.toml).Hash
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\home -Mode copy -Name 'Work: R&D?' -Accent "#2060E0" -Yes
Get-Content D:\AI\jarvis-brand3-tests\home\config.toml -Tail 5
Get-ChildItem D:\AI\jarvis-brand3-tests\home\brand | Select-Object -ExpandProperty Name
$before -eq (Get-FileHash .\config.toml).Hash
(Get-FileHash D:\AI\jarvis-brand3-tests\work\brand\brand.ico).Hash -eq (Get-FileHash D:\AI\jarvis-brand3-tests\home\brand\brand.ico).Hash
```

(This runs the deploy tool of the Work home itself: a deployed home can deploy.)
Expected output start:

```
Preparing application files in D:\AI\jarvis-brand3-tests\home
Copying the Jarvis snapshot into D:\AI\jarvis-brand3-tests\home
Generated brand icons in D:\AI\jarvis-brand3-tests\home\brand
Installing Jarvis in D:\AI\jarvis-brand3-tests\home
```

and the last line `JARVIS_DEPLOY_RESULT:` with `"shortcut_file": "Work_ R&D_ - home.lnk"`
(`:` and `?` become `_`). Then: the config tail is an empty line, `[brand]`,
`name = "Work: R&D?"`, `monogram = "W"` (inherited), `accent = "#2060E0"`; the
`brand` folder lists `brand.ico` and `brand.png`; the first `True` says the source
`config.toml` is unchanged; the second line prints `False` (the override regenerated
the icon: a blue disc with a WHITE `W`, white because it contrasts better on dark
blue; open `home\brand\brand.png`).

Copy previews of the other overrides (instant; same state; window fresh; they create
nothing):

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-brand3-tests\home2 -ErrorAction SilentlyContinue
cd D:\AI\jarvis-brand3-tests\work
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\home2 -Mode copy -Preview -DefaultBrand | ForEach-Object { $_.Substring('JARVIS_DEPLOY_PREVIEW:'.Length) | ConvertFrom-Json } | Select-Object -ExpandProperty brand | Format-List
.\deploy.cmd -Target D:\AI\jarvis-brand3-tests\home2 -Mode copy -Preview | ForEach-Object { $_.Substring('JARVIS_DEPLOY_PREVIEW:'.Length) | ConvertFrom-Json } | Select-Object -ExpandProperty brand | Format-List
```

Expected: the first prints `name : Jarvis`, `monogram : J`, `accent : #3FE0D0`,
`is_default : True`, `origin : default`; the second `name : Work`, `monogram : W`,
`accent : #E0A03F`, `is_default : False`, `origin : inherited`.

## Case 8 (optional): wizard Copy of a hostile-named home

State: Case 7 done; no Jarvis runtime running. Window: fresh. Run
`D:\AI\jarvis-brand3-tests\home\DeploymentWizard.cmd`, `Copy current Jarvis`,
destination `D:\AI\jarvis-brand3-tests\wizard-home`, `Review`, `Deploy`,
`Create shortcut...`: the default file name must be `Work_ R&D_ - wizard-home.lnk`;
save it into `D:\AI\jarvis-brand3-tests\shortcuts`. The shortcut shows the blue disc
with a white `W`.

## Case 9 (optional): default brand regression in the wizard

State: no Jarvis runtime needed. Window: fresh. Run `D:\AI\Jarvis\DeploymentWizard.cmd`,
`Clean installation`, destination `D:\AI\jarvis-brand3-tests\plain`, `Review`,
`Deploy`, `Create shortcut...`: the default file name is exactly
`Jarvis - plain.lnk` (as before this change) and the shortcut has the packaged
Jarvis icon (dark tile, cyan mark). `Test-Path D:\AI\jarvis-brand3-tests\plain\brand`
prints `False` (a default brand generates nothing) and `Test-Path
D:\AI\jarvis-brand3-tests\plain\config.toml` prints `True` (the installer created it
from the example, as before).

## Not covered by hand (covered by the automated tests)

A failed icon stage and its `-Resume`, a stale or hand-placed `brand.ico` carried by
a faithful Copy, `-NoIcon`, comment preservation in `config.toml`, rejection of an
unsupported `[brand]` form, the shortcut-name sanitising table (device names, dots,
length). See `tests/test_brand_deployment.py`, `tests/test_deployment_brand.py`,
`tests/test_deployment_shortcut.py`, `tests/test_deployment_toml_brand.py` and
`tests/test_brand_deploy_cli.py`.

## Cleanup (state-independent)

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-brand3-tests -ErrorAction SilentlyContinue
```

(The deployed homes hold `.venv` folders; deleting them can take a minute.) Make sure
`D:\AI\Jarvis\config.toml` still has no `[brand]` block and that no `D:\AI\Jarvis\brand`
or `D:\AI\Jarvis\brand-source` folder appeared (this handoff never writes there).

## Report back

For each case: pass, or the exact difference (what you saw instead). Judgement calls
are yours: whether the shortcut names read well (`<name> - <folder>`), 16 px
legibility of the generated icons, whether copying a stale `brand\` should instead be
regenerated (the card's alternative), and the wait for the icon stage.
