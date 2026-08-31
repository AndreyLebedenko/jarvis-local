# Task v1.9.0-5: Docs + release verification

**Status:** Implemented, awaiting human verification. Pre-doc test-suite
split done (26 files under `tests/main_split/` + shared
`_support_from_test_main.py`; 215 tests, same names/bodies; gates green in
the same run as before the split - 2535 passed / 1 skipped, ruff check +
format clean). Docs written: `config.example.toml` ([response] mode full
comment, [hotkeys] response_mode_toggle), README.md + README.ru.md
(Response modes section, hotkey tables, Status/Settings tab lists),
PROJECT.md v1.9.0 section extended (localized TTS gate + persistence
model). Assembled human-run release handoff below. Handoff
self-sufficiency audit of tasks 2/3/3b/4 handoffs done - see its section
in this card. Codex review of the split commit (2026-08-31, deep): 2
findings, both fixed - P2 package-safe helper imports (absolute
`tests.main_split...` imports replaced by bare `_support_from_test_main`
imports; pytest's rootdir insertion resolves them; suite re-verified) and
P3 broken Markdown link in README.ru.md (link target joined back).
**Story:** `tasks/story-v1.9.0-response-modes.md` (scope item 5). Closes the
story.
**Depends on:** task-v1.9.0-1..4 (all behavior in place).

## Summary

Document the three response modes and their trade-offs for users and config,
record any architectural decision that landed, and assemble the human-run
release verification handoff (hotkey, voice, and mode-3 audio timing are
hardware/manual checks). Then close the story.

## Context you need

- `tests/test_main.py` is 5700+ lines covering the whole `Orchestrator`/`App`
  history from task-08 onward, in one file. Existing `# --- ...` section
  markers already outline natural per-topic boundaries (turns: clipboard/
  journal/attachment; interrupt/cancel; response mode; wiring; debug mode;
  shutdown; playback lock; etc.) - see the "Pre-doc test suite cleanup" step
  below for splitting it along those lines.
- `config.example.toml`: the `[response] mode` entry gets its full explanatory
  comment here - the three modes, what each speaks/shows, the mode-2
  self-contained trade-off, and mode-3's two-pass timing. Task 1 added only the
  minimal parseable entry; this task writes the user-facing explanation.
- `README.md` / `README.ru.md`: user-facing description of switching modes (the
  drop-down, the cycling hotkey and its chosen `ctrl+alt+<letter>`, and - if it
  shipped - the voice command). Keep hotkey honesty (README must state the real
  binding actually registered).
- `PROJECT.md`: add a v1.9.0 note only if an architectural decision was
  recorded - the two-contract split, the mode-3 second pass being reasoning-off
  and form-only, the derivative's additive-in-turn persistence and its
  exclusion from the retrieval/memory corpus, and the mode-3 first-pass TTS
  suppression being a localized mode-keyed gate (not the global mute). Also
  record the owner-approved interpretation from 2026-08-30: mode 3 is a
  canonical text canvas plus a spoken commentary/log over that canvas, and this
  is a deliberate quality-for-latency trade. Update in the same spirit as prior
  story notes; do not restate what the code already makes obvious.
- `docs/`: any user/architecture doc that enumerates runtime toggles
  (thinking mode, mic-sleep, visibility) should gain the response-mode entry so
  the set stays complete.
- The prior story's release-verification task (e.g.
  `tasks/done/task-v1.8.3-4-docs-and-release-verification.md`) for the shape of
  the handoff and the exact-command style.

## Boundary

- Docs + verification handoff only. No behavior change; if a doc reveals a
  behavior gap, write a bug report (`tasks/bug_reports/`) rather than fixing it
  here.
- PROJECT.md gets a note only if a real architectural decision needs recording;
  no note-for-note's-sake.
- The test-suite split below is test-file reorganization, not a behavior
  change - no test's assertions or fixture semantics may change as part of
  it, only which file each test lives in and how shared fixtures are shared.

## Pre-doc test suite cleanup

Runs first, before any documentation edit in this task.

- Split `tests/test_main.py` (5700+ lines) into multiple files by topic,
  following its own existing `# --- ...` section boundaries (e.g. turns,
  interrupt/cancel, response mode, wiring, debug mode, shutdown, playback
  lock). Extract shared fixtures/fakes (`_orchestrator`, `_FakeBackend`,
  `_FakeJournalRecorder`, etc.) into a shared module or conftest rather than
  duplicating them per file.
- Every test keeps its current name, body, and assertions unchanged - this
  is a file-layout move, not a rewrite.
- `python -m pytest`, `ruff check`, `ruff format --check` green (same total
  test count as before the split) before moving on to the docs requirements
  below.

## Requirements

- `config.example.toml` `[response] mode` documented with the three modes and
  their trade-offs.
- README (en + ru) updated: mode switching via drop-down, hotkey (real
  binding), and voice command if it shipped. The README must describe Mode 3
  as the canvas+voice feature and call out that it is intentionally alternative
  to lowest-latency output.
- `config.example.toml` `[hotkeys]` gains the `response_mode_toggle` entry
  with its real default binding. Known gap being closed here, surfaced by
  the owner on 2026-08-30: the binding (default `ctrl+alt+o`) shipped in
  task 2 but is listed neither in `config.example.toml` nor in either
  README's hotkey table; the prepared task-3 handoff silently depended on
  it (see
  `tasks/bug_reports/2026-08-30-handoff-silently-depends-on-undocumented-hotkey.md`
  and the handoff self-sufficiency rule, Testing protocol item 4 in
  `AGENTS.md`).
- Handoff self-sufficiency audit as part of assembling the verification
  handoff: every human-run handoff prepared by this story (tasks 2, 3, 4
  handoffs and the assembled release handoff) is checked against Testing
  protocol item 4 - each hotkey, config key, and implicit default named
  literally with a source reference, no step assuming a starting state of
  a persistent setting.
- PROJECT.md v1.9.0 note if warranted; docs toggle list updated.
- A single assembled human-run verification handoff with exact commands
  covering: default-unchanged behavior; mode 2 self-contained one-pass output;
  mode 3 streaming/timing/derivative/first-pass-silence; hotkey cycle + UI
  drop-down + persistence across restart; voice switch (or the recorded stop
  outcome from task 4).

## Verification

- `python -m pytest`, `ruff check`, `ruff format --check` green (docs changes
  must not break the pure suite; any doctest/config-example parse test stays
  green).
- The human runs the assembled handoff and reports; on green, the story's
  acceptance criteria are all satisfied.

## Acceptance criteria

- [ ] `tests/test_main.py` is split by topic (pre-doc cleanup step), same
      tests unchanged, before any doc edit in this task.
- [ ] `config.example.toml`, README (en + ru), and the docs toggle list
      describe all three modes and how to switch; hotkey honesty preserved,
      including the previously undocumented `response_mode_toggle` binding
      in the README hotkey tables and `config.example.toml` `[hotkeys]`.
- [ ] Every handoff prepared by this story passes the handoff
      self-sufficiency audit (Testing protocol item 4): literal hotkeys and
      config keys with source references, no assumed starting state for
      persistent settings.
- [ ] PROJECT.md carries a v1.9.0 architectural note iff a decision needed
      recording.
- [ ] The assembled human-run verification handoff exists with exact commands
      and covers every story acceptance criterion.
- [ ] `ruff` and `pytest` gates green; the story can be closed on a green
      human report.

## Handoff self-sufficiency audit (Testing protocol item 4, AGENTS.md)

Audited 2026-08-31 against the rule: every hotkey, config key, and implicit
default named literally with a source reference; no step assumes a starting
state of a persistent setting.

- task-v1.9.0-2 (`tasks/done/task-v1.9.0-2-hotkey-and-ui-dropdown.md`,
  Verification section): FAILED as originally prepared - it never named the
  binding. This is the already-recorded finding
  (tasks/bug_reports/2026-08-30-handoff-silently-depends-on-undocumented-hotkey.md,
  restated in that card's Correction 2026-08-30). Not repaired in place: the
  card is done and its correction section documents the gap; the assembled
  release handoff below carries the coverage (hotkey cycle + drop-down +
  persistence) with literal bindings.
- task-v1.9.0-3 (`tasks/done/task-v1.9.0-3-mode3-second-pass-and-tts-
  suppression.md`, "Human verification handoff"): PASS after its own
  2026-08-30 correction - Ctrl+Alt+O named with source (`config.py:140`,
  `[hotkeys] response_mode_toggle`), mode-reach steps state-independent
  ("the number of presses depends on the currently active mode, which
  persists across restarts"), launch command named.
- task-v1.9.0-3b (`tasks/done/task-v1.9.0-3b-status-panel-response-mode-
  toggle.md`, "Human-run handoff"): PASS, owner-verified 2026-08-30 -
  binding named with source, "from an arbitrary starting state" wording
  throughout, config path state declared as reachable from either starting
  state.
- task-v1.9.0-4 (`tasks/done/task-v1.9.0-4-voice-toggle-intent.md`, "Human-
  run handoff"): PASS - `voice_intent_directive` named with source
  (`config.py:687`, default None, opt-in directive text provided),
  Ctrl+Alt+I named with source (`config.py:134`), opt-out step is
  state-independent. Owner-verified live 2026-08-30.

No new gaps found beyond the already-recorded task-2 one.

## Assembled release verification handoff (human-run, hardware)

Hardware/UI/live-model checks per the Testing protocol. The agent prepares
this and stops; the human runs it and reports. Executable from its own text.

Launch command for every step (repository root; do not run twice
concurrently):

```
python -m jarvis --status-console
```

Global references used throughout (all defaults; each may be overridden by
the named `[hotkeys]`/`[prompts]`/`[response]` key in `config.toml`, or by
the per-key layering from `config.ui.toml` - check those files first if a
binding below does not match):

- Response-mode cycle hotkey: **Ctrl+Alt+O** - `hotkeys.
  response_mode_toggle`, default `src/jarvis/core/config.py:140`
  (`[hotkeys] response_mode_toggle`).
- Interrupt hotkey: **Ctrl+Alt+I** - `hotkeys.interrupt`, default
  `src/jarvis/core/config.py:134`.
- Response mode config key: `[response] mode`, values `text` / `voice` /
  `text_voice`, default `text` - `src/jarvis/core/config.py`
  `ResponseSettings.mode` (`config.py:697`) and `config.example.toml
  [response]`.
- Persisted-default write-back target: `config.ui.toml` (repository root),
  written only by the Settings tab's Apply.
- Voice-intent opt-in key: `[prompts] voice_intent_directive`, default
  absent (feature off) - `src/jarvis/core/config.py:687`.

No step below assumes a starting mode: each says how to reach its target
state from whatever the persistent setting currently is (mode persists
across restarts; the live mode is session-only).

### 1. Default-unchanged behavior (mode 1, `text`)

Reach the target state: open the Settings tab, set the "Response mode" /
"Режим ответа" drop-down to "Text only" / "Только текст", click Apply, then
start (or restart) Jarvis.

1.1. Launch `python -m jarvis --status-console`. Speak a short question and
     a typed question via the Journal dock. Expect: the reply streams to
     the screen AND is spoken sentence-by-sentence as it streams (existing
     behavior), one request entry per turn in the events panel, no
     "spoken aloud" block in the Journal.

### 2. Mode 2 self-contained one-pass output (`voice`)

Reach the target state: press Ctrl+Alt+O (checking the Status-tab Response
mode buttons after each press) until "Voice" is highlighted, or click
"Voice" on the Status-tab buttons directly. (Live, session-only value.)

2.1. Ask a question that tempts structured output, e.g. "назови три
     способа уменьшить задержку звука". Expect: ONE spoken answer, plain
     connected prose, no bullets/tables/URLs spoken; the spoken words do
     not reference anything shown on screen (nothing is displayed that the
     speech depends on). One request entry in the events panel.

2.2. Choose a request whose content inherently needs a visual remainder
     (e.g. "дай таблицу сравнения X и Y"). Expect: the spoken answer
     describes, not displays - the table itself is not shown anywhere
     (that is the known, owner-accepted mode-2 trade).

### 3. Mode 3 streaming/timing/derivative/first-pass silence (`text_voice`)

Reach the target state: press Ctrl+Alt+O (or use the Status-tab buttons)
until "Text + voice" is highlighted.

3.1. Ask a question whose answer has visible structure (e.g. "list three
     ways to reduce audio latency, briefly"). Timing sequence to confirm:
     (a) the reply streams to the screen immediately, exactly like mode 1;
     (b) NO speech plays while it streams; (c) after the on-screen answer
     completes, after a short pause, Jarvis speaks - a shorter derivative
     of the shown text, not a re-derivation; (d) any spoken reference
     ("as in the table above") matches actually visible content.

3.2. In the events panel, confirm two request entries for this one turn:
     the primary pass and a derivative sub-pass (not a second turn).

3.3. Open the Journal for this session: the assistant entry shows a
     collapsed "spoken aloud >" block; expanding it shows the derivative
     text. Confirm the canonical (screen) text is also stored. If a future
     session's automatic-retrieval/search is exercised, only canonical
     content should surface.

### 4. Hotkey cycle + UI drop-down + persistence across restart

4.1. Cycle: press Ctrl+Alt+O repeatedly. Expect the Status-tab buttons to
     move text -> voice -> text_voice -> text (wrapping), one press per
     step. The Settings-tab drop-down does NOT move while you cycle.

4.2. Persistence: on the Settings tab, pick "Text + voice" in the
     drop-down, click Apply (the "restart to apply" banner appears).
     Fully quit (Ctrl+Alt+Q or the Shutdown button) and relaunch
     `python -m jarvis --status-console`. Expect: the session starts in
     Text + voice (Status-tab buttons show it). Then restore whatever
     default you want the same way (drop-down + Apply) - do not leave
     the setting on an unintended value.

### 3b replay (regression, already owner-verified 2026-08-30)

The four Status/Settings separation checks (live buttons vs restart-to-apply
drop-down vs `config.ui.toml` byte-identity under live toggles) live in
`tasks/done/task-v1.9.0-3b-status-panel-response-mode-toggle.md`. Re-run
them only if 4.1/4.2 above behave unexpectedly.

### 5. Voice switch (task 4's recorded outcome + opt-in re-check)

Task 4's handoff was owner-verified live on 2026-08-30
(`tasks/done/task-v1.9.0-4-voice-toggle-intent.md`); no further live run is
required for release. Optional re-check:

5.1. Opt in: add to `config.toml` under `[prompts]` (create the section if
     absent; the feature is OFF without this line) the directive from
     `tasks/done/task-v1.9.0-4-voice-toggle-intent.md` (the ready-to-paste
     `voice_intent_directive = "..."` one-liner in its handoff preamble),
     then restart Jarvis.

5.2. Say "переключись на голосовой режим". Expect: no spoken/text answer to
     the command; the Status-tab buttons highlight "Voice"; the journal
     shows the utterance with a mode-switched outcome. Then say something
     that merely mentions modes (e.g. "какие режимы ответа существуют?");
     expect a normal spoken answer and NO mode change.

5.3. Opt out: remove the `[prompts] voice_intent_directive` line, restart:
     voice turns behave as in step 1 (no probe request in the log, no mode
     change from speech).

### Report

Report per-step outcomes (or "green" wholesale). On green, every story
acceptance criterion is satisfied and the story closes.
