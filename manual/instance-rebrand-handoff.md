# Instance branding, task 5: change the identity of an existing home (human handoff)

Human-run, per Testing protocol item 4 (`CLAUDE.md`). The wizard is a WPF window and
Case 9 runs the real installer, so the agent prepared this handoff and ran none of the
window cases. The agent did run:

- Preparation and Cases 1 to 6 in the test area below, and copied their output into this
  document (Windows PowerShell 5.1, the real icon renderer, no installer);
- the wizard controller (`tools\install\wizard.ps1`) with its window replaced by a driver,
  so no window was ever shown: it rebranded a scratch home end to end (third mode, home
  check, review text, `Apply`, finish text, shortcut name and icon) and refused a home that
  predates branding. The page titles and texts quoted below are what that driver printed.

What no agent run has seen: the window's look, the folder dialog, the shortcut file, the
real tray and the real installer.
Card: `tasks/done/task-instance-rebrand-existing-home.md`.

What it answers: a home that is already deployed can get a new name, letter, accent colour
or PNG without a new folder; the rules and messages are the deployment's own; a refused
request leaves the home byte-identical; the wizard and the command do the same thing.

Documentation: `README.md` and `README.ru.md` (section "Give an installation its own
identity", paragraph "Change it later, in place") describe `-Rebrand` and the third wizard
mode. They deliberately do not describe `-Rebrand -CheckBrand`, the read-only check the
wizard runs while you type; it is documented in this handoff and in `PROJECT.md` (section
"Architecture: instance branding", part "Rebrand an existing home"). Everything a case
relies on is named here with its source.

## Names and fixed paths

- Repository = `D:\AI\Jarvis` (holds `deploy.cmd`, `DeploymentWizard.cmd`). If yours is
  elsewhere, replace the prefix everywhere. Nothing in Cases 1 to 8 writes into it.
- Test area = `D:\AI\jarvis-rebrand-tests` (outside the repository). The scratch homes in it
  are NOT deployed Jarvis installations: each holds only `config.toml`, a journal file and
  `src\jarvis\core\brand.py` (the one file the rebrand tool checks, see below). The tool runs
  the repository's code, so the scratch homes need nothing else.
- Commands run in a fresh Windows PowerShell 5.1 window (`powershell.exe`).
- What makes a home eligible (source: `tools\deployment_rebrand.py`, `_eligible_home`): the
  folder exists, has `config.toml`, and has `src\jarvis\core\brand.py`. A home without that
  file predates branding: its Jarvis rejects an unknown `[brand]` section.
- The command: `deploy.cmd -Rebrand -Target <home>` plus any of `-Name`, `-Monogram`,
  `-Accent`, `-Icon <png>`, `-NoIcon`, `-DefaultBrand` (source: `tools\install\deploy.ps1`,
  parameter set `Rebrand`; no `-Mode`, `-Resume`, `-Yes`, `-Preview`; it never installs
  Python). `-Rebrand -Target <home> -CheckBrand` is the read-only check of the same request.
  Both print one `JARVIS_DEPLOY_REBRAND:{...}` or `JARVIS_DEPLOY_BRAND_CHECK:{...}` line; a
  rejected request is an answer (exit code 0).
- The wizard: run `D:\AI\Jarvis\DeploymentWizard.cmd` (source: that file; it starts
  `tools\install\wizard_start.ps1` with a hidden console). Controls are named as the window
  shows them (source `tools\install\wizard.xaml`): first page radio `Change the identity of
  an existing home` line 50, label `Jarvis home folder` (shown instead of `Destination
  folder`, line 52, Alt+`J`), text box line 56, `Browse...` line 55; Identity page as in
  task 4 (`Name` line 77, `Choose PNG...` 105, `Remove PNG` 106, `Restore default identity`
  110, `Discard changes` 112, preview `PreviewLarge` 120); bottom buttons `Back`, the primary
  button, `Close` (lines 173-175). The primary button is the default button: Enter in a
  text box presses it. It disappears (is not greyed) when it cannot be used.
- Page titles in this mode (source: `tools\install\wizard_pages.ps1`): `Change identity`
  (first page and Identity page), `Review identity change`, `Changing identity`,
  `Identity changed`, `The identity was not changed`. Primary button: `Customize identity`,
  then `Review`, then `Apply`.
- Running state: nothing here needs Jarvis stopped. Never start Jarvis from a scratch home.
  Case 9 (optional) starts the tray launcher only.
- Time: Cases 1 to 6 take about a minute together. Case 9 runs the installer (several
  minutes, network and Ollama installed); skip it if you do not need the tray check.

## Preparation (state-independent; repeat it to start over)

Fresh test area, pictures and scratch homes (one block; recreated every time). `work` has a
brand and other settings, `plain` has none, `old` lacks the branding file, `uilayer` has a
`[brand]` in `config.ui.toml`:

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-rebrand-tests -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force D:\AI\jarvis-rebrand-tests\pictures | Out-Null
Add-Type -AssemblyName System.Drawing
function New-TestPng($name, $w, $h) {
    $b = [Drawing.Bitmap]::new($w, $h, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [Drawing.Graphics]::FromImage($b); $g.Clear([Drawing.Color]::Transparent)
    $g.FillEllipse([Drawing.Brushes]::OrangeRed, 2, 2, $w - 4, $h - 4)
    $g.FillRectangle([Drawing.Brushes]::RoyalBlue, 0, 0, [int]($w / 6), [int]($h / 6))
    $b.Save("D:\AI\jarvis-rebrand-tests\pictures\$name", [Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $b.Dispose()
}
New-TestPng square.png 256 256; New-TestPng wide.png 300 150; New-TestPng tiny.png 32 32
Set-Content D:\AI\jarvis-rebrand-tests\pictures\notpng.png "this is text, not an image"
function New-TestHome($name, $config) {
    $path = "D:\AI\jarvis-rebrand-tests\$name"
    New-Item -ItemType Directory -Force "$path\src\jarvis\core", "$path\journal" | Out-Null
    Copy-Item D:\AI\Jarvis\src\jarvis\core\brand.py "$path\src\jarvis\core\brand.py"
    Set-Content "$path\journal\today.jsonl" 'a journal line that must never change'
    [IO.File]::WriteAllText("$path\config.toml", $config, [Text.UTF8Encoding]::new($false))
}
$work = @'
# my settings
[ui]
language = 'en'

[brand]
name = "Work"
monogram = "W"
accent = "#E0A03F"

[tts]
enabled = true
'@
New-TestHome work $work
New-TestHome plain "[ui]`nlanguage = 'en'`n"
New-TestHome old $work
Remove-Item D:\AI\jarvis-rebrand-tests\old\src\jarvis\core\brand.py
New-TestHome uilayer $work
[IO.File]::WriteAllText('D:\AI\jarvis-rebrand-tests\uilayer\config.ui.toml', "[brand]`nname = `"Ui`"`n", [Text.UTF8Encoding]::new($false))
```

(The file is written without a byte-order mark on purpose: the TOML reader rejects one.)

Helpers for Cases 1 to 6 (define them once per window; `Show-Answer` turns the one JSON line
into one readable line, `Get-HomeState` lists every file of a scratch home with the first ten
characters of its SHA-256):

```powershell
function Show-Answer {
    process {
        foreach ($prefix in 'JARVIS_DEPLOY_REBRAND:', 'JARVIS_DEPLOY_BRAND_CHECK:') {
            if ($_.StartsWith($prefix)) {
                $a = $_.Substring($prefix.Length) | ConvertFrom-Json
                if ($a.ok) {
                    $files = if ($a.files) { ' files=' + ($a.files -join ',') } else { '' }
                    "ok=True name=$($a.brand.name) monogram=$($a.brand.monogram) accent=$($a.brand.accent) origin=$($a.brand.origin) icon=$($a.brand.icon)$files"
                } else { "ok=False message=$($a.message)" }
                return
            }
        }
        "(other output) $_"
    }
}
function Get-HomeState($name) {
    $root = "D:\AI\jarvis-rebrand-tests\$name"
    Get-ChildItem $root -Recurse -File | Sort-Object FullName | ForEach-Object {
        '{0}  {1}' -f $_.FullName.Substring($root.Length + 1), (Get-FileHash $_.FullName -Algorithm SHA256).Hash.Substring(0, 10)
    }
}
$t = 'D:\AI\jarvis-rebrand-tests'
cd D:\AI\Jarvis
```

Cases 1 to 6 are a sequence on the home `work`: run them in order after the Preparation, or
start over.

## Case 1: the check answers for a home (instant, writes nothing)

`-CheckBrand` with `-Rebrand` is what the wizard's Identity page asks while you type; the
home is the source of the stored brand.

```powershell
.\deploy.cmd -Rebrand -Target $t\work -CheckBrand | Show-Answer
.\deploy.cmd -Rebrand -Target $t\work -CheckBrand -Name Lab -Accent "#112233" | Show-Answer
.\deploy.cmd -Rebrand -Target $t\work -CheckBrand -Accent red | Show-Answer
.\deploy.cmd -Rebrand -Target $t\plain -CheckBrand | Show-Answer
.\deploy.cmd -Rebrand -Target $t\old -CheckBrand | Show-Answer
.\deploy.cmd -Rebrand -Target $t\uilayer -CheckBrand | Show-Answer
.\deploy.cmd -Rebrand -Target $t\nowhere -CheckBrand | Show-Answer
Get-HomeState work
```

Expected (the exit code of every command is 0):

```
ok=True name=Work monogram=W accent=#E0A03F origin=inherited icon=
ok=True name=Lab monogram=W accent=#112233 origin=requested icon=
ok=False message=[brand].accent must be a #RRGGBB colour, got 'red'
ok=True name=Jarvis monogram=J accent=#3FE0D0 origin=default icon=
ok=False message=D:\AI\jarvis-rebrand-tests\old predates instance branding (src\jarvis\core\brand.py is missing); update this home first, because its Jarvis would not read [brand]
ok=False message=[brand] (D:\AI\jarvis-rebrand-tests\uilayer\config.ui.toml) belongs in config.toml: the Settings form rewrites this file and would drop it
ok=False message=The Jarvis home does not exist: D:\AI\jarvis-rebrand-tests\nowhere
config.toml  0EF3F9A2E9
journal\today.jsonl  B6F6A6B305
src\jarvis\core\brand.py  D21402A625
```

Severity if it differs: a wrong `ok=True` is the dangerous kind (a home that would break is
offered for a change); a different message text is only noise.

## Case 2: rename and recolour (real icons)

```powershell
.\deploy.cmd -Rebrand -Target $t\work -Name Lab -Accent "#112233" | Show-Answer
Get-HomeState work
Get-Content $t\work\config.toml
```

Expected: the answer lists the three files; `config.toml` changes, `brand\brand.png` and
`brand\brand.ico` appear, `journal\today.jsonl` and `src\jarvis\core\brand.py` keep their
hashes; the comment, the other tables and their order are untouched:

```
ok=True name=Lab monogram=W accent=#112233 origin=requested icon= files=config.toml,brand/brand.png,brand/brand.ico
brand\brand.ico  753453E194
brand\brand.png  BE7787E4A1
config.toml  7890AB03B9
journal\today.jsonl  B6F6A6B305
src\jarvis\core\brand.py  D21402A625
# my settings
[ui]
language = 'en'

[brand]
name = "Lab"
monogram = "W"
accent = "#112233"

[tts]
enabled = true
```

The icon hashes depend on the renderer and may differ on another Windows build; compare the
rest. Open `D:\AI\jarvis-rebrand-tests\work\brand\brand.png`: a dark-blue disc with a white
`W` (white because it contrasts with `#112233`).

## Case 3: a new PNG, the same file again, then remove it

```powershell
.\deploy.cmd -Rebrand -Target $t\work -Icon $t\pictures\wide.png | Show-Answer
Get-HomeState work
.\deploy.cmd -Rebrand -Target $t\work -Icon $t\work\brand-source\icon.png | Show-Answer
.\deploy.cmd -Rebrand -Target $t\work -NoIcon | Show-Answer
Get-HomeState work
```

Expected: the first answer lists `brand-source/icon.png`, `config.toml` and the two icons, and
`config.toml` gains `icon = "brand-source/icon.png"` in `[brand]`; choosing the home's own
`brand-source\icon.png` again works and lists only the two icons (it is not copied onto
itself); `-NoIcon` removes the key, regenerates the monogram icons and leaves
`brand-source\icon.png` in place (the final listing has the Case 2 hashes plus
`brand-source\icon.png  A96579F185`):

```
ok=True name=Lab monogram=W accent=#112233 origin=requested icon=brand-source/icon.png files=brand-source/icon.png,config.toml,brand/brand.png,brand/brand.ico
ok=True name=Lab monogram=W accent=#112233 origin=requested icon=brand-source/icon.png files=brand/brand.png,brand/brand.ico
ok=True name=Lab monogram=W accent=#112233 origin=requested icon= files=config.toml,brand/brand.png,brand/brand.ico
```

Open `brand\brand.png` after the first command: the orange-red ellipse with the blue square,
centred (the 2:1 image is fitted inside the square).

## Case 4: back to the default identity

```powershell
.\deploy.cmd -Rebrand -Target $t\work -DefaultBrand | Show-Answer
Get-HomeState work
Get-Content $t\work\config.toml
```

Expected: the `[brand]` table is gone (the other tables stay), nothing is rendered, nothing
is deleted: `brand\` and `brand-source\` stay and the journal hash is unchanged; the launcher
ignores a stale `brand\` for a default brand.

```
ok=True name=Jarvis monogram=J accent=#3FE0D0 origin=default icon= files=config.toml
```

## Case 5: a refused request leaves the home byte-identical

```powershell
$before = Get-HomeState plain
.\deploy.cmd -Rebrand -Target $t\plain -Accent red | Show-Answer
.\deploy.cmd -Rebrand -Target $t\plain -Name Lab -Icon $t\pictures\tiny.png | Show-Answer
.\deploy.cmd -Rebrand -Target $t\plain -Icon $t\pictures\notpng.png | Show-Answer
.\deploy.cmd -Rebrand -Target $t\plain | Show-Answer
.\deploy.cmd -Rebrand -Target $t\plain -DefaultBrand -Name Lab | Show-Answer
'same state: ' + (-not (Compare-Object $before (Get-HomeState plain)))
```

Expected (the messages are the planner's own; the `Nothing to change` line also names the
way to rebuild icons alone):

```
ok=False message=[brand].accent must be a #RRGGBB colour, got 'red'
ok=False message=[brand].icon "D:\AI\jarvis-rebrand-tests\pictures\tiny.png": is 32x32; the shorter side must be at least 64 px
ok=False message=[brand].icon "D:\AI\jarvis-rebrand-tests\pictures\notpng.png": is not a PNG file (bad signature)
ok=False message=Nothing to change: give at least one of -Name, -Monogram, -Accent, -Icon, -NoIcon or -DefaultBrand. To rebuild the icons from the current [brand], use Regenerate icons in the launcher Settings or python -m jarvis.core.brand_render --home <home>
ok=False message=-DefaultBrand cannot be combined with other brand options
same state: True
```

Severity if `same state` is False: serious (a refused request changed the home).

## Case 6: homes that cannot be rebranded, and a home without a brand

```powershell
.\deploy.cmd -Rebrand -Target $t\old -Name Lab | Show-Answer
.\deploy.cmd -Rebrand -Target $t\uilayer -Name Lab | Show-Answer
.\deploy.cmd -Rebrand -Target $t\nowhere -Name Lab | Show-Answer
.\deploy.cmd -Rebrand -Target $t\plain -Name Lab -Yes
.\deploy.cmd -Rebrand -Target $t\plain -Name Lab | Show-Answer
Get-Content $t\plain\config.toml
```

Expected: the first three answers are the Case 1 messages for `old`, `uilayer` and `nowhere`;
the fourth command fails with `Parameter set cannot be resolved using the specified named
parameters.` (`-Yes` does not exist in this mode); the fifth gives the `plain` home a brand
(its letter is derived from the name) and appends the table:

```
ok=True name=Lab monogram=L accent=#3FE0D0 origin=requested icon= files=config.toml,brand/brand.png,brand/brand.ico
[ui]
language = 'en'

[brand]
name = "Lab"
```

## Case 7: the wizard, third mode (window)

State: Preparation done and Cases 1 to 6 run (so `work` has the default identity and `plain`
is `Lab`), or run only the Preparation: either is fine, the steps say what to expect.
Run `D:\AI\Jarvis\DeploymentWizard.cmd`.

1. First page. Click the radio `Change the identity of an existing home`. Expect: the title
   becomes `Change identity`; the label above the text box reads `Jarvis home folder`; the
   button beside it reads `Browse...`; the text box now holds `D:\AI\Jarvis` (the folder the
   wizard runs from, `$source` in `tools\install\wizard.ps1`) - do not use it; the Python
   consent checkbox, the `Customize identity...` button and the `Identity:` line disappear;
   the primary button reads `Customize identity`. Click `Clean installation`: everything
   returns (and the text box returns to `D:\AI\Jarvis-new`); click the rebrand radio again.
2. Replace the text with `D:\AI\jarvis-rebrand-tests\work` and press Enter. Expect the page
   `Change identity` with the Identity form; for a moment `Reading the current identity...`;
   then the name and accent boxes hold the home's values (after Cases 1 to 6: `Jarvis` and
   `#3FE0D0`; right after the Preparation: `Work` and `#E0A03F`). The primary button is
   absent and the status line reads `Change at least one value to continue.`
3. Type `Studio` in `Name`. Within about a second the preview follows; the primary button
   `Review` appears. Choose `Review`. Expect the page `Review identity change` with exactly:

   ```
   Change the identity of an existing Jarvis home.
   Home: D:\AI\jarvis-rebrand-tests\work

   Identity: Studio (changed)
   Monogram: S on #3FE0D0

   Files that will change:
     config.toml: the [brand] section
     brand\brand.png and brand\brand.ico: regenerated

   Everything else in the home stays as it is.
   ```

   (after Cases 1 to 6 the home has the default identity, so the letter comes from the name:
   `Monogram: S on #3FE0D0`; after only the Preparation the stored letter and accent stay:
   `Monogram: W on #E0A03F`). The primary button reads `Apply`.
4. `Back` returns to the Identity page with `Studio` still typed; `Review` again; `Apply`.
   Expect `Changing identity`, then `Identity changed` with the output text:

   ```
   The identity of this home was changed.
   Written: config.toml, brand/brand.png, brand/brand.ico

   The Status Console and window titles change when Jarvis starts next.
   The tray name and icon change at the next mode start from the tray, or after Regenerate icons.
   A shortcut you saved earlier keeps its name; save a new one to get the new name and icon.
   ```

   The buttons are `Open folder` and `Create shortcut...`; there is no `Launch Jarvis`.
5. `Create shortcut...`: the suggested file name is `Studio - work.lnk`. Save it into
   `D:\AI\jarvis-rebrand-tests` (not the Desktop). In Explorer its icon is the new `S` disc
   (Explorer may need a refresh, F5, to drop a cached icon); its properties show the target
   `D:\AI\jarvis-rebrand-tests\work\Jarvis.cmd` (the file does not exist in a scratch home; do
   not double-click the shortcut) and the icon file `...\work\brand\brand.ico`.
6. Check on disk (a new window is fine): `Get-Content D:\AI\jarvis-rebrand-tests\work\config.toml`
   shows `name = "Studio"` and the comment, `[ui]` and `[tts]` tables unchanged; the journal
   hash is unchanged (`Get-HomeState work`, after defining the Preparation helpers).

## Case 8: the wizard refuses and resets (window)

State: Preparation done; wizard window fresh.

1. Rebrand radio, text `D:\AI\jarvis-rebrand-tests\old`, Enter. Expect the Identity page with
   the red message line from Case 1 (`... predates instance branding ... update this home
   first ...`) and no primary button; `Back` returns to the first page.
2. `Back`, text `D:\AI\jarvis-rebrand-tests\nowhere`, Enter: the message `The Jarvis home does
   not exist: ...`. `Back`, clear the text box and press Enter: the status line says `Choose
   the Jarvis home folder.` and the first page stays.
3. Text `D:\AI\jarvis-rebrand-tests\work`, Enter, type `Temp` in `Name`, then `Discard
   changes`: the name returns to the home's value and the primary button disappears again.
   Type `Temp` again and `Back`; click `Clean installation`: the status line says `Identity
   changes were discarded because the mode changed.`
4. Rebrand radio, the same `work` text, Enter: the Identity page opens with the stored
   values (the earlier `Temp` is gone). Type `accent` text `red`: the accent message appears
   next to the box and the primary button disappears; fix it to `#112233`: the button
   returns. Close the window.

## Case 9 (optional, runs the installer): the tray and a real home

Skip this unless you want to see the tray. It needs network and Ollama installed and takes
several minutes. It creates one real home with the repository's installer.

```powershell
cd D:\AI\Jarvis
.\deploy.cmd -Target D:\AI\jarvis-rebrand-tests\real -Yes
```

Wait for it to finish (exit code 0). Then run the wizard, choose the rebrand radio, text
`D:\AI\jarvis-rebrand-tests\real`, Enter, `Name` = `Studio`, `Review`, `Apply`. Then start
the tray launcher from the repository you normally use, open its Settings, set `Jarvis Home
Folder` to `D:\AI\jarvis-rebrand-tests\real`, `Save folder`. Expect: the tray tooltip names
`Studio` (the launcher reloads its identity after a home change, `PROJECT.md`, Windows tray
launcher section) and the tray icon is the `S` disc. Changing the name again through the
wizard changes the tray at the next mode start from the tray, or at once through
`Regenerate icons` in Settings. Do not start Assistant or MCP mode from this home.

## Cleanup

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-rebrand-tests -ErrorAction SilentlyContinue
```

Delete any `.lnk` you saved outside the test area.

## Report back

For every case: pass or the deviation as expected / actual, plus whether it accepted
something that had to be refused, refused something that had to be accepted, or is only
noise (a message wording or a visual detail).
