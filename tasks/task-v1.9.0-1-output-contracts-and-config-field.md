# Task v1.9.0-1: Output contracts + response-mode config field

**Status:** Proposed. Not started.
**Story:** `tasks/story-v1.9.0-response-modes.md` (scope item 1).
**Depends on:** nothing. First slice of the story.

## Summary

Introduce the three-valued response-mode setting, persisted in config and
read by the turn pipeline on the first pass, plus the two extra output-contract
system directives (mode 2 self-contained voice; mode 3 spoken-derivative). This
slice makes the mode selectable in config and honored on the first pass only:
mode 1 (`text`) is today's behavior byte-identical, mode 2 (`voice`) fully
works in one pass, and mode 3 (`text_voice`) selects the mode-2-like
first-pass contract as a placeholder and otherwise behaves like mode 1/2 until
task 3 adds the second pass. No hotkey, no UI, no second pass here.

## Context you need

- `src/jarvis/dialog/thinking_mode.py`: the `ReasoningLevel` enum +
  `ReasoningLevelState`/`ReasoningLevelChanged` shape. The response-mode
  runtime state mirrors this (three-valued), but note the persistence delta:
  reasoning level resets to `off` at launch; response mode is seeded from
  config (this task) and written back by the UI (task 2). Do not fold this
  into `thinking_mode.py`; give it its own module (e.g.
  `src/jarvis/dialog/response_mode.py`).
- `src/jarvis/app.py:230` `_compose_effective_system_prompt`: the exact
  pattern for appending a prompt section by a state value. Reasoning level
  appends a section from `PromptSettings`; the response-mode contract appends
  its own directive the same way. Reuse this composition point; do not open a
  second prompt-assembly path.
- `src/jarvis/app.py:809` `_start_turn` and the reasoning-level read around
  `:928` (`reasoning_level = ...` -> `_compose_effective_system_prompt`): the
  turn pipeline already reads a runtime state at turn-construction time and
  folds it into the system prompt. Response mode reads at the same seam.
- `src/jarvis/core/config.py`: `BackendSettings`/`PromptSettings` and the
  frozen-dataclass + `_from_mapping` parsing/validation convention. The new
  `[response]` block and the two contract prompt sections live here.
- `config.example.toml`: where the documented default goes (task 5 owns the
  full explanatory text; this task adds the minimal parseable entry).

## Boundary

- First pass only. No second backend pass, no TTS suppression - that is task 3.
- No hotkey (task 2), no UI control (task 2), no voice trigger (task 4).
- Mode 3 here selects the mode-2-like first-pass contract; it is explicitly a
  placeholder until task 3 makes it two-pass. Document this in the code seam
  so task 3 has an obvious hook, but keep it out of scope now.
- Do not change the reasoning-level state, mic-sleep, or interrupt contracts.

## Requirements

- A `ResponseMode` enum with three members mapping to config strings
  `text` / `voice` / `text_voice`, and a `ResponseModeState` runtime owner
  mirroring `ReasoningLevelState` (`level`/`set_mode`/`cycle_mode`, a
  `ResponseModeChanged` event carrying `source`, the same synchronous
  read-decide-write race rule). `cycle_mode` order is
  `text -> voice -> text_voice -> text`.
- A `[response]` config block with `mode` (default `"text"`), parsed and
  validated in `config.py`: an unknown mode string is a startup `ConfigError`
  listing the three valid values. `ResponseModeState` is seeded from this
  field at construction (the persistence delta from the reasoning precedent).
- Two output-contract prompt sections (mode 2 self-contained voice; mode 3
  spoken-derivative) added as `PromptSettings` fields with sensible built-in
  defaults, selected by mode inside `_compose_effective_system_prompt` (or a
  sibling composed alongside it). Mode 1 appends nothing (default behavior
  unchanged). The two contracts are separate directives and must not be
  collapsed into one "voice" prompt (story design decision).
- The turn pipeline reads `ResponseModeState.level` at turn-construction time
  and composes the matching contract into the effective system prompt for the
  first pass.

## Verification

- `python -m pytest`, `ruff check`, `ruff format --check` green.
- New pure logic tests: config parse/validate for the three modes and the
  reject-unknown case; `ResponseModeState` cycle order and event `source`;
  `_compose_effective_system_prompt` (or its sibling) appends the correct
  contract per mode and appends nothing for `text`.
- No hardware handoff for this slice (config + prompt composition are pure
  logic). Manual first-pass audio quality of mode 2 can be spot-checked by the
  human but is not a gate here.

## Acceptance criteria

- [ ] With no config change, Jarvis is `text` mode and the first pass is
      byte-identical to today.
- [ ] Setting `[response] mode = "voice"` selects the self-contained voice
      contract on the first pass; `mode = "text_voice"` selects the placeholder
      mode-2-like contract (task-3 hook documented in the seam).
- [ ] An unknown `mode` value is a startup `ConfigError` naming the three
      valid values.
- [ ] Pure tests above pass; `ruff` gates green.
