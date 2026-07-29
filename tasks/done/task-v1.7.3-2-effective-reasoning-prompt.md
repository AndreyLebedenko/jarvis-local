# Task v1.7.3-2: Effective reasoning prompt composition

**Status:** Completed.
**Story:** `tasks/story-v1.7.3-reasoning-mode-prompts.md`
**Depends on:** `tasks/task-v1.7.3-1-prompt-reference-config.md`
**Complexity:** Medium. The change is narrow, but it must preserve the
existing "sample reasoning level once at turn start" and memory-injection
contracts.

## Summary

Use the new optional reasoning-level prompt sections when building the system
prompt for a turn. A turn at `off` receives no extra section. A turn at
`low`, `medium`, or `high` receives exactly that level's configured section,
after the base prompt and memory/self prompt material.

## Context you need

- Read the story card and task 1.
- `Orchestrator._start_turn()` samples `ReasoningLevelState.level` once before
  calling the backend.
- `build_app()` currently passes
  `lambda: memory_loader.compose_system_prompt(settings.prompts.system)` as
  `system_prompt_provider`.
- `MemoryFileLoader.compose_system_prompt()` currently accepts only a base
  prompt and appends `self.md` and `memory.md`.
- Existing orchestration tests around system prompt sampling and reasoning
  level sampling live in `tests/test_main.py`.

## Current boundary

- In scope: effective system prompt composition, `build_app()` wiring, and
  pure orchestration tests.
- Out of scope: config reference parsing, docs, UI, backend `think` mapping,
  memory write tools, journal schema, and reasoning trace handling.

## Requirements

- Keep composition order: base system prompt, memory/self prompt material,
  then the active reasoning-mode prompt section.
- Keep off mode as base-plus-memory only. Do not add or simulate a
  `reasoning_off` section.
- Sample the reasoning level once for the turn and use that same sampled value
  both for selecting the prompt section and for the backend `reasoning_level`
  argument.
- A reasoning-level change while a turn is in flight must not alter that
  turn's already-built message list.
- Avoid making `MemoryFileLoader` know about `ReasoningLevel` unless that is
  clearly the smallest clean design. Prefer a small prompt-composition helper
  if it keeps memory loading and reasoning selection separate.
- Preserve the existing behavior of `start_new_context()` and
  `Orchestrator.clear()`: a new session should re-sample prompt files/memory
  through the provider, but not mutate an in-flight turn.

## Acceptance criteria

- [ ] Off turns include base prompt and memory material only.
- [ ] Low, medium, and high turns include exactly their configured section
      after memory material.
- [ ] If a level's section is omitted, that level behaves like off except for
      the existing backend `think` value.
- [ ] Changing the reasoning level after a turn starts does not change that
      turn's message list.
- [ ] Existing reasoning-token isolation tests still pass unchanged or with
      only naming/setup updates required by this feature.
- [ ] No live Ollama, audio, hotkey, or UI test is needed.

## Stop conditions

- Stop if effective prompt composition requires changing the backend message
  shape instead of only the system prompt content.
- Stop if selecting the prompt section cannot reuse the sampled
  `ReasoningLevel` without a second live state read later in the turn.
- Stop if clean composition requires a broad rewrite of memory file loading
  or conversation history.

## Verification

- Run focused orchestration tests in `tests/test_main.py`.
- Run all prompt/config/reasoning related tests touched by this task.
