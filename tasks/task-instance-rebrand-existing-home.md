# Task instance-rebrand: Change the identity of an existing home

Status: Approved, 2026-11-27. Not started. Task instance-branding-4 is completed; its
Identity page, `--brand-check` and page modules are the base of this card (still
uncommitted on `feat/branding-4-wizard` until the owner asks for a commit).

Story: `tasks/story-instance-branding.md`, task 5 (release verification moved to task 6).
This card reverses one decision of that story, "No in-place rebranding wizard. An existing
home is rebranded by editing `[brand]` and restarting." The owner asked for the reversal on
2026-11-27; the story card is updated accordingly. `PROJECT.md` records the contract when
the code lands, in the same change. Size: M.

## Owner's answers (2026-11-27)

All three recommendations were accepted without changes: (1) any folder with `config.toml`
and a Jarvis version that knows `[brand]` can be rebranded; (2) one pipeline for the CLI and
the wizard; (3) old shortcuts are not touched, the finish page and the README say what to
expect. The questions are kept below as the record of the reasoning.

## Summary

Let the owner change name, monogram, accent and PNG of a home that is already deployed,
in place, without deploying to a new folder, with the same rules, messages and preview as
deployment:

1. A new Python entry, `--rebrand`, next to `--preview` and `--brand-check` in
   `tools.deployment`. It plans the brand with the existing `plan_brand` (source = the
   home itself, Copy semantics: unset keys keep the stored value), then writes `[brand]`,
   the source PNG and the icons into that home.
2. A `-Rebrand` parameter set of `deploy.ps1` (`-Target <home>` plus the existing `-Name
   -Monogram -Accent -Icon -NoIcon -DefaultBrand`), so the CLI and the wizard share one
   code path again.
3. A third mode in the wizard first page, `Change identity of an existing home`, that
   goes `choice -> identity -> review -> busy -> finish`, reusing the Identity page of
   task 4 with the home as both source and destination.

Nothing else in the home changes: journal, memory, `.venv`, other config keys, other
files.

## Current state (facts read from the code at the working tree of task 4)

- Today an existing home is rebranded by hand: edit `[brand]` in `config.toml`, then
  `python -m jarvis.core.brand_render --home <dir>` or the launcher Settings button
  `Regenerate icons` (`launcher/window.py`). Both regenerate from what `config.toml`
  already says; neither validates a request, writes `[brand]`, or accepts a new PNG.
  `regenerate_home_icons` is "the one entry point for the CLI, the launcher button and
  deployment" (`core/brand_render.py`).
- `generate_brand_assets` renders into a staging directory inside `<home>/brand/`,
  verifies, then replaces `brand.png` and `brand.ico` with `os.replace`; a failure before
  publishing leaves the old files. It reads a user PNG through the home path stored in
  `[brand].icon` (`build_request` calls `validate_icon_png(home, brand.icon)`), so a new
  PNG must be at that path before it can be rendered.
- `plan_brand(source, mode, request)` (`tools/deployment_brand.py`) is read-only and
  needs no destination. With `source` = the home and `mode` = Copy it already means
  "stored brand plus this request", revalidates an inherited PNG when the request is not
  empty, and dry-runs the rewrite of `config.toml`. `check_brand` (task 4) answers the
  same for the wizard, so the check, the messages and the preview need no new code.
- `apply_brand` writes with `write_bytes` (not atomic); `_reject_ui_layer_brand` refuses a
  `[brand]` in `config.ui.toml`; `ICON_SOURCE_PATH` is `brand-source/icon.png`; picking the
  file that already is `<home>/brand-source/icon.png` would make `shutil.copyfile` copy a
  file onto itself.
- A default brand has no generated icon, and the launcher ignores a stale `<home>/brand/`
  for a default brand (`launcher/identity.py`, `PROJECT.md`).
- Consumers refresh at different moments: the Status Console, touchstrip and window titles
  read `[brand]` when the runtime starts; the launcher reloads its identity at start, after
  a home change, before each mode start and after the `Regenerate icons` button, so the
  tray follows at the next mode start. The runtime never reads `brand.png` or `brand.ico`,
  so replacing them needs no runtime gating (`PROJECT.md`, regeneration section).
- The wizard shortcut is a file the owner saves on the finish page; its name is
  `<brand name> - <folder>.lnk` and its `IconLocation` is `shortcut_icon(home)`, which is
  the home's `brand\brand.ico` for a branded home and the packaged `jarvis.ico` for a
  default one (`tools/deployment_shortcut.py`, `wizard.ps1` ShortcutButton). Nothing knows
  where an old shortcut was saved.
- A wizard-deployed home has `.jarvis-deployment.json` with `phase` `complete`
  (`tools/deployment.py`). A home put in place any other way (older installer, the
  development checkout) has none.
- The wizard scripts are copied into a deployed home (`APPLICATION_FILES`), so the wizard
  running from one home can be pointed at another. The planner and renderer then come from
  the wizard's own checkout, not from the target.

## Design

### A. `tools/deployment_rebrand.py` (new, pure logic, injectable renderer)

`rebrand_home(home, request, *, renderer) -> RebrandResult`:

1. Refuse an ineligible home (see question 1) and an empty request ("Nothing to change:
   give at least one of -Name, -Monogram, -Accent, -Icon, -NoIcon, -DefaultBrand").
2. `plan_brand(home, COPY, request)`: every task-1/2/3 rule and message, unchanged. Also
   `_reject_ui_layer_brand(home)`.
3. Render first, publish later. Render the new icons into staging with the planned brand
   (for a new PNG, from the validated external file, not from a half-written home) and
   verify them. Only after that: write `config.toml` atomically (temporary file in the
   home, then replace), copy the new PNG to `brand-source/icon.png` (handle the same-file
   case), publish `brand.png` and `brand.ico`. A failure before the first write leaves the
   home byte-identical; a failure in the last steps raises a message that names the exact
   recovery command (`python -m jarvis.core.brand_render --home <dir>`). Step 1 of the
   implementation decides how to render from an explicit path (a variant of
   `build_request`, or staging inside the home); the contract above is what is tested.
4. A default result (`-DefaultBrand`, or a request that resolves to the default) removes
   `[brand]` and generates nothing. `brand/` and `brand-source/` are left in place: the
   launcher ignores them for a default brand, and deleting user files is not part of this
   task (question 3 covers shortcuts that still point at `brand.ico`).
5. A non-default result always renders, even when the stored values did not change: the
   command is also the repair for a stale or missing icon.
6. The result carries what was written and what is refreshed when: runtime start (Status
   Console, titles), next mode start (tray), and the shortcut note (question 3).

`tools.deployment --rebrand --target <home>` prints `JARVIS_DEPLOY_REBRAND:<json>`; a
rejected request is an answer with exit code 0 (the `--brand-check` convention), a crash
exits 1. It takes no installer, no runtime mutex and no Python install.

### B. `deploy.ps1 -Rebrand`

A third parameter set with `-Target` (mandatory, an existing home) and the six brand
options; no `-Mode`, `-Resume`, `-Preview`, `-Yes`. The brand reaches Python through
`JARVIS_DEPLOY_BRAND` exactly as today. The consent flag does not exist in this set: a
rebrand never installs Python.

### C. Wizard

First page: a third choice, `Change identity of an existing home`. The destination box
then names the home and is validated as an existing eligible home, not as a new folder.
Flow:

| From | Event | To |
| --- | --- | --- |
| choice (rebrand) | Next, home eligible | identity (not opt-in: it is the point of the mode) |
| identity | Review (check ok or unavailable) | busy (read-only `--brand-check`) then review |
| review | Apply | busy (`--rebrand`) |
| busy | ok / failure | finish / error (Back returns to choice) |
| identity, review | Back | previous page, edits kept |

The Identity page starts from the home's stored brand through the same empty-request
check as Copy (`origin inherited`), with the same two resets (`Restore default identity`,
`Remove PNG`) and `Discard changes`. The Review page shows the resolved brand and which
files will change (`config.toml`, `brand-source/icon.png` if a PNG was chosen,
`brand\brand.png`, `brand\brand.ico`), and says that the running Jarvis shows the new
name after its next start. Finish offers `Save shortcut` as today (a shortcut saved now
carries the new name and icon); what the other finish buttons do for a rebrand is decided
in step 5 and recorded here.
The page table, identity state and preview modules of task 4 are reused; the new logic is
the third mode in `Get-WizardPageState` and its transitions, tested like the others.

### D. Out of the picture on purpose

The launcher Settings window stays as it is (it is stdlib-only and cannot import the
planner in `tools/`); a `Change identity...` button there that starts the wizard for the
saved home is a possible follow-up, not part of this card.

## Questions for the owner (answered, see above)

1. **Which homes can be rebranded?** Recommended: any folder that has `config.toml` and a
   Jarvis version that knows `[brand]` (`src/jarvis/core/brand.py` present), not only homes
   with a `complete` manifest, because the development checkout and pre-wizard homes are
   exactly the ones owners hold. A home that predates branding is refused with "update this
   home first": writing `[brand]` there would feed a config the old runtime may reject, and
   I have not verified how an old runtime treats an unknown table. Alternative: manifest
   `complete` only (safer, excludes the homes you most likely have today).
2. **Where does the entry live?** Recommended: CLI and wizard on one pipeline (this
   card). Cheaper alternative: CLI only, no wizard mode; the Identity page of task 4 is not
   reused then, and there is no live preview for existing homes.
3. **Old shortcuts.** The tool cannot find or edit shortcuts the owner saved earlier. A
   shortcut saved from a branded home keeps its old name, and keeps showing the new icon
   only if it already pointed at `brand\brand.ico` (and only after Explorer refreshes its
   icon cache, which I have not verified). After `Restore default identity` such a shortcut
   keeps pointing at the old `brand.ico` because the file stays. Recommended: say so on the
   finish page and in the README, and offer `Save shortcut`; never delete or search for
   shortcuts. Alternative: delete the generated `brand\` files on a restore (shortcuts then
   show a blank icon, which is worse).

## Decisions taken without a question (reverse any if wrong)

- A rebrand is allowed while Jarvis runs: it writes only `[brand]` and files the runtime
  never reads. To verify in step 1 that nothing in the runtime writes `config.toml`.
- A rebrand with an empty request is an error, not a silent regeneration (regeneration
  already has its own button and command).
- The identity check and the rebrand use Copy semantics, so "unset keeps stored" and the
  `-DefaultBrand` non-combination rule stay exactly as in task 3.
- `brand/` and `brand-source/` are never deleted.

## Boundary

In: `tools/deployment_rebrand.py` (new, in `APPLICATION_FILES`); `tools/deployment.py`
(`--rebrand`); `tools/install/deploy.ps1` (`-Rebrand` set); `wizard.ps1`, `wizard.xaml`,
`wizard_pages.ps1`, `wizard_worker.ps1`, `wizard_job.ps1` (third mode, transport);
`tools/deployment_plan.py` (inventory entry only); atomic write helper for `config.toml`
if none exists; `PROJECT.md` and the story card (same change); tests; the human handoff
`manual/instance-rebrand-handoff.md`.

Out: README and README.ru (task 6 of the story, which documents this too); any change to
the task-1/2/3/4 rules, messages or the `BrandRequest` contract; the launcher Settings
window; shortcut discovery or editing; deleting brand files; per-key reset; technical
identifiers; the single-instance guard; CI scope and `requirements.txt`.

## Acceptance criteria

- [ ] A request changes `[brand]` in the existing home and nothing else in `config.toml`
  (other keys, comments and order preserved); with a new PNG, `brand-source/icon.png` is
  replaced; `brand.png` and `brand.ico` are regenerated; nothing else in the home changes.
- [ ] Every task-1/2/3 rejection arrives with the planner's exact message and the home is
  byte-identical afterwards.
- [ ] A render failure leaves the home byte-identical; a failure after the first write
  names the recovery command.
- [ ] `-DefaultBrand` removes `[brand]`, generates nothing, deletes nothing, and the
  launcher then shows the packaged identity.
- [ ] Picking the home's own `brand-source/icon.png` does not fail or corrupt it.
- [ ] A home that is not eligible, an empty request, and a `[brand]` in `config.ui.toml`
  are refused with a message that says what to do.
- [ ] Hostile names and paths survive the JSON hand-over, the TOML and the page, as in
  task 4.
- [ ] Wizard: the third mode follows the table in C; the Identity page starts from the
  stored brand; Review shows the resolved brand and the files that change; the default
  Clean and Copy flows and their Review text are unchanged (the task-4 tests stay green).
- [ ] The finish text states when each surface refreshes; a shortcut saved afterwards has
  the new name and icon. (human) the owner confirms tray, titles and shortcut.
- [ ] No new dependency; technical identifiers unchanged; new files in the inventory.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green; the human handoff is
  prepared, not run.

## Implementation plan (TDD order)

1. Read-only spikes, no code: which code writes `config.toml` while Jarvis runs; how an old
   home treats an unknown `[brand]`; how to render from an explicit PNG path; the launcher's
   own rule for "a valid home". Report anything that contradicts this card (CLAUDE.md 0).
2. `tests/test_deployment_rebrand.py` then `tools/deployment_rebrand.py` with a recording
   renderer: changed keys only, comments and order kept, atomic write, all rejection rows,
   failure injection before and after the first write, default result, same-file PNG,
   empty request, ineligible home, UI-layer `[brand]`, no files outside `brand/`,
   `brand-source/` and `config.toml` touched.
3. `tools.deployment --rebrand` and its CLI test (exit codes, output line).
4. `deploy.ps1 -Rebrand` parameter set and the wizard job/worker mapping; tests through the
   existing fake-backend harness, including hostile names.
5. Wizard third mode: page table and transitions first (pure PowerShell tests), then XAML
   and wiring; headless controller tests as in task 4.
6. Inventory, `PROJECT.md`, story card, the human handoff, the self-sufficiency check,
   full test run.

## Human handoff (outline)

`manual/instance-rebrand-handoff.md`, self-sufficient per CLAUDE.md Testing protocol 4,
fixed scratch area, literal commands, state-independent preparation (a branded home made
by the real deploy tool, a second PNG, a truncated PNG). Cases: CLI rename and recolour;
CLI with a new PNG, then back to a monogram; `-DefaultBrand`; rejected inputs leave the
home untouched; wizard third mode (preview, resets, Review, Apply); rebrand while Jarvis
runs and what refreshes when (Status Console after restart, tray after the next mode
start); a shortcut saved before and after; an ineligible home. The installer is not run
by any case if the home is prepared from a fake-installer deployment; the cases that need
the real installer are named in the document.
