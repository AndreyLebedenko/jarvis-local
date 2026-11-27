# Story: Instance branding

Status: Completed, 2026-11-27. Tasks 1-6 are complete. No release version assigned.
On 2026-11-27 the owner added task 5 (change the identity of an existing home) and moved
documentation and release verification to task 6.

Related work: `story-deployment-wizard.md`. Its wizard and `deploy.cmd` are
the entry points this story extends; its tasks 1-4 are complete, task 5
(release verification) is pending and unaffected.

Story task 5 (`task-instance-rebrand-existing-home.md`) reuses the Identity page and
`--brand-check` of task 4.

## Goal

Let the owner give a Jarvis installation its own display name and visual
identity (monogram letter or a custom PNG icon), chosen in the Deployment
Wizard when a new copy is deployed, so several installations on one machine
can be told apart at a glance. Only one Jarvis instance runs at any moment.

## Decisions (owner, 2026-11-26)

- Scope is the **display identity only**: application name, monogram, accent
  colour, icon.
- **Technical identifiers do not change**: the runtime and launcher mutexes
  (`Local\Jarvis.SingleInstance`, `Local\Jarvis.Launcher.SingleInstance`),
  `%LOCALAPPDATA%\JarvisLauncher`, the autostart value `JarvisLauncher`, the
  Python package `jarvis`, `Jarvis.cmd`. The persona, system prompt and
  `self.md` are not branding; they stay in their own files.
- **One instance at a time** stays the rule. The single-instance guard is not
  touched; no per-home mutex.
- **Two icon sources, both supported**:
  1. a generated monogram: a letter in a circle. The default letter is the
     first letter of the name, and the owner can choose another;
  2. an optional user PNG that replaces the generated icon.
- Without any branding the application is exactly "Jarvis" as today; existing
  installations need no migration.

## Current state (commit `cc71105`)

Branding is hard-coded in several places:

- Status Console: `<div class="brand-mark">J</div>` and "JARVIS Status
  Console" in `status_console_ui/index.html`; `.brand-mark` in `style.css`
  (a rounded square today, not a circle); `<title>` in `index.html` and
  `touchstrip.html`; touchstrip window title in `ui/status_console.py`.
- About 24 strings per language in `status_console_ui/strings.js` mention
  "Jarvis" (for example `journal_source_assistant`, `journal_input_placeholder`).
- Tray icon, launcher window icon and the wizard shortcut icon all use
  `launcher/assets/jarvis.ico`, built from `jarvis.png` by
  `tools/build_launcher_icon.ps1`.
- The wizard shortcut name (`tools/install/wizard.ps1`) and the MessageBox
  title in `core/single_instance.py`.

## Design

- **Source of truth: a `[brand]` section in `config.toml`.** Keys: `name`,
  `monogram`, `accent`, `icon` (path to a user PNG, relative to the app home).
  Absent section or key means the default. The deployment tool already
  rewrites and verifies destination TOML; the brand is written the same way.
- **Resolved brand asset directory: `<home>/brand/`.** Generated or converted
  `brand.png` and `brand.ico` live there and take precedence over the package
  defaults in `launcher/assets/`. Tracked package files are never modified.
- **Runtime consumers.** The Status Console receives the resolved brand at
  load time and fills the brand mark, brand name, document titles and the
  `{name}` placeholder in `strings.js`. The brand is always inserted as text,
  never as markup. The launcher (stdlib only) reads the selected home's
  `config.toml` with `tomllib` for the tray tooltip and uses the home's
  `brand/brand.ico` for the tray and window icon.
- **Icon pipeline.** A user PNG is converted to a multi-resolution `.ico` by
  the existing `build_launcher_icon.ps1` logic. With no PNG, a monogram icon
  (letter on an accent-coloured circle) is rendered with `System.Drawing` to
  the same `brand.png` and `brand.ico`, and the same artwork is mirrored by the
  CSS brand mark so the UI and the tray match.
- **Wizard and CLI.** A new optional "Identity" step after mode and
  destination with a live preview. CLI flags `deploy.cmd -Name -Monogram
  -Accent -Icon <png>` feed the same code. Clean mode starts from the default
  brand. Copy mode inherits the source's brand and lets the owner override it.
  The wizard shortcut name and icon come from the resolved brand.
- **In-place rebranding (task 5, owner 2026-11-27).** An existing home can have its
  identity changed without deploying to a new folder, from the CLI (`deploy.cmd -Rebrand`)
  and from a third wizard mode, with the same validation and preview. This replaces the
  earlier decision "no in-place rebranding wizard; edit `[brand]` and restart". Editing
  `[brand]` by hand and using `Regenerate icons` keeps working.

## Boundaries

- No change to the journal, memory, config layering or path contract beyond
  adding the `[brand]` section and the `brand/` directory to the deployment
  inventory (Copy mode carries both by value).
- No renaming of technical identifiers, no persona or prompt rewriting, no
  wake word (Jarvis has none).
- No parallel instances and no change to the runtime locality contract; the
  brand pipeline needs no network.
- Localised grammar is out of scope: `{name}` is inserted unchanged into
  Russian strings, so a name does not decline.
- Windows UI, tray and shortcut verification is a human-run handoff per the
  Testing protocol; config parsing, validation and the deployment rewrite are
  pure-logic tests.

## Acceptance criteria

- [x] Without `[brand]` every visible name and icon is exactly as before.
  Proof: task 1 tests and handoff; the default flow of the task 3 and 4 handoffs.

- [x] With a name, monogram and accent, the Status Console, touchstrip,
  window titles, tray tooltip, tray and window icons, MessageBox title and
  wizard shortcut all show the chosen identity.
  Proof: task 1 handoff (Status Console, touchstrip, titles, MessageBox), task 2 handoff (tray, window, icons), task 3 handoff and the rebrand handoff (shortcut).

- [x] The monogram defaults to the first letter of the name and can be
  overridden; invalid values (empty, more than one letter, unsupported
  characters, over-long name, malformed accent) are rejected with a message
  naming the key, in config loading and in the wizard.
  Proof: task 1 config tests and task 3, 4 and 5 handoffs (the same messages in the CLI and in the wizard).

- [x] A user PNG replaces the generated icon; a missing, non-PNG or unusable
  PNG fails validation before deployment starts.
  Proof: task 2 validation tests; `--brand-check` and `--rebrand` refuse before anything is written.

- [x] A hostile name (markup, quotes, control characters, very long) is shown
  literally and cannot break the page, the TOML or the shortcut.
  Proof: task 1 UI contract tests, task 3 hostile-name cases and the task 4 and 5 hostile-input tests.

- [x] Clean mode applies the wizard's identity; Copy mode inherits the
  source's brand and the override works; `brand/` assets are copied by value.
  Proof: task 3 and task 4 tests and handoffs; task 5 does the same for an existing home.

- [x] Technical identifiers and the single-instance guard are unchanged.
  Proof: the single-instance and launcher tests stay green; no identifier was renamed.

- [x] `PROJECT.md` records the brand contract; README documents the wizard
  step, CLI flags and the `[brand]` keys.
  Proof: `PROJECT.md` ("Architecture: instance branding") and the README.md and README.ru.md section "Give an installation its own identity".

## Ordered task-card sequence

1. **Brand settings and runtime consumption.** `[brand]` parsing and
   validation in `core/config.py`, defaults, the `brand/` asset resolution,
   injection into the Status Console and touchstrip, `strings.js`
   placeholders, MessageBox title. Pure-logic tests plus a UI handoff.
2. **Icon generation.** Monogram renderer and PNG-to-ICO conversion with
   input validation; the launcher reads the brand for tooltip and icons.
   Tests on generated files; tray rendering is a human check.
3. **Deployment integration.** Brand flags in `deploy.cmd`, TOML rewrite and
   verification, Copy-mode inheritance and override, `brand/` in the
   inventory, shortcut name and icon from the brand. Tests with the fake
   installer.
4. **Wizard step.** The "Identity" screen with live preview and the shared
   validation rules; UI state-transition tests and a Windows visual handoff.
5. **Change the identity of an existing home.** `--rebrand` and `deploy.ps1
   -Rebrand`, a third wizard mode on the Identity page of task 4, an
   all-or-nothing write of `[brand]`, the source PNG and the icons. Card:
   `task-instance-rebrand-existing-home.md`.
6. **Documentation and release verification.** README, `PROJECT.md`, and a
   human-run end-to-end handoff: deploy a clean and a copied home with a
   custom name, a generated monogram and a custom PNG, rebrand an existing home,
   and confirm every surface listed in the acceptance criteria.

## Open questions

None left. Both were decided in the tasks that owned them:

1. Default accent colour: `#3FE0D0`, the Status Console cyan (task 1,
   `DEFAULT_BRAND_ACCENT` in `core/config.py`).
2. PNG requirements (task 2, `core/brand_icon.py`): shorter side at least 64 px, longer
   side at most 2048 px, aspect ratio at most 2:1, file at most 8 MiB; a non-square image
   is fitted inside the square and centred; transparency is allowed.

## Resolved questions (owner, 2026-11-26)

- The accent colours only the brand mark and the generated icon, never the UI
  theme.
- Allowed monogram characters: Latin and Cyrillic letters and digits.
- A user PNG may contain transparency (confirmed in task 2).

## Closing notes (2026-11-27)

- Task 6 was done as: README.md and README.ru.md (the new section covers the wizard step,
  the `deploy.cmd` options, the `[brand]` keys and the in-place rebrand), `PROJECT.md`, and
  the owner's own check of deployment on 2026-11-27, who reported that it works. No
  separate release handoff was written for task 6: the per-task handoffs
  (`manual/instance-branding-1-handoff.md` to `manual/instance-branding-4-handoff.md` and
  `manual/instance-rebrand-handoff.md`) cover every surface and were run by the owner.
- Deployment of a clean and a copied home with the real installer was last covered by the
  owner's handoff runs of tasks 3 and 4 and by this final check; the automated suite uses a
  fake installer.
- The story's tasks and their cards are in `tasks/done/`.
