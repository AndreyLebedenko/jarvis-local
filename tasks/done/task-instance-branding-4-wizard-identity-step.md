# Task instance-branding-4: Wizard Identity step

Status: Completed. Verified by the automated suite and, on 2026-11-27, by the owner's
manual check of the wizard (window, dialogs and installer, human-run per
`manual/instance-branding-4-handoff.md`): it works as designed. The orchestrator approved
the card and the three confirmation items (see "Resolved: confirmation items").

Story: `tasks/story-instance-branding.md`, task 4 (Size: L; one Python tool module,
three PowerShell modules, XAML, deploy-script plumbing, a drawing parity test and a
human handoff).

## Summary

Let the owner give the new home its identity inside the Deployment Wizard, with the
same rules and the same code path as `deploy.cmd`:

1. An optional **Identity** page, opened from the first page with a `Customize
   identity...` button. Fields: name, monogram letter, accent colour, optional PNG,
   plus the two reset affordances of the CLI contract. A live preview draws the icon
   natively in WPF.
2. Validation is never re-implemented in PowerShell. A new read-only sibling of
   `--preview`, `--brand-check`, runs `plan_brand` (task 3) for the current request and
   answers with the resolved brand or the task-1/task-2 message plus the offending
   key. The wizard shows that message next to the field, unchanged.
3. The wizard sends the brand to `deploy.ps1` as parameters (`-Name -Monogram -Accent
   -Icon -NoIcon -DefaultBrand`), through the existing `JARVIS_WIZARD_*` environment
   hand-over to `wizard_job.ps1`, so `deploy.ps1` stays the one place that builds the
   `JARVIS_DEPLOY_BRAND` JSON. The Review page shows the resolved brand.
4. The default state sends nothing: no identity edits means no brand data anywhere, so
   Clean gives the default brand and Copy is a faithful inherit, as today.
5. The page logic lives in pure PowerShell modules (page table, identity state,
   preview geometry) that are tested without a window; the WPF window itself is a human
   handoff.

## Current state (commit `e71e945`)

Facts read from the code, not assumed:

- Pages (`wizard.ps1` `Show-WizardPage`): `choice`, `review`, `busy`, `retry`,
  `error`, `finish`. The page logic is inline in the controller, which needs a window,
  so none of it is tested today. The tests cover only `wizard_worker.ps1` (worker
  streaming, `Get-DeploymentWizardOutcome`, `Get-DeploymentWizardPhase`,
  `ConvertFrom-DeploymentResultLine`), `wizard_start.ps1`, and a check that
  `wizard.xaml` names equal the names listed in the controller
  (`tests/test_deployment_wizard.py`).
- Review = one read-only `--preview` run: `Next` on `choice` resolves the target,
  looks at the manifest phase (`ready` means resume, `preparing` stops with a hint),
  then `Start-WizardStep $true` starts the worker. The review pane is a plain text box
  built in `Set-WizardReview`; Deploy is the same worker with `Preview=false`.
- Worker chain: `Start-DeploymentWorker` starts `powershell.exe -File wizard_job.ps1`
  with `JARVIS_WIZARD_SCRIPT/TARGET/MODE/PREVIEW/RESUME/CONSENT`; `wizard_job.ps1`
  calls `deploy.ps1 -Target -Mode -NonInteractive -Preview: -Resume: -Yes:`; stdout and
  stderr are polled by a 100 ms `DispatcherTimer` through `Receive-DeploymentWorker`.
  `$script:worker` is one slot; the window `Closing` handler refuses to close while it
  is set.
- `deploy.ps1` already has `-Name -Monogram -Accent -Icon -NoIcon -DefaultBrand`, turns
  the bound ones into one JSON object in `JARVIS_DEPLOY_BRAND` (and clears the variable
  when none are bound), and `tools.deployment` reads it. `--preview` runs `plan_brand`
  and returns `brand {name, monogram, accent, icon, is_default, origin}`;
  `-Resume` with any brand option is an error (`_reject_brand_on_resume`), and the
  resume preview returns only `{target, mode}`.
- `--preview` is the wrong tool for live validation: in Copy mode it holds the runtime
  mutex (`_pause_runtime_for_copy`), so it fails while a Jarvis runtime is alive, and it
  plans the destination, so it needs a valid new target. Both are Review concerns, not
  Identity concerns.
- `deploy.ps1` with consent set (`-Yes`) installs Python 3.11 through winget when none
  is found (`Get-OrInstallPython311`), also in a preview run. A validation run that is
  triggered by typing must never do that.
- Measured on this machine (Windows PowerShell 5.1, a Clean `--preview` with `-Name`
  through `deploy.ps1`, three runs): 540-560 ms for the whole chain. With the worker
  job in front it is about 0.8 s. Cheap enough for a debounced check, far too slow for
  a per-keystroke one.
- Task-2 art constants live only in Python: `MonogramStyle` (`core/brand_render.py`):
  disc = accent with margin 8 on a 512 canvas, glyph = graphite `#0A0D14` or white by
  WCAG contrast, glyph at most 50% of the disc height and 62% of its width, centred by
  its measured outline bounds, Segoe UI Semibold; the drawing script
  `tools/generate_brand_icons.ps1` takes them all as parameters. The default brand has
  no generated icon at all: the shortcut and tray show the packaged
  `launcher/assets/jarvis.png` look.
- Brand request rules the wizard has to live with (task 3): unset keys keep the stored
  value; `-DefaultBrand` cannot be combined with any other option; `-Icon` and
  `-NoIcon` exclude each other; there is no per-key clearing. A faithful Copy (empty
  request) carries the source `brand/` and config bytes; any request regenerates.
- The wizard scripts are in `APPLICATION_FILES` (`tools/install/*`), so a deployed home
  can run its own wizard; a new wizard file must be added there. There is a pin test for
  `tools/deployment*.py` but none for `tools/install/*`.
- WPF facts: the window is 760x570 (min 600x480) with a card of 20 px padding; the
  `Next` button is `IsDefault`, so Enter in any text box presses it.

## Design

### A. Where Identity sits (decision; confirmation item 1)

Options:

- **A1. A fifth linear page** between `choice` and `review`. Everyone clicks through a
  form, even those who want the default. Rejected: the owner's rule is that the step
  must not force the user through a form.
- **A2. A section of the first page** (an Expander). No extra click, but the first page
  gets the whole form, the preview and up to six message lines; Enter in a field would
  press `Review`; switching Clean/Copy has to reload the section in place. The page is
  already full at 570 px height. Rejected.
- **A3 (recommended). An opt-in page.** The first page keeps today's controls and gains
  one line, `Identity: default` (Copy: `same as the source`), and a `Customize
  identity...` button. `Review` on the first page goes straight to the review, exactly
  as today. The `identity` page is entered only through the button; its primary button
  is `Review` (the same action, so the flow after opting in is linear: first page,
  identity, review). `Back` returns to the first page with the edits kept, and the
  summary line then says what changed.

Justification: zero extra clicks for the default path; the identity step is literally
"after mode and destination" for those who opt in; the first page stays as dense as it
is. The story's list of four screens stays true for the default flow; the owner may
prefer to read the new page as a fifth screen, which is why this is a confirmation item.
Back from `review` returns to `identity` when the review was started from it, otherwise
to the first page (as today). `retry`, `error` keep today's Back (first page).

### B. Page table and transitions (testable without a window)

`wizard_pages.ps1` (new, dot-sourced by `wizard.ps1`) holds a pure function
`Get-WizardPageState -Page -Resume -Preview -IdentityReady` returning every visibility,
button enabled/content flag and the title that `Show-WizardPage` sets today, plus
`Get-WizardBackTarget -Page -CameFromIdentity` and `Get-WizardReviewGate` (below).
`Show-WizardPage` only applies the record to the controls. The table is first written as
a characterisation test of today's six pages, then extended; transitions that are tested:

| From | Event | To |
| --- | --- | --- |
| choice | Review (default or customised and ready) | busy (preview) |
| choice | Customize identity | identity |
| identity | Review (check ok or unavailable) | busy (preview), remembers `CameFromIdentity` |
| identity | Back | choice, edits kept |
| review | Back | identity if `CameFromIdentity`, else choice |
| review | Deploy | busy |
| busy | preview ok / deploy ok / failure | review / finish / retry or error (unchanged) |
| error, retry | Back | choice |
| choice | mode radio changes after edits | edits discarded, status says so (item 6 of C) |

`Get-WizardReviewGate` decides what `Review` does, from the identity state and the
manifest phase of the typed destination: `go`; `identity` (a customised request whose
check is invalid or pending: open the page instead of starting a preview);
`resume-conflict` (see C, item 5).

### C. Identity model (`wizard_identity.ps1`, pure functions over one state record)

State: `Mode`, `Start` (the resolved brand answered for an empty request, or `$null`
while unread), `NameText`, `AccentText`, `MonogramText`, `IconPath` (absolute path or
`$null`), `NoIcon`, `UseDefaultBrand`, `RequestId`, `Check {Status, Answer, Message}`.

1. **Starting values.** Opening the page the first time per mode runs a check with an
   empty request. Clean answers the default brand; Copy answers the source's brand
   (`origin inherited`). The answer fills the name and accent boxes (programmatic fill,
   guarded so it never counts as an edit) and the preview. Boxes are disabled and `Review`
   is off until that first answer or a failure; on failure the boxes start with the default
   values and a message says the source identity could not be read (below, D).
2. **Request rules** (`Get-BrandRequest`): the empty request is `$null`, and an empty
   request sends nothing.
   - `name`: sent iff the text differs from the start name (ordinal; a typed-back
     original is "no edit"). An emptied box is sent as empty and Python's message appears.
   - `accent`: sent iff it differs from the start accent, case-insensitively; same for
     an emptied box.
   - `monogram`: the box is NOT prefilled. Empty means "automatic": the hint under the box
     reads `Empty keeps the current letter: W` using the letter of the last answer. Sent
     iff non-empty. This avoids every echo of an answer into editable text and the
     user-versus-programmatic edit problem for the one field whose automatic value depends
     on another field.
   - `icon`: a PNG chosen with the file dialog (absolute path); `no_icon`: set by
     `Remove PNG` when the start brand has an icon, otherwise it only clears a chosen
     path.
   - `default_brand`: set by `Restore default identity`; sent alone.
3. **The two reset affordances** are exactly the two CLI switches: `Restore default
   identity` (`-DefaultBrand`; offered in Copy mode when the source brand is not the
   default, because in Clean the start already is the default) and `Remove PNG`
   (`-NoIcon`). After `Restore default identity` the text fields are read-only and show
   the default values, because the CLI contract forbids combining `-DefaultBrand` with
   any other option (confirmation item 2). One UI-local button, `Discard changes`, clears
   all edits back to the starting state; it adds no request language.
4. **No per-key clearing.** Emptying the monogram box returns to the automatic letter;
   there is no way to say "forget the inherited monogram" other than typing a letter, as
   the task-3 card decided.
5. **Resume.** `deploy.ps1` refuses brand options on `-Resume` and the resume preview
   returns no brand. A destination whose manifest is `ready` is a resume. If the identity
   request is non-empty when `Review` is pressed for such a destination, `Review` stops on
   the first page with `This folder holds a prepared deployment; it resumes with the
   identity it was prepared with. Discard the identity changes or choose another
   folder.` An empty request resumes exactly as today. (Silently dropping the edits would
   let the owner believe they applied.)
6. **Mode change** (Clean/Copy radio) after any edit discards the identity state and says
   so in the page status line: the same text means different things in the two modes.
   A destination change does not touch the identity (the brand does not depend on it).

### D. Validation: `--brand-check`, the one sibling of `--preview`

- `tools/deployment_brand_check.py` (new, listed in `APPLICATION_FILES` and in the CLI
  test helper's file list; the existing pin test then covers it): `check_brand(source,
  mode, request) -> dict`. It calls `plan_brand` (read-only; no mutex, no destination).
  Answers:
  - `{"ok": true, "brand": <plan.preview()>, "icon_preview": {...}}`
  - `{"ok": false, "field": "name"|"monogram"|"accent"|"icon"|null, "message": "..."}`
  `field` is the first `[brand].<key>` named in the message; messages without one (an
  unsupported `[brand]` form in the source, a conflicting request) have `null` and are
  shown in a general line. The message text is exactly the planner's.
  `icon_preview` says what the preview must draw, so the wizard decides nothing:
  `{"kind": "monogram", "art": <asdict(monogram_style(brand))>}` (the renderer's own
  `MonogramStyle`: code point, disc colour, glyph colour, ratios, margin, canvas),
  `{"kind": "image", "path": <absolute path>}` (a requested or inherited PNG), or
  `{"kind": "packaged", "path": <source>/src/jarvis/launcher/assets/jarvis.png}` for the
  default brand.
- `tools.deployment.main` gets `--brand-check` (prints `JARVIS_DEPLOY_BRAND_CHECK:<json>`;
  a rejected request is an answer with exit code 0, only a crash exits 1) and `--target`
  becomes optional exactly then.
- `deploy.ps1` gets `-CheckBrand`. `-Target` stays mandatory through a `Deploy` parameter
  set (`DefaultParameterSetName`), `-CheckBrand` belongs to a `CheckBrand` set that has no
  `-Target`, `-Resume`, `-Yes` or `-Preview`. The consent flag is deliberately not part of
  that set: a check never installs Python. If no Python 3.11 is found, the check fails
  with deploy's own message and the page says it is `unavailable`.
- Wizard side (`wizard_worker.ps1`): `Start-DeploymentWorker` gets two optional trailing
  parameters (`-BrandJson`, `-CheckBrand`), so its positional callers keep working; the
  environment gains `JARVIS_WIZARD_BRAND` (the wizard's own JSON, same key names as
  `JARVIS_DEPLOY_BRAND`) and `JARVIS_WIZARD_CHECK_BRAND`. `wizard_job.ps1` maps the JSON to
  the `deploy.ps1` parameters by splatting. A new parser `ConvertFrom-BrandCheckLine`
  mirrors `ConvertFrom-DeploymentResultLine`.
- **Degradation.** A failed or malformed check (no Python, timeout, a crash, a line that
  is not JSON) sets `Check.Status = unavailable` with a sanitised one-line reason. The
  page stays usable: fields editable, a general line says `Could not check the identity
  now: <reason>. It is checked again at Review.`, the preview shows a neutral
  `Preview unavailable` tile, and `Review` is enabled. The real `--preview` validates the
  same request, so nothing invalid can reach a deployment; a brand error found there
  appears on the error page and `Back` returns to the first page.

### E. Concurrency: debounce, one process, only the latest answer

- Every user edit increments `RequestId`, sets `Check.Status = pending` and restarts a
  350 ms one-shot `DispatcherTimer`. Choosing a PNG or pressing a reset button checks at
  once (no debounce).
- At most ONE check process is alive. When the timer fires: no process running -> start
  one for the current request, tagged with its `RequestId`; a process running -> mark
  `dirty` and start the next when it exits. Typing therefore costs at most one process per
  roughly (350 ms + 0.8 s), never one per key.
- An answer is applied only when its tag equals the current `RequestId`; otherwise it is
  dropped and the next check is started. A process that has not answered in 20 s is
  killed and the state becomes `unavailable` (`The check did not finish`).
- The window `Closing` handler kills a running check and then lets the window close (the
  deploy worker still blocks closing as today). The check worker is a second slot; the
  existing tick handler polls both.
- Pure functions `Get-IdentityCheckAction` (`start`, `wait`, `idle`) and
  `Test-IdentityAnswerIsCurrent` are tested with event sequences (many edits, an answer
  for an old id, a timeout, the page left mid-check).

### F. Native preview and how it stays equal to the generated icon

Decision: the preview is drawn natively in WPF from `icon_preview` of the latest current
answer (confirmation item 3). It follows the validated answer, so it trails the typing by
about a second, and it never shows a value Python rejected. The alternative (instant
drawing from the raw text) needs the letter rule (NFC, strip, upper-casing, derivation
from the name, the unsupported-first-character error), the hex rule and the WCAG glyph
choice duplicated in PowerShell, with parity tests; it was rejected because those rules
have one owner today and the answer is already one process away. While a check is
pending the last drawing stays, dimmed, with `Updating...`.

`wizard_preview.ps1` (new): `New-MonogramDrawing -Art` returns a frozen `DrawingImage`
in the renderer's 512x512 coordinates: a disc of diameter `canvas - 2 * margin` in the
disc colour; the letter as outline geometry (`FormattedText`, Segoe UI Semibold, 100 em),
centred by its outline bounds and scaled by `min(height_ratio * D / h, width_ratio * D /
w)`, filled with the glyph colour. Every number comes from `art`; PowerShell holds no art
constant. `New-ImagePreview -Path -Side` loads a PNG with `DecodePixelWidth`,
`CacheOption OnLoad` and no file lock, only for a path that an `ok` answer named, and
returns `$null` on any decode failure (the tile then reads `No preview`); the packaged
icon uses the same function. The vector `DrawingImage` is shown at 96 px and at 32 and
16 px on a dark and a light strip (what the tray and Explorer show), five `Image`
controls over one source.

Keeping and testing the match:

1. One source: `art` is `monogram_style(brand)` of the same planner the deployment uses.
2. Windows test (parity): for W, a Cyrillic letter and a digit, render the real
   `generate_brand_assets` result (GDI+, `brand.png`) and the WPF drawing offscreen at
   512 px (`RenderTargetBitmap`, no window), read both with the existing
   `tests/png_pixels.py`, and assert same corners (transparent), same disc colour at the
   same probe points, same glyph colour, and the glyph's pixel bounding box equal within
   2 px. A spike at the start of step 5 proves offscreen WPF rendering works under
   `powershell.exe` in this repo's test runner and on `windows-latest`; if it does not,
   the test compares `Geometry.Bounds` after the layout transform with the glyph box
   measured on the GDI+ image (same tolerance) and the card records that.
3. Pure layout function `Get-MonogramLayout` (disc rectangle, glyph scale and translation
   from the art and the measured glyph bounds) is tested with numbers on its own.

### G. PNG picker

`Microsoft.Win32.OpenFileDialog` (already available through PresentationFramework, as the
`SaveFileDialog` the finish page uses): filter `PNG image (*.png)|*.png`, file must
exist. The chosen absolute path goes to the check at once; the preview image is loaded
only after an `ok` answer for that exact path, so the task-2 validation (signature,
chunks, inflate, 64 to 2048 px, 8 MiB, 2:1) stands between a hostile file and the WPF
decoder. Rejected files show the task-2 message (`[brand].icon "<path>": ...`) next to
the icon row and keep `Review` off. The deployment copies and validates the file again
(task 3), so a file changed after the check cannot reach GDI+. An inherited icon in a
faithful Copy is not validated by the planner (task-3 tolerance), so a missing or broken
inherited file shows `No preview` and no error.

### H. Review page

`Set-WizardReview` appends, when the previewed brand is not the default, the lines from a
pure function `Get-ReviewBrandLines` over `preview.brand`: `Identity: <name> (changed |
inherited from the source)`, `Monogram: W on #E0A03F` (or `Icon image: <relative path>`
plus, for a newly chosen PNG, `copied from <path>`). Default brand: no line, so the
default Review text is byte-identical to today's. The resume review is unchanged. All
text is set through `.Text`, never as markup.

### I. Transport (changes in task-3 plumbing)

`Start-WizardStep` passes `$script:request.BrandJson` (empty for resume and for an empty
request). `wizard_job.ps1` splats `-Name -Monogram -Accent -Icon -NoIcon -DefaultBrand`
from `JARVIS_WIZARD_BRAND` (PowerShell-to-script calls do not go through native
argument parsing, so embedded quotes survive; a test pins it with the hostile names of
task 3) and `deploy.ps1` is otherwise untouched apart from the `-CheckBrand` set.
Nothing else in the deployment tool changes.

### J. Accessibility and hostile input

- Every input has a real label with `Target` and an access key (the existing `_Destination
  folder` pattern): `_Name`, `_Monogram letter`, `_Accent colour`, `Icon _image`; every
  button has text; the preview `Image`s and the swatch carry `AutomationProperties.Name`
  (for example `Icon preview: monogram W on accent #E0A03F`, `Icon preview unavailable`),
  message lines are `AutomationProperties.LiveSetting="Polite"` and are tied to their field
  through `HelpText`. No information is colour-only: errors are text, the swatch has its
  hex value beside it.
- Tab order is the visual order and is pinned by a test that reads the XAML; focus moves to
  the name box when the page opens; Enter presses `Review` only from a text box (WPF
  default button), a focused button keeps its own Enter.
- Colours: message and hint text on the white card meet 4.5:1, pinned by a test that parses
  the XAML brushes and reuses `contrast_ratio` from `core/brand_render.py`. The preview is a
  vector, so it stays crisp at 150% DPI. The page scrolls (`ScrollViewer`) and the window
  default height grows from 570 to 640 px (`MinHeight` stays 480). The existing wizard uses
  fixed colours and does not follow Windows high-contrast themes; that stays as it is (see
  "Noticed").
- Hostile text: name box `MaxLength` 100 (above the 32-character rule, so Python's wording
  for 33 and more is still reachable; it only bounds the data); accent and monogram boxes
  `MaxLength` 16 and 4; paths are bounded by Windows. Messages are shown through
  `Format-IdentityMessage` (pure): characters of the Unicode categories control, format,
  separator, private use and unassigned (bidi overrides, line breaks) become U+FFFD, the
  text is cut at 300 characters with `...`, wrapped, with a tooltip of the full sanitised
  text. Names, messages and paths are only ever assigned to `.Text`/`.ToolTip`/`.Content` as
  strings. The JSON hand-over carries them intact (Unicode environment block).

### K. Where the tests can reach

| Part | Testable without a window | How |
| --- | --- | --- |
| `check_brand`, `--brand-check`, field mapping | yes, every platform | pytest |
| `deploy.ps1 -CheckBrand`, job splat, quotes | yes, Windows | existing CLI harness (fake bootstrap) |
| page table, transitions, identity state, request rules, debounce/stale logic, message sanitising, review lines | yes, Windows | PowerShell run by pytest, like the existing worker tests |
| preview geometry and parity with the renderer | yes, Windows | offscreen WPF vs real GDI+ render |
| XAML names, labels, tab order, contrast | yes, every platform | XML parse |
| window look, live typing feel, dialogs, real deployment | no | human handoff |

## Boundary

In: `tools/deployment_brand_check.py` (new); `tools/deployment.py` (`--brand-check`,
optional `--target` then); `tools/install/deploy.ps1` (`-CheckBrand` set);
`tools/install/wizard.ps1`, `wizard.xaml`, `wizard_worker.ps1`, `wizard_job.ps1`; new
`tools/install/wizard_pages.ps1`, `wizard_identity.ps1`, `wizard_preview.ps1`;
`tools/deployment_plan.py` (inventory entries only); a pin test that every file of
`tools/install/` is in the inventory; `PROJECT.md` (deployment and branding sections,
same change); tests; the human handoff `manual/instance-branding-4-handoff.md`.

Out: README and README.ru, the release handoff (story task 6 since 2026-11-27; it was
task 5 when this card was written); any change to the task-1/2/3
rules, messages, the `BrandRequest` contract (`-DefaultBrand` stays non-combinable), the
manifest, `-Resume` behaviour or the icon stage; a Status Console look-alike preview
(outline mark on the dark header) and title/tooltip samples; accent presets; the tray
launcher shortcut; per-key reset; technical identifiers; the single-instance guard;
CI scope, `requirements.txt` (no new dependency).

## Acceptance criteria

Ticked items are proven by the automated suite; "(human)" marks what only the handoff
`manual/instance-branding-4-handoff.md` can show.

- [x] No identity edits: the wizard sends no brand data (worker environment without the
  brand variable, no brand parameters to `deploy.ps1`), the Review text is today's text,
  Clean gives the default brand, Copy is faithful. Proof:
  `tests/test_wizard_identity.py::test_a_fresh_state_sends_nothing_and_the_summary_says_default`,
  `tests/test_wizard_brand_plumbing.py::test_the_worker_hands_the_brand_to_the_backend_and_nothing_else`,
  `...::test_a_deployment_through_the_job_without_a_brand_is_the_old_deployment`,
  `tests/test_wizard_identity.py::test_the_review_lines_describe_only_a_brand_that_is_not_the_default`,
  and the unchanged `tests/test_deployment_wizard.py`. (human) Case 2 shows the real
  default Review text.
- [x] The Identity page is opt-in; `Review` on the first page does not visit it;
  transitions and Back targets follow the table in B. Proof: `tests/test_wizard_pages.py`
  (`test_the_pages_that_existed_before_the_identity_page_are_unchanged` is the
  characterisation table of the six old pages, written first;
  `test_back_goes_where_the_owner_came_from`,
  `test_review_goes_on_stops_at_the_identity_or_refuses_a_resume`).
- [x] Clean starts from the default brand; Copy shows the source's brand as the starting
  values; an untouched Copy sends nothing. Proof:
  `tests/test_wizard_identity.py::test_opening_the_page_reads_the_start_and_fills_name_and_accent`,
  `...::test_clean_starts_from_the_default_and_offers_no_restore`,
  `tests/test_wizard_controller.py::test_a_copy_inherits_the_source_identity_and_offers_the_two_resets`.
  (human) Case 7.
- [x] Every task-1 and task-2 rejection appears next to its field with the planner's exact
  message, and `Review` is off while any is shown. Proof:
  `tests/test_deployment_brand_check.py` (every rejection row with its `field`),
  `tests/test_wizard_identity.py::test_the_planners_message_appears_next_to_the_field_it_names`,
  `tests/test_wizard_controller.py`. (human) Cases 4 and 5.
- [x] No validation rule is re-implemented in PowerShell. Proof:
  `tests/test_wizard_identity.py::test_the_identity_module_decides_no_brand_rule_itself`
  (the cheap guard) and review of the new modules; the only bounds are the `MaxLength`
  values (`tests/test_wizard_xaml.py::test_hostile_text_is_bounded_by_the_input_limits`).
- [x] Typing does not spawn a process per keystroke: one process at a time, one request per
  pause, a stale answer is never shown, a hung check is killed after 20 s, closing the
  window kills it. Proof:
  `tests/test_wizard_identity.py::test_only_the_latest_request_is_ever_answered`,
  `...::test_a_check_that_hangs_is_timed_out_after_twenty_seconds`. (human) Case 3, step 5
  counts the check processes on a real window and step 6 closes the window during a check
  (the `Closing` handler that kills a running check has no window-less test).
- [x] The wizard stays usable when the check fails. Proof:
  `tests/test_wizard_identity.py::test_a_failed_check_leaves_the_page_usable`,
  `...::test_a_failure_reason_always_reads_as_a_sentence`,
  `tests/test_wizard_brand_plumbing.py::test_a_review_through_the_job_validates_the_brand_and_creates_nothing`.
  (human) Case 10. That scratch copy cannot show that the real preview still rejects an
  invalid request, because it imports the same module; that part is the job test.
- [x] The preview is drawn natively from the answer, equals the generated icon (corners,
  disc, glyph colour, glyph box within 2 px) for a Latin letter, a Cyrillic letter and a
  digit, and a user PNG is shown scaled only after an `ok` answer. Proof:
  `tests/test_wizard_preview.py::test_the_native_drawing_matches_the_generated_icon`
  (W, Cyrillic Zhe, 7, J; offscreen render, no window),
  `...::test_the_layout_fits_the_tighter_of_the_two_limits_and_centres_the_glyph`,
  `...::test_a_file_preview_is_the_scaled_image_and_failures_give_nothing`,
  `tests/test_wizard_identity.py::test_the_preview_trails_typing_dimmed_and_never_shows_a_rejected_identity`.
  (human) Cases 3 and 5 judge the look.
- [x] The two reset affordances do what the CLI does; `Discard changes` returns to the
  start. Proof:
  `tests/test_wizard_identity.py::test_the_two_reset_affordances_are_the_two_switches`,
  `...::test_removing_a_chosen_png_in_clean_mode_sends_no_switch`,
  `...::test_the_request_json_survives_the_worker_mapping_with_hostile_text`,
  `tests/test_wizard_brand_plumbing.py::test_the_job_parameter_mapping_keeps_empty_values_so_the_planner_can_answer`.
  (human) Case 7, steps 2 and 3, and Case 8.
- [x] The Review page shows the resolved brand and the deployment applies it. Proof:
  `tests/test_wizard_brand_plumbing.py::test_a_deployment_through_the_job_applies_the_brand_with_real_icons`
  (fake installer, real renderer),
  `tests/test_wizard_identity.py::test_the_review_lines_describe_only_a_brand_that_is_not_the_default`.
  (human) Case 6 with the real installer.
- [x] Hostile input does not break the page, the JSON hand-over or the TOML, and is shown
  literally and sanitised. Proof:
  `tests/test_wizard_identity.py::test_a_message_is_made_safe_to_show`,
  `...::test_the_request_json_survives_the_worker_mapping_with_hostile_text`,
  `tests/test_wizard_brand_plumbing.py::test_a_check_through_the_job_needs_no_target_and_keeps_a_hostile_name`.
  (human) Case 4.
- [x] A customised request for a `ready` destination is refused on the first page with the
  resume message; an empty request resumes as before. Proof:
  `tests/test_wizard_pages.py::test_review_goes_on_stops_at_the_identity_or_refuses_a_resume`,
  `...::test_the_resume_refusal_tells_what_to_do`. (human) Case 9.
- [x] Accessibility basics: labels and access keys, automation names, tab order, live
  regions, contrast. Proof: `tests/test_wizard_xaml.py` (labels and names, unique access
  keys, tab order, contrast, error messages announced and not colour-only, and a load of
  the XAML into objects without showing a window). (human) Case 11 (Narrator, keyboard,
  150%).
- [x] Technical identifiers, the single-instance guard and the task-3 contracts are
  unchanged; new scripts and the module are in the inventory; no new dependency. Proof:
  `tests/test_deployment_plan.py::test_every_wizard_script_and_the_window_definition_is_in_the_inventory`,
  the unchanged task-1/2/3 tests, `requirements.txt` untouched.
- [x] `python -m pytest`, `ruff check`, `ruff format --check` green (see "Verification");
  the human handoff was prepared and the owner ran it on 2026-11-27.

## Implementation plan (TDD order)

1. `tests/test_deployment_brand_check.py`, then `tools/deployment_brand_check.py` and the
   `--brand-check` flag: every rejection row with its `field`, the three `icon_preview`
   kinds, inherited start values for Copy (including an invalid stored brand and an
   unsupported form), no files written, no runtime mutex taken, `--target` optional only for
   the check, hostile names survive JSON.
2. Plumbing: `deploy.ps1` parameter sets and `-CheckBrand`; `Start-DeploymentWorker` extra
   parameters; `wizard_job.ps1` splat; `ConvertFrom-BrandCheckLine`. Tests: fake-backend
   worker test (the existing style) for the environment and the splat, the CLI harness for
   the real `deploy.ps1 -CheckBrand` and for a wizard-job Review/Deploy with hostile names
   and with no brand at all (today's behaviour).
3. `wizard_pages.ps1`: characterisation test of today's six pages first, refactor
   `Show-WizardPage` onto the table, then add `identity`, back targets and the review gate.
4. `wizard_identity.ps1`: state, request rules, start values, resets, mode change, field
   messages, `Format-IdentityMessage`, summary line, `Get-ReviewBrandLines`, debounce and
   stale-answer functions; tests by event sequences.
5. `wizard_preview.ps1`: spike for offscreen WPF rendering; `Get-MonogramLayout` tests;
   drawing and image functions; the parity test.
6. `wizard.xaml` and `wizard.ps1` wiring (pane, handlers, timers, picker, colour dialog,
   Closing); XAML static tests (names equal the controller list, labels, tab order,
   contrast); window height.
7. Inventory entries and the `tools/install` pin test; `PROJECT.md`; the handoff; a run of
   `tools/check_handoff_self_sufficiency.py` on the card and handoff; `python -m pytest`,
   `ruff check`, `ruff format --check`.

Automated, every platform: step 1, XAML tests, inventory. Automated, Windows only (skipped
elsewhere, run on `windows-latest` CI): steps 2 to 5 PowerShell parts, including offscreen
WPF rendering, which opens no window. Human-run: the window itself.

## Human handoff

`manual/instance-branding-4-handoff.md`, self-sufficient per CLAUDE.md Testing protocol 4:
fixed test area `D:\AI\jarvis-brand4-tests`, literal commands, every control named by its
label with its `wizard.xaml` line, a state-independent preparation (test PNGs including a
sliver and a truncated one), no hand-written `config.toml`, README debt stated, cleanup.
Cases: 1 shared check outputs (instant); 2 default path unchanged; 3 customise in Clean
(preview, accent, process count, close during a check); 4 rejections and hostile input;
5 PNG picker; 6 Review and Deploy of a customised Clean home (installer); 7 Copy: inherit
(installer), rename, Restore default, mode switch; 8 optional PNG home and Remove PNG
(installer); 9 prepared destination refuses a changed identity; 10 check unavailable;
11 keyboard and accessibility. The cases that run the installer are 6, the first part of 7
and the optional 8. (The task-3 handoff lists its installer cases as `3, 4, 6, 7, and the
optional 8` and omits its optional case 9, the wizard Clean deploy, which also runs it;
that document is left alone, see "Noticed".) The agent ran the instant commands and the
two preparation blocks in a scratch folder and compared their output with the document;
it ran no window and no installer.

## Resolved: confirmation items

There were no blocking questions. Three choices had consequences the owner may want to
reverse; the orchestrator approved all three as written. Where each lives, and what
reversing it costs:

1. **Identity is an opt-in page, not a mandatory fifth screen** (section A). Implemented by
   the `Customize identity...` button (`wizard.xaml`), the page table and back targets in
   `tools/install/wizard_pages.ps1`, and `Enter-IdentityPage` in `wizard.ps1`. Reversing it
   means a linear `choice -> identity -> review` route: remove the button and change
   `Get-WizardBackTarget` and the Review handler.
2. **After `Restore default identity` the fields are read-only** (section C.3), because the
   task-3 contract forbids `-DefaultBrand` with other options. Implemented by
   `Use-DefaultIdentity` and `FieldsReadOnly` in `Get-IdentityView`
   (`tools/install/wizard_identity.ps1`). Reversing it means letting `-DefaultBrand`
   combine, which reverses a rule pinned by task-3 tests and handoff.
3. **The preview follows validated answers** (about one second behind typing, section F).
   Implemented by `Get-IdentityPreview` (`wizard_identity.ps1`), the drawing in
   `tools/install/wizard_preview.ps1` and `Update-IdentityPreview` in `wizard.ps1`.
   Reversing it means duplicating the letter, hex and contrast rules in PowerShell with
   parity tests.

## Decisions taken without a question (reverse any of them if wrong)

- A new sibling `--brand-check` rather than `--preview` (mutex in Copy, destination
  planning, the Python-install side effect of consent), and `deploy.ps1` parameter sets
  instead of a dummy `-Target`.
- The check never installs Python and ignores the consent checkbox.
- The brand reaches `deploy.ps1` as parameters via `JARVIS_WIZARD_BRAND`; `deploy.ps1`
  stays the only builder of `JARVIS_DEPLOY_BRAND`.
- Name and accent boxes are prefilled and compared with the starting value; the monogram
  box is empty-means-automatic with a hint; `Discard changes` is a UI-local third button
  (the owner's "exactly these two reset affordances" is read as "no per-key clearing and no
  other request switch").
- Mode change discards identity edits (with a message); a destination change does not.
- A non-empty identity request for a resumable destination is refused, not dropped.
- Debounce 350 ms, one live check process, 20 s timeout, `MaxLength` 100/16/4.
- Preview sizes 96, 32 and 16 px on dark and light strips (what the owner judged in the
  icon handoffs); no Status Console look-alike, no title samples.
- The accent has a hex box and the standard Windows colour dialog, no preset palette.
- The Review brand lines appear only for a non-default brand, so the default Review text is
  unchanged.
- The window default height grows to 640 px; the identity pane scrolls.
- Python-side module `deployment_brand_check.py` instead of growing `deployment_brand.py`
  (SRP; the planner is not touched).

## Implementation notes (differences from the plan above)

- **Process kill.** A timed-out or abandoned check is killed with `taskkill /T /F`, not
  `Process.Kill()`, because the check is a `powershell.exe` that starts `deploy.ps1`'s
  Python; killing only the parent would leave the child running.
- **Start values after a failed first read.** The plan said the boxes start with the default
  values; they start empty and editable instead, and an empty box with an unknown start is
  not sent (`Get-BrandRequest`), so an unread start can never turn into a request. Shown in
  handoff Case 10.
- **Page logic split.** `wizard_pages.ps1` also owns `Get-ResumeConflictMessage`; the
  controller functions added to `wizard.ps1` are thin (`Update-IdentityPage`,
  `Receive-IdentityWorker`, `Invoke-IdentityNow`, `Enter-IdentityPage`, `Sync-IdentityMode`,
  `Invoke-Review`), all decisions are in the pure modules.
- **Access key clash.** `Discard changes` is written `Dis_card changes` (Alt+C) so that no
  access key repeats on a page; `tests/test_wizard_xaml.py` pins uniqueness across all pages.
- **`Review` is hidden, not greyed,** when it cannot be used (the existing chrome sets the
  button's visibility from `NextEnabled`).
- **Preview drawing.** The first parity run showed the WPF drawing 3 percent too large: a
  `DrawingImage` takes its extent from the drawn bounds, so the disc was stretched to the
  tile. An invisible full-canvas rectangle is drawn first (one comment at that line says
  why). Offscreen WPF rendering works under `powershell.exe` in the test runner, so the
  geometry-bounds fallback was not needed.
- **Headless controller tests.** `tests/test_wizard_controller.py` runs `wizard.ps1` with
  `ShowDialog` replaced by a driver, so the XAML is loaded and the handlers run without a
  window ever appearing. Helpers are in `tests/wizard_ps_support.py` (`report(...)` builds
  the compact JSON of a snippet; scripts are written UTF-8 with a BOM so that Windows
  PowerShell 5.1 reads non-ASCII literals).
- **Failure sentences.** `Receive-IdentityFailure` always produces a sentence (empty reason
  becomes `No reason was reported.`, a missing period is added) because the reason is the
  last line the check printed, which may be a bare exception name.
- **CLI.** `--target` is optional only with `--brand-check` (`tools/deployment.py`); without
  it argparse's own message is reproduced (`the following arguments are required: --target`).
- **Inventory.** `tools/deployment_plan.py` lists the four new files; the new pin test
  fails when a file of `tools/install/` is missing from the inventory.

## Verification

Run on the final tree (Windows 11, Python 3.11.9, Windows PowerShell 5.1):

- `python -m pytest`: 7113 passed, 2 skipped (2026-11-27, 3 min 28 s).
- `python -m ruff check .`: all checks passed; `python -m ruff format --check .`: 674
  files already formatted.
- `tools/check_handoff_self_sufficiency.py` on this card and the handoff: exit code 0.
- The instant commands and preparation blocks of the handoff were run in a scratch folder;
  output equals the documented blocks.
- A fake-installer deployment of the real repository (Clean, `Work`, `W`, `#E0A03F`) gave
  the `config.toml` tail, the `brand\` file list and the shortcut name documented in Case 6.
- The controller was driven without a window against a scratch copy of the tool without
  `deployment_brand_check.py` to read the unavailable-state texts quoted in Case 10.

## Noticed, left out of scope

- `remove_table` in `tools/deployment_toml.py` removes a comment line directly above the
  next table when `[brand]` is removed. It does touch the wizard path: Copy with `Restore
  default identity` runs `-DefaultBrand`, which calls it, so a comment above a table that
  follows `[brand]` in the copied `config.toml` can be lost. The effect is a lost comment
  only; `[brand]` is appended at the end by the deployment, so it needs a hand-edited source
  with a table after `[brand]`. The handoff Case 6 can mention it. Not fixed here.
- The task-3 handoff lists the installer-running cases as `3, 4, 6, 7, and the optional 8`
  and omits the optional case 9 (the wizard Clean deploy). It does not touch wizard code;
  the new handoff states the correct list. The old handoff is a done document and is left
  alone unless the owner wants the one-line fix.
- The wizard ignores Windows high-contrast themes (fixed colours since task 4 of the
  wizard story); the new page follows the same palette.
- `Review` with Copy still fails while a Jarvis runtime is alive (existing behaviour,
  unrelated to the identity check, which takes no lock).
- The wizard has no automated test that the `Closing` handler kills a running check
  (it needs a real window); handoff Case 3, step 8 covers it.
- With the check unavailable, `Review` still depends on the real preview, which imports the
  same Python module as the check, so a missing module breaks both; the degradation only
  protects against a check-only failure (a timeout, a crash, a malformed line).
