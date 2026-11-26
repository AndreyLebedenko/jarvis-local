# Instance branding, task 1: visual handoff

Human-run, per Testing protocol item 4 (`CLAUDE.md`). It opens the real Status
Console and touchstrip windows (WebView2), so the agent prepared it and ran none
of it. Card: `tasks/done/task-instance-branding-1-settings-and-runtime.md`.

What it answers: with a `[brand]` section the header mark, header name, window
titles, `{brand}` UI texts and the already-running message box show the chosen
identity; a hostile name shows literally; with no `[brand]` section nothing
differs from before.

Out of scope here: tray icon, launcher window, shortcut and generated icon
files (tasks 2 and 3). The `[brand]` keys are documented only in
`config.example.toml` (section `[brand]`, commented) and `PROJECT.md` ("Architecture:
instance branding"); the README does not mention them yet (story task 5 debt, not
crossed silently - do not look for them there).

## Preparation

All commands run in the repository root (the app home), in PowerShell. The app
home is the folder holding `config.toml` (`DEFAULT_CONFIG_PATH` in
`src/jarvis/core/config.py`); `Jarvis.cmd` changes into its own folder first.

1. Close any running Jarvis: Status Console, `Status` view, button `Shut down`,
   then the `Shut down` button of the confirmation row.
2. Make sure `config.toml` has no `[brand]` section (delete it if present: TOML
   forbids a second one) and `config.ui.toml` has none either (the loader refuses
   `[brand]` there with an error naming `config.toml`).
3. Print the effective values (source: `load_settings()` in
   `src/jarvis/core/config.py`):

   `.venv\Scripts\python.exe -c "from jarvis.core.config import load_settings; s = load_settings(); print(s.ui.language, s.brand)"`

   Expected now: your language and `BrandSettings(name='Jarvis', monogram='J',
   accent='#3FE0D0', icon=None)`.
4. UI language. `[ui].language` is `"en"` or `"ru"`. `config.ui.toml` overrides
   `config.toml` key by key (layering described at the top of
   `src/jarvis/core/config.py`). To reach a language regardless of the current
   state: set `language` under `[ui]` in `config.ui.toml` if that file has a `[ui]`
   section, otherwise under `[ui]` in `config.toml`, then re-run the print command
   from step 3 and confirm the printed language. The language takes effect at the
   next start.

## Case A: no `[brand]` section (regression check)

Starting state: no Jarvis is running (Preparation step 1). Start: `Jarvis.cmd` (it runs `.venv\Scripts\python.exe -m jarvis --status-console`;
the touchstrip window opens too, unless you add `--no-touchstrip`).

Expect, exactly as before the change:
- Status Console header: a rounded-square mark with `J`, the name `JARVIS`, then
  the dimmer words `Status Console`. Mark and `J` are cyan.
- Status Console window title `Jarvis - Status Console`; touchstrip window title
  `Jarvis - Touchstrip` (hover the taskbar buttons, or Alt+Tab).
- `Journal` view (tab `Journal`; `Журнал` in Russian): the message box placeholder
  reads `Message Jarvis` (`Сообщение Jarvis`) and the search label reads
  `Search Jarvis answers` (`Поиск ответов Jarvis`).
- `Status` view, button `Shut down`: the confirmation row reads `Jarvis will be
  stopped. You will need to start the process again.` (Russian:
  `Jarvis будет остановлен. Потребуется запустить процесс заново.`). Press
  `Cancel` (`Отмена`) to keep running.
- With Jarvis running, start `Jarvis.cmd` again in a second console: a message box
  titled `Jarvis` with the text `Jarvis is already running. Only one instance may
  run at a time.` appears. Press OK: the second command just ends (a PowerShell
  console stays open; a console opened by double-clicking `Jarvis.cmd` closes).

Stop Jarvis before the next case: Status Console, `Status` view, button `Shut down`
(`btn_shutdown`, `id="btnShutdown"` in `src/jarvis/ui/status_console_ui/index.html`),
then the `Shut down` button of the confirmation row. Afterwards no Jarvis process
is running (the second console of the last bullet already ended).

## Case B: a custom brand

Starting state: no Jarvis is running (end of Case A). Append this block to the end
of `config.toml` (first remove any earlier `[brand]` block):

```toml
[brand]
name = "Work Station"
monogram = "W"
accent = "#E0A03F"
```

Re-run the print command from Preparation step 3: it must show `name='Work
Station', monogram='W', accent='#E0A03F'`. Start `Jarvis.cmd` and expect:
- Header mark: a circle (not a rounded square) with `W`, circle and letter amber
  (`#E0A03F`). The accent changes nothing else: compare the orb, chips, badges and
  buttons with Case A in the same runtime state; their colours must match.
- Header name: `WORK STATION` then `Status Console`.
- Window titles: `Work Station - Status Console` and `Work Station - Touchstrip`.
- `Journal` view placeholder `Message Work Station`, search label `Search Work
  Station answers`; the `Status` view shutdown confirmation starts `Work Station
  will be stopped.` (press `Cancel` to keep running).
- A second `Jarvis.cmd` start while it runs: the message box title is `Work
  Station`; its text is still `Jarvis is already running. Only one instance may
  run at a time.` Press OK.

Russian texts. Stop Jarvis (`Shut down`, then the confirmation `Shut down`, as at
the end of Case A). Set `[ui].language = "ru"` (Preparation step 4), start
`Jarvis.cmd` again: the same texts read `Сообщение Work Station`, `Поиск ответов
Work Station`, and the confirmation starts `Work Station будет остановлен.`; the
name is not declined. Stop Jarvis again and restore the language you started with
(Preparation step 4).

Optional layout check. Starting state: no Jarvis is running. Change the name line
to the 32-character maximum, `name = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"` (keep
`monogram = "W"`), and start `Jarvis.cmd`. The window opens at its default width
(1040 px, `width` in `StatusConsoleWindow`, `src/jarvis/ui/status_console.py`);
narrow it, staying above 720 px. The brand and the right-hand controls share one
row and the mark keeps its size. The brand text is one non-wrapping line that is
clipped with an ellipsis at the end of its box (`.brand-name` in `style.css`), so
the dim `Status Console` suffix is clipped first (you may see the full name
followed by `Status Co...`) and only a narrower box cuts the name itself; the
controls are never pushed out. Below 720 px `style.css` (`@media (max-width:
720px)`, `.topbar { flex-wrap: wrap }`) wraps the controls onto a second row by
design; down to the window minimum (480 px, `min_size` in the same file) the mark
and the brand text must still stay on one row. Stop Jarvis, then set
`name = "Work Station"` again.

Monogram checks. Starting state: no Jarvis is running (every start below is only
valid if the previous instance was stopped; a running instance would make the
start stop at the already-running box before the config is read). Delete the
`monogram` line, start `Jarvis.cmd`: the mark letter must be `W` (first character of
the name); stop Jarvis. Then set `name = "#1 Bot"` without a monogram line and
start `Jarvis.cmd`: the start must fail with a traceback ending in a `ConfigError`
that mentions `[brand].monogram` and `explicit`; no window opens and nothing is
left running.

## Case C: hostile name

Starting state: no Jarvis is running (the last start of Case B failed, or stop it
if you skipped that check). Replace the block with (TOML literal string, so
nothing is escaped):

```toml
[brand]
name = '<b>x</b> "q" $& {max}'
monogram = "H"
```

Start `Jarvis.cmd`. Expect the header, both window titles and the texts listed in
Case B to show the characters exactly as typed (`<B>X</B> "Q" $& {MAX}` in the
header, where the header is shown in capitals), no bold text anywhere, no
alert dialog, and the window working normally.

Stop Jarvis (`Shut down`, then the confirmation `Shut down`) before the next step.
Then check the rejections. Each row below is its own start from a stopped state, and
needs no further shutdown: a failed start leaves nothing running. Each line replaces
the matching line inside the `[brand]` block (for the `name` rows the block must also
hold `monogram = "A"`, so only the `name` is at fault; for the other rows keep a valid
`name`). Each start of `Jarvis.cmd` must stop with a traceback ending in a
`ConfigError` message that names the key (no window opens):
- `name = ""` -> `[brand].name`
- `name = "0123456789012345678901234567890123"` (34 characters) -> `[brand].name`
- `monogram = "AB"` -> `[brand].monogram`
- `accent = "orange"` -> `[brand].accent`
- `icon = "../outside.png"` -> `[brand].icon`

## Cleanup (state-independent)

Make sure no Jarvis is running (stop it as above if the last case left one). Delete
the whole `[brand]` block from `config.toml`, run the print command from
Preparation step 3, and confirm the default `BrandSettings(...)` again. Restore the
`[ui].language` you started with the same way as in Preparation step 4.

## Report back

For each case: pass, or what you saw instead (screenshot of the header and the
window titles for Cases A and B helps).
