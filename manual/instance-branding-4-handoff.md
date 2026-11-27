# Instance branding, task 4: wizard Identity step (human handoff)

Human-run, per Testing protocol item 4 (`CLAUDE.md`). The Identity step is a WPF
window, and two cases run the real installer (`pip install`, minutes), so the agent
prepared this handoff and ran none of the window or installer cases. The agent did run:

- the instant commands of Case 1 and the preparation blocks of Cases 9 and 10, in a
  scratch folder, and copied their output below;
- a fake-installer deployment of the real repository (Clean, `Work`, `W`, `#E0A03F`) to
  read the real `config.toml` tail and `brand\` file list used in Case 6;
- the wizard controller (`tools\install\wizard.ps1`) with its window replaced by a
  driver, so no window was ever shown: the texts of the Customize page, of the
  Review page and of the unavailable state quoted below are what that driver printed.

What no agent run has seen: the window's look, typing, the file and colour dialogs, the
real installer, and the real shortcut.
Card: `tasks/done/task-instance-branding-4-wizard-identity-step.md`.

What it answers: the wizard has an optional `Customize identity...` page with a live
preview; it validates with the same rules as `deploy.cmd` (it calls the same code); the
preview matches the icon the deployment generates; an untouched wizard deploys exactly as
before; the identity the owner chose is what the deployed home gets.

Documentation: `README.md` and `README.ru.md` (section "Give an installation its own
identity") describe the Identity step and the brand options. They deliberately do not
describe `-CheckBrand`, the read-only check the wizard runs while you type; it is
documented in this handoff and in `PROJECT.md` (sections "Architecture: instance
branding" and "Wizard Identity step"). Everything a case relies on is named here with its
source.

## Names and fixed paths

- Repository = `D:\AI\Jarvis` (holds `deploy.cmd`, `DeploymentWizard.cmd`,
  `config.example.toml`). If yours is elsewhere, replace the prefix everywhere.
- Test area = `D:\AI\jarvis-brand4-tests` (outside the repository). Every destination is
  a new folder in it. Nothing in this handoff writes into `D:\AI\Jarvis`.
- Commands run in a fresh Windows PowerShell 5.1 window (`powershell.exe`); every block
  starts with its own `cd` and defines what it uses.
- The wizard: double-click or run `D:\AI\Jarvis\DeploymentWizard.cmd` (source: that file;
  it starts `tools\install\wizard_start.ps1` with a hidden console, so no console window
  appears). A home started from its own folder uses its own `DeploymentWizard.cmd`.
- Controls are named below exactly as the window shows them. Source: `tools\install\wizard.xaml`,
  first page `Customize identity...` line 61; Identity page `Name` line 73, `Monogram
  letter` line 78, `Accent colour` line 85, `Pick colour...` line 95, `Icon image
  (optional PNG)` line 98, `Choose PNG...` line 103, `Remove PNG` line 104, `Restore
  default identity` line 109, `Discard changes` line 110; the preview is the right
  column (`PreviewLarge` line 118, caption line 122); the bottom buttons are `Back`,
  `Review`, `Close` (lines 171-173). The `Review` button disappears (it is not greyed)
  whenever it cannot be used. The access keys are the underlined letters: Alt plus
  `U` (`Customize identity...`), `N`, `M`, `A`, `P`, `I`, `H`, `R`, `C`, `G` on the
  Identity page, `D` (`Destination folder`).
- Page titles (`tools\install\wizard_pages.ps1`): `Deploy Jarvis` (first page),
  `Customize identity`, `Review deployment`, `Checking deployment`, `Deploying Jarvis`,
  `Installation needs attention`, `Deployment could not continue`, `Jarvis is ready`.
- Running state. The wizard window itself needs no Jarvis runtime and never starts one;
  the identity check takes no lock, so the Identity page works while Jarvis runs. A Copy
  `Review` or `Deploy` takes the runtime lock `Local\Jarvis.SingleInstance` (`MUTEX_NAME`,
  `src\jarvis\core\single_instance.py` line 18) and is refused while a Jarvis runtime
  (Assistant or MCP mode, started by anything) is alive: stop it first for Cases 7 and 8.
  Clean cases do not care. The tray launcher may stay running idle. Never start Jarvis
  from a test home and never click `Launch Jarvis`.
- Time: the cases that run the installer are 6, 7 (its first part) and the optional 8;
  each takes several minutes (creates a `.venv`, runs `pip install -r requirements.txt`)
  and needs network and Ollama installed. Cases 1 to 5, 7 (Review parts), 9, 10 and 11
  do not run the installer; do not click `Deploy` or `Resume installation` in them.
- Files written: PNG images, scratch copies and shortcuts only. No `config.toml` is
  written by hand (a PowerShell 5.1 `-Encoding UTF8` file carries a BOM that the TOML
  reader rejects); `config.toml` files are only read.

## Preparation (state-independent; repeat it to start over)

1. No Jarvis runtime running (needed from Case 7 on). Check (expect no output):

   `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'jarvis' -and $_.Name -match '^pythonw?\.exe$' } | Select-Object ProcessId, CommandLine`

2. Fresh test area and images (one block; recreated every time):

   ```powershell
   Remove-Item -Recurse -Force D:\AI\jarvis-brand4-tests -ErrorAction SilentlyContinue
   New-Item -ItemType Directory -Force D:\AI\jarvis-brand4-tests\pictures, D:\AI\jarvis-brand4-tests\shortcuts | Out-Null
   Add-Type -AssemblyName System.Drawing
   function New-TestPng($name, $w, $h) {
       $b = [Drawing.Bitmap]::new($w, $h, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
       $g = [Drawing.Graphics]::FromImage($b); $g.Clear([Drawing.Color]::Transparent)
       $g.FillEllipse([Drawing.Brushes]::OrangeRed, 2, 2, $w - 4, $h - 4)
       $g.FillRectangle([Drawing.Brushes]::RoyalBlue, 0, 0, [int]($w / 6), [int]($h / 6))
       $b.Save("D:\AI\jarvis-brand4-tests\pictures\$name", [Drawing.Imaging.ImageFormat]::Png)
       $g.Dispose(); $b.Dispose()
   }
   New-TestPng square.png 256 256; New-TestPng wide.png 300 150; New-TestPng tiny.png 32 32; New-TestPng sliver.png 600 100
   Set-Content D:\AI\jarvis-brand4-tests\pictures\notpng.png "this is text, not an image"
   [IO.File]::WriteAllBytes('D:\AI\jarvis-brand4-tests\pictures\truncated.png', [byte[]][IO.File]::ReadAllBytes('D:\AI\jarvis-brand4-tests\pictures\wide.png')[0..199])
   ```

   `wide.png` is a 2:1 orange-red ellipse with a blue square at its top-left and
   transparent corners. `missing.png` must stay absent.

## Case 1: the shared check answers like the wizard sees it (instant)

State: Preparation step 2 done. Window: fresh. `deploy.cmd -CheckBrand` is the read-only
check the Identity page runs while you type (source: `tools\install\deploy.ps1`,
parameter set `CheckBrand`; it has no `-Target`, writes nothing, takes no lock and never
installs Python). It prints one `JARVIS_DEPLOY_BRAND_CHECK:{...}` line; the block turns
it into one readable line. The messages are the planner's own (`src\jarvis\core\config.py`
`_brand_name`, `_brand_monogram`, `_brand_accent`; `src\jarvis\core\brand_icon.py`
`validate_icon_file`; `tools\deployment_brand.py`).

```powershell
cd D:\AI\Jarvis
function Show-Check {
    process {
        $a = $_.Substring('JARVIS_DEPLOY_BRAND_CHECK:'.Length) | ConvertFrom-Json
        if ($a.ok) {
            "ok=True name=$($a.brand.name) monogram=$($a.brand.monogram) accent=$($a.brand.accent) origin=$($a.brand.origin) icon=$($a.brand.icon) kind=$($a.icon_preview.kind)"
        } else {
            "ok=False field=$($a.field) message=$($a.message)"
        }
    }
}
.\deploy.cmd -CheckBrand -Mode clean | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Name Work -Accent "#E0A03F" | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Accent red | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Monogram AB | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Name 123456789012345678901234567890123 | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Name '!Bang' | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Name ('Bad' + [char]0x202E + 'name') | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Icon D:\AI\jarvis-brand4-tests\pictures\wide.png | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Icon D:\AI\jarvis-brand4-tests\pictures\tiny.png | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Icon D:\AI\jarvis-brand4-tests\pictures\notpng.png | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Icon D:\AI\jarvis-brand4-tests\pictures\missing.png | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Icon D:\AI\jarvis-brand4-tests\pictures\sliver.png | Show-Check
.\deploy.cmd -CheckBrand -Mode clean -Icon D:\AI\jarvis-brand4-tests\pictures\truncated.png | Show-Check
```

Expected, in order (the exit code of every command is 0: a rejected request is an answer,
not a failure):

```
ok=True name=Jarvis monogram=J accent=#3FE0D0 origin=default icon= kind=packaged
ok=True name=Work monogram=W accent=#E0A03F origin=requested icon= kind=monogram
ok=False field=accent message=[brand].accent must be a #RRGGBB colour, got 'red'
ok=False field=monogram message=[brand].monogram must be exactly one Latin or Cyrillic letter or digit, got 'AB'
ok=False field=name message=[brand].name must be at most 32 characters, got 33
ok=False field=monogram message=[brand].monogram cannot be taken from [brand].name '!Bang': its first character is not a Latin or Cyrillic letter or digit; set the monogram explicitly
ok=False field=name message=[brand].name must not contain control, invisible or non-space separator characters, got '\u202e'
ok=True name=Jarvis monogram=J accent=#3FE0D0 origin=requested icon=brand-source/icon.png kind=image
ok=False field=icon message=[brand].icon "D:\AI\jarvis-brand4-tests\pictures\tiny.png": is 32x32; the shorter side must be at least 64 px
ok=False field=icon message=[brand].icon "D:\AI\jarvis-brand4-tests\pictures\notpng.png": is not a PNG file (bad signature)
ok=False field=icon message=[brand].icon "D:\AI\jarvis-brand4-tests\pictures\missing.png": file not found: D:\AI\jarvis-brand4-tests\pictures\missing.png
ok=False field=icon message=[brand].icon "D:\AI\jarvis-brand4-tests\pictures\sliver.png": is 600x100; it must be at most twice as wide as high (or the reverse)
ok=False field=icon message=[brand].icon "D:\AI\jarvis-brand4-tests\pictures\truncated.png": is truncated or corrupt (IDAT chunk is cut short)
```

The `field` is what the Identity page uses to put each message next to its field in
Cases 4 and 5.

## Case 2: the default path is unchanged (UI, no installer)

State: Preparation done; Jarvis may run or not. Window: any.

1. Start `D:\AI\Jarvis\DeploymentWizard.cmd`. First page, title `Deploy Jarvis`. The
   `Source installation` line reads `D:\AI\Jarvis`; `Clean installation` is selected.
   Under the `Allow installing Python 3.11 through winget if needed` check box (leave it
   as it is) one line reads `Identity: default`, with the button `Customize identity...`
   on its right.
2. Type `D:\AI\jarvis-brand4-tests\plain` into `Destination folder`. Click `Review`
   (do not click `Customize identity...`). The page `Review deployment` shows exactly
   these lines (no identity line at all; the button reads `Deploy`, do NOT click it):

   ```
   Source: D:\AI\Jarvis
   Destination: D:\AI\jarvis-brand4-tests\plain

   Default settings, empty journal and empty memory.

   New journal: D:\AI\jarvis-brand4-tests\plain\journal
   New memory: D:\AI\jarvis-brand4-tests\plain\memory
   ```

3. Click `Back`: the first page again (the Identity page was never visited). Close the
   wizard (`Close`). `Test-Path D:\AI\jarvis-brand4-tests\plain` prints `False`.

## Case 3: Customize identity in a Clean installation (UI, no installer)

State: Preparation done. Window: fresh wizard from `D:\AI\Jarvis\DeploymentWizard.cmd`,
`Clean installation`, `Destination folder` `D:\AI\jarvis-brand4-tests\plain`.

1. Click `Customize identity...`. Title `Customize identity`. For a moment the fields
   are disabled and the status line says `Reading the current identity...`; then
   `Name` = `Jarvis`, `Accent colour` = `#3FE0D0`, `Monogram letter` empty with the hint
   `Empty keeps the current letter: J`, `Icon image (optional PNG)` = `No PNG: a generated
   monogram is used`, the caption under the large preview `The standard Jarvis icon`, and
   `Review` is visible. Keyboard focus is in `Name`.
2. Type `Work` into `Name` (select the old text first or press Alt+N then `Ctrl+A`). At
   once the status line says `Updating...`, the old picture dims and `Review` disappears;
   about a second after you stop typing the hint becomes `Empty keeps the current letter: W`,
   the caption reads `Generated monogram W on accent #3FE0D0`, and the preview shows a
   cyan disc with a dark `W`: large (96 px) and in the four small squares (32 and 16 px on
   a dark and on a light strip). `Review` is back.
3. Replace the `Accent colour` text with `#E0A03F`: caption `Generated monogram W on accent
   #E0A03F`, amber disc, dark `W`. Click `Pick colour...`, choose any colour in the Windows
   colour dialog, confirm: the box now holds that colour as `#RRGGBB` and the preview
   follows. Type `#E0A03F` again.
4. Type `Д` into `Monogram letter` (or paste it; it is a Cyrillic letter): the caption
   reads `Generated monogram Д on accent #E0A03F`, the disc shows `Д`. Empty the box again
   (the hint returns).
5. Typing latency and process count. In a SECOND PowerShell window run (about 15 seconds):

   ```powershell
   1..60 | ForEach-Object { @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*wizard_job.ps1*' }).Count; Start-Sleep -Milliseconds 250 } | Sort-Object -Unique
   ```

   and meanwhile, in `Name`, hold a letter key for about ten seconds, then release. The
   second window must print only `0` and/or `1` (never `2`), and the picture updates
   only after you release the key (about a second later), not per key. Then put `Work`
   back into `Name` and wait for the preview.
6. Click `Back`: the first page; the line reads `Identity: changed (name, accent)` (your
   edits are kept). Click `Review`: the page ends with a blank line and then
   `Identity: Work (changed)` and `Monogram: W on #E0A03F`. Click `Back`: you land on the
   Identity page again with the values kept. Click `Discard changes`: the fields return to
   `Jarvis` and `#3FE0D0`; `Back`: the line reads `Identity: default`.
7. Type a new `Name` once more, click `Back`, then select `Copy current Jarvis` on the first
   page: the status line under the page title reads `Identity changes were discarded
   because the mode changed.` and the line reads `Identity: same as the source`.
8. Closing during a check. Click `Customize identity...`, type one letter into `Name`
   and click `Close` within a second (before the picture updates). The window closes
   at once. In a PowerShell window run
   `@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*wizard_job.ps1*' }).Count`
   two seconds later: it prints `0` (a check that was running was stopped with the window).

## Case 4: rejections and hostile input appear next to their field (UI, no installer)

State: Case 3 start (fresh wizard, Clean, `Customize identity...` open, values read).
Each row: change the field, wait about a second; the planner's message appears in red
text directly under that field (the text is the one printed in Case 1), the preview caption
reads `No preview while the identity is not valid`, and `Review` is not shown. Put the
original value back and the message goes, the preview returns, `Review` is back.

| Field | Type | Expected message under the field |
| --- | --- | --- |
| `Accent colour` | `red` | `[brand].accent must be a #RRGGBB colour, got 'red'` |
| `Monogram letter` | `AB` | `[brand].monogram must be exactly one Latin or Cyrillic letter or digit, got 'AB'` |
| `Name` | `123456789012345678901234567890123` | `[brand].name must be at most 32 characters, got 33` |
| `Name` (monogram empty) | `!Bang` | under `Monogram letter`: `[brand].monogram cannot be taken from [brand].name '!Bang': its first character is not a Latin or Cyrillic letter or digit; set the monogram explicitly` |

Further checks:

1. Name limit of the box. In a PowerShell window run `Set-Clipboard -Value ('a' * 150)`,
   click `Name`, `Ctrl+A`, `Ctrl+V`. The box keeps 100 characters (its `MaxLength`,
   `wizard.xaml` line 75) and the message reads `[brand].name must be at most 32 characters,
   got 100`.
2. Hidden characters. Run `Set-Clipboard -Value ('Bad' + [char]0x202E + 'name')` and paste
   into `Name`. The message reads `[brand].name must not contain control, invisible or
   non-space separator characters, got '\u202e'` (the character is written as an escape,
   it does not reverse the text). The page does not break.
3. Hostile but valid text. Run `Set-Clipboard -Value 'Say "hi" & 5% <b> Работа'` (24
   characters) and paste into `Name` with the monogram empty: no message, the caption reads
   `Generated monogram S on accent #3FE0D0`. Click `Review`: the review shows
   `Identity: Say "hi" & 5% <b> Работа (changed)` literally (no markup effect, no
   percent expansion) and `Monogram: S on #3FE0D0`. Do not click `Deploy`.
4. Cyrillic. Paste `Работа`: the caption reads `Generated monogram Р on accent #3FE0D0`.

## Case 5: the PNG picker (UI, no installer)

State: Preparation done; Case 3 start (Identity page open, values read, Clean).

1. Click `Choose PNG...`. The file dialog is titled `Choose a PNG image for the icon` and
   lists only `PNG image (*.png)`. Choose `D:\AI\jarvis-brand4-tests\pictures\wide.png`.
   `Icon image (optional PNG)` shows that path, the caption reads `Your PNG image,
   centred`, and the large preview shows the 2:1 ellipse centred, with empty bands above
   and below, the blue square at its top-left; not squeezed into a circle, not cropped.
   `Remove PNG` is now usable.
2. Choose `tiny.png`: under the icon row `[brand].icon "D:\AI\jarvis-brand4-tests\pictures\tiny.png":
   is 32x32; the shorter side must be at least 64 px`; caption `No preview while the identity
   is not valid`; `Review` not shown.
3. Same for `notpng.png` (`is not a PNG file (bad signature)`), `sliver.png` (`is 600x100;
   it must be at most twice as wide as high (or the reverse)`) and `truncated.png` (`is
   truncated or corrupt (IDAT chunk is cut short)`); the message text in every row is the
   one printed in Case 1. A rejected file is never drawn.
4. Click `Remove PNG`: the chosen path is dropped, the box reads `No PNG: a generated
   monogram is used`, the messages go, the monogram preview is back.
5. Choose `square.png`: caption `Your PNG image, centred`, a round orange-red disc with a
   blue corner square. Click `Back`, `Review`: the review ends with `Identity: Jarvis
   (changed)` and `Icon image: brand-source/icon.png (copy of
   D:\AI\jarvis-brand4-tests\pictures\square.png)`. Do not click `Deploy`; close.

## Case 6: Review and Deploy a customised Clean home (installer, minutes)

State: Preparation done; Jarvis may run or not. Window: fresh wizard from
`D:\AI\Jarvis\DeploymentWizard.cmd`; the destination `D:\AI\jarvis-brand4-tests\work`
must not exist.

1. `Clean installation`; `Destination folder` = `D:\AI\jarvis-brand4-tests\work`;
   `Customize identity...`; `Name` = `Work`; `Accent colour` = `#E0A03F`; wait for the
   caption `Generated monogram W on accent #E0A03F`; `Review`. The review ends with a
   blank line, `Identity: Work (changed)`, `Monogram: W on #E0A03F`. Click `Deploy`.
2. The output box shows, before the installer lines:

   ```
   Preparing application files in D:\AI\jarvis-brand4-tests\work
   Generated brand icons in D:\AI\jarvis-brand4-tests\work\brand
   Installing Jarvis in D:\AI\jarvis-brand4-tests\work
   ```

   and, when finished, the page `Jarvis is ready`.
3. Click `Create shortcut...`. The file name field must read `Work - work.lnk`. Save it into
   `D:\AI\jarvis-brand4-tests\shortcuts`. Close the wizard (do NOT click `Launch Jarvis`).
4. In PowerShell:

   ```powershell
   Get-Content D:\AI\jarvis-brand4-tests\work\config.toml -Tail 5
   Get-ChildItem D:\AI\jarvis-brand4-tests\work\brand | Select-Object -ExpandProperty Name
   Test-Path D:\AI\jarvis-brand4-tests\work\brand-source
   (Get-Content D:\AI\jarvis-brand4-tests\work\.jarvis-deployment.json | ConvertFrom-Json).phase
   ```

   Expected: an empty line, `[brand]`, `name = "Work"`, `monogram = "W"`,
   `accent = "#E0A03F"` (the rest of `config.toml` is `config.example.toml`; the line
   above the empty line is `# kv_cache_type = "q8_0").`); `brand.ico` and `brand.png`;
   `False`; `complete`.
5. Open `D:\AI\jarvis-brand4-tests\work\brand\brand.png` and compare it with what the
   Identity page showed in the large preview: the same amber disc, the same dark `W`,
   the same proportions (the disc fills almost the whole square; the `W` is about half
   as tall as the disc), transparent corners. Judgement call: is the 16 px version in the
   page's small squares what Explorer shows for `brand.ico` under `Small icons`?

## Case 7: wizard Copy: inherit, rename, restore default, mode switch

State: Case 6 done (`D:\AI\jarvis-brand4-tests\work` is a finished deployment); no Jarvis
runtime running (Copy). Window: fresh wizard from
`D:\AI\jarvis-brand4-tests\work\DeploymentWizard.cmd`.

1. Inherit (installer). The `Source installation` line shows
   `D:\AI\jarvis-brand4-tests\work`. Choose `Copy current Jarvis`; `Destination folder` =
   `D:\AI\jarvis-brand4-tests\copy-inherit`. The first page line reads `Identity: same as
   the source`. Click `Customize identity...`: after the reading moment `Name` = `Work`,
   `Accent colour` = `#E0A03F`, hint `Empty keeps the current letter: W`, caption
   `Generated monogram W on accent #E0A03F`, and `Restore default identity` is usable.
   `Back`, `Review`: the review ends with `Identity: Work (inherited from the source)` and
   `Monogram: W on #E0A03F`. Click `Deploy`, wait for `Jarvis is ready`, close the wizard.
   Then:

   ```powershell
   Get-Content D:\AI\jarvis-brand4-tests\copy-inherit\config.toml -Tail 5
   (Get-FileHash D:\AI\jarvis-brand4-tests\work\brand\brand.ico).Hash -eq (Get-FileHash D:\AI\jarvis-brand4-tests\copy-inherit\brand\brand.ico).Hash
   ```

   Expected: the same `[brand]` tail as Case 6; `True` (an untouched Copy carries the
   generated icon by value; nothing was regenerated).
2. Rename (Review only). Start the wizard again from the same `work` home. `Copy current
   Jarvis`, destination `D:\AI\jarvis-brand4-tests\copy-renamed`, `Customize identity...`,
   `Name` = `Home`. Back: the line reads `Identity: changed (name)`. `Review` ends with
   `Identity: Home (changed)` and `Monogram: W on #E0A03F` (the stored letter is kept).
   Do NOT click `Deploy`. `Back` lands on the Identity page.
3. Restore default. On that page click `Restore default identity`: `Name` shows `Jarvis`,
   `Accent colour` shows `#3FE0D0`, the caption reads `The standard Jarvis icon`, the icon
   box reads `The standard Jarvis icon`, and the fields do not accept typing (they are
   read-only; the CLI forbids combining `-DefaultBrand` with other options, Case 1 of the
   task 3 handoff). Click `Back`: the line reads `Identity: the default Jarvis identity`.
   `Review`: no identity line at all (a default brand shows none). `Back` (the Identity
   page), `Discard changes`: the inherited values (`Work`, `#E0A03F`) return and the fields
   accept typing again.
4. Switch the mode. Type any new `Name` on the Identity page, click `Back`, then click
   `Clean installation` on the first page: the status line under the title reads
   `Identity changes were discarded because the mode changed.` and the line reads
   `Identity: default`.
5. Close the wizard. Known and accepted: `Restore default identity` followed by a real
   `Deploy` runs `-DefaultBrand`, which removes the `[brand]` table through
   `remove_table` (`tools\deployment_toml.py`); that function can also drop a comment line
   directly above a table that follows `[brand]` in a hand-edited source. The wizard's
   `[brand]` is appended last, so nothing is lost for a home made by these cases. Not fixed
   here.

## Case 8 (optional): a PNG home, then Remove PNG in a Copy (installer for the first part)

State: Preparation done; for the second part no Jarvis runtime running; the destination
`D:\AI\jarvis-brand4-tests\work-png` must not exist.

1. Wizard from `D:\AI\Jarvis\DeploymentWizard.cmd`, `Clean installation`, destination
   `D:\AI\jarvis-brand4-tests\work-png`, `Customize identity...`, `Choose PNG...` =
   `D:\AI\jarvis-brand4-tests\pictures\wide.png`, `Back`, `Review`: the review ends with
   `Identity: Jarvis (changed)` and `Icon image: brand-source/icon.png (copy of
   D:\AI\jarvis-brand4-tests\pictures\wide.png)`. `Deploy`, wait, close. Then:

   ```powershell
   Get-Content D:\AI\jarvis-brand4-tests\work-png\config.toml -Tail 3
   (Get-FileHash D:\AI\jarvis-brand4-tests\pictures\wide.png).Hash -eq (Get-FileHash D:\AI\jarvis-brand4-tests\work-png\brand-source\icon.png).Hash
   Get-ChildItem D:\AI\jarvis-brand4-tests\work-png\brand | Select-Object -ExpandProperty Name
   ```

   Expected: an empty line, `[brand]`, `icon = "brand-source/icon.png"`; `True`;
   `brand.ico`, `brand.png`.
2. Start the wizard from `D:\AI\jarvis-brand4-tests\work-png\DeploymentWizard.cmd`,
   `Copy current Jarvis`, destination `D:\AI\jarvis-brand4-tests\copy-nopng`,
   `Customize identity...`: the icon box reads `Inherited from the source: brand-source/icon.png`,
   the caption `Your PNG image, centred`. Click `Remove PNG`: caption `The standard Jarvis
   icon` (the stored brand then has no key left, so it is the default one), `Back`: the
   line reads `Identity: changed (PNG removed)`. `Review` shows no identity line. Do not
   click `Deploy`.

## Case 9: a prepared (resumable) destination refuses a changed identity (UI, no installer)

State: Preparation step 2 done. Create the prepared destination with a fake installer
(real preparation, installer replaced by one that exits with code 7); the block is
state-independent:

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-brand4-tests\ready -ErrorAction SilentlyContinue
cd D:\AI\Jarvis
D:\AI\Jarvis\.venv\Scripts\python.exe -c "import sys; sys.path[:0] = ['D:/AI/Jarvis/src', 'D:/AI/Jarvis']; from pathlib import Path; from tools import deployment; print(deployment.deploy(Path('D:/AI/Jarvis'), Path('D:/AI/jarvis-brand4-tests/ready'), installer=lambda *a: 7))"
(Get-Content -Raw D:\AI\jarvis-brand4-tests\ready\.jarvis-deployment.json | ConvertFrom-Json).phase
```

Expected output:

```
Preparing application files in D:\AI\jarvis-brand4-tests\ready
Installing Jarvis in D:\AI\jarvis-brand4-tests\ready
Installer exited with code 7. Use -Resume after addressing the error.
7
ready
```

Then in the wizard (from `D:\AI\Jarvis\DeploymentWizard.cmd`): `Clean installation`,
`Destination folder` = `D:\AI\jarvis-brand4-tests\ready`.

1. Click `Review` without touching identity: the page `Review deployment` shows
   `Resume installation from the prepared files.`, a blank line and `Destination:
   D:\AI\jarvis-brand4-tests\ready`; the button reads `Resume installation`. Do NOT click
   it (it would run the real installer). `Back`.
2. `Customize identity...`, `Name` = `Work`, wait for the preview, `Back`, `Review`: the wizard
   stays on the first page and the status line under the title reads `This folder holds a
   prepared deployment; it resumes with the identity it was prepared with. Discard the
   identity changes or choose another folder.` (source: `Get-ResumeConflictMessage`,
   `tools\install\wizard_pages.ps1`). `Customize identity...`, `Discard changes`, `Back`,
   `Review`: the resume review of step 1 appears again.

## Case 10: the check is unavailable (UI, no installer)

State: Preparation step 2 done. Build a scratch copy of the deployment tool without the
module the check needs (it only copies source files; the repository is not touched).
One state-independent block:

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-brand4-tests\nocheck -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force D:\AI\jarvis-brand4-tests\nocheck | Out-Null
robocopy D:\AI\Jarvis\src D:\AI\jarvis-brand4-tests\nocheck\src /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
robocopy D:\AI\Jarvis\tools D:\AI\jarvis-brand4-tests\nocheck\tools /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
foreach ($f in 'deploy.cmd', 'DeploymentWizard.cmd', 'config.example.toml', 'requirements.txt') { Copy-Item "D:\AI\Jarvis\$f" "D:\AI\jarvis-brand4-tests\nocheck\$f" }
Remove-Item D:\AI\jarvis-brand4-tests\nocheck\tools\deployment_brand_check.py
cd D:\AI\jarvis-brand4-tests\nocheck
.\deploy.cmd -CheckBrand -Mode clean
"exit $LASTEXITCODE"
```

Expected: a Python traceback whose last line is `ModuleNotFoundError: No module named
'tools.deployment_brand_check'`, then `exit 1`.

Then start `D:\AI\jarvis-brand4-tests\nocheck\DeploymentWizard.cmd`, `Clean installation`,
`Destination folder` = `D:\AI\jarvis-brand4-tests\nocheck-out`, `Customize identity...`:

1. After the reading moment the page is usable: `Name` and `Accent colour` are empty and
   editable, the caption reads `Preview unavailable`, `Review` is visible, and the message
   line (under the buttons) reads `Could not read the current identity now: ModuleNotFoundError:
   No module named 'tools.deployment_brand_check'. It is checked again at Review.`
2. Type `Work` into `Name`: the line becomes `Could not check the identity now:
   ModuleNotFoundError: No module named 'tools.deployment_brand_check'. It is checked again
   at Review.`; `Review` stays visible.
3. Click `Review`: the page `Checking deployment`, then `Deployment could not continue`,
   with the same traceback in the output box (the real preview imports the same module, so
   nothing can be deployed from this copy). `Back` returns to the first page. What this case
   proves: a failing check never traps the owner on the page. That the real preview still
   rejects an invalid request when only the check is unavailable is covered by automated
   tests (see below), not by this recipe.

## Case 11: keyboard and accessibility pass (UI)

State: Case 3 start (Identity page open, values read). Window size: leave it as it opens
(760 x 640).

1. Tab order. Click into `Name`, then press `Tab` repeatedly: `Name`, `Monogram letter`,
   `Accent colour`, `Pick colour...`, `Icon image (optional PNG)` box, `Choose PNG...`,
   `Remove PNG`, `Restore default identity`, `Discard changes`, then `Back`, `Review`,
   `Close` (source: `TabIndex` 0 to 8 in `wizard.xaml` lines 75-110). A disabled or
   hidden button is skipped.
2. Access keys. Alt+N focuses `Name`, Alt+M `Monogram letter`, Alt+A `Accent colour`,
   Alt+P `Pick colour...`, Alt+I the icon box, Alt+H `Choose PNG...`, Alt+G `Remove PNG`,
   Alt+R `Restore default identity` (Copy only), Alt+C `Discard changes`. On the first
   page Alt+D focuses `Destination folder` and Alt+U presses `Customize identity...`.
3. Enter. In `Name`, `Monogram letter` or `Accent colour` Enter presses `Review` (it is the
   default button); on a focused button Enter presses that button.
4. Narrator (Win+Ctrl+Enter toggles it). Focus each field: it is announced with its label
   (`Name`, `Monogram letter`, `Accent colour`, `Icon image`). Type `red` in `Accent colour`
   and wait: the message `[brand].accent must be a #RRGGBB colour, got 'red'` is read out
   without moving focus, and focusing the field reads it again as its help text. The large
   preview is announced as an image named after what it shows (for example `Icon preview:
   monogram W on accent #E0A03F`, or `Icon preview unavailable`).
5. Look. At 150% display scaling (Settings > System > Display > Scale) the text is not
   clipped, the preview stays sharp (it is a drawing), and the page scrolls with the
   mouse wheel when the window is too short. Message text and hints are readable on the
   white card. Known and unchanged: the wizard ignores Windows high-contrast themes (fixed
   colours, as before this task).

## Where the three owner decisions are in the code (for judging them)

- The Identity page is opt-in, not a mandatory screen: `Customize identity...`
  (`wizard.xaml` line 61), the page table in `tools\install\wizard_pages.ps1`, and
  `Enter-IdentityPage` in `tools\install\wizard.ps1`. Making it linear means removing that
  button and routing `choice` to `identity` to `review` in `Get-WizardBackTarget`.
- After `Restore default identity` the fields are read-only: `Use-DefaultIdentity` and
  `FieldsReadOnly` in `Get-IdentityView`, `tools\install\wizard_identity.ps1`. Allowing
  the combination reverses the task 3 rule (`BrandRequest`, `tools\deployment_brand.py`).
- The preview follows validated answers, about a second behind typing: the preview is drawn
  from the answer's `icon_preview` (`Get-IdentityPreview`, `wizard_identity.ps1`;
  `tools\install\wizard_preview.ps1`; `Update-IdentityPreview`, `wizard.ps1`). Instant
  drawing would need the letter, hex and contrast rules duplicated in PowerShell.

## Covered by automated tests, not by hand

The request rules, page transitions, stale-answer and debounce logic, the 20 second
timeout, the sanitising of echoed text, the review lines (`tests\test_wizard_identity.py`,
`tests\test_wizard_pages.py`), the drawing against the real generated icon
(`tests\test_wizard_preview.py`), the XAML labels, tab order and contrast
(`tests\test_wizard_xaml.py`), the controller without a window
(`tests\test_wizard_controller.py`), the worker hand-over and quoting
(`tests\test_wizard_brand_plumbing.py`), `-CheckBrand` and the shared check
(`tests\test_brand_deploy_cli.py`, `tests\test_deployment_brand_check.py`).

## Cleanup (state-independent)

Close every wizard window first, then:

```powershell
Remove-Item -Recurse -Force D:\AI\jarvis-brand4-tests -ErrorAction SilentlyContinue
```

(The deployed homes hold `.venv` folders; deleting them can take a minute.) This handoff
never writes into `D:\AI\Jarvis`; if you want to be sure, `git -C D:\AI\Jarvis status`
shows no change caused by it.

## Report back

For each case: pass, or the exact difference (what you saw instead). Judgement calls
are yours: the one-second lag of the preview, whether `Customize identity...` is easy to
find on the first page, the 16 px legibility, the reading of the messages next to their
fields, and the wording of the status lines.
