# Task v1.8.0-4: Context budget configuration and pure policy

**Status:** Proposed.
**Story:** `tasks/story-v1.8.0-unlimited-conversation-history.md`
**Depends on:** task v1.8.0-3 completed with an approved decision.

## Summary

Implement the approved token estimator, strict history/context configuration,
and a pure budget-allocation policy. Do not select or assemble messages yet.

## Context you need

- Task 3's completed outcome and `PROJECT.md` decision.
- `src/jarvis/core/config.py`: strict dataclass section parsing and `Settings`.
- `config.example.toml` and `tests/test_config.py`.
- Existing pure domain-module patterns such as attachment planning.

## Current boundary

- In scope: `[history]` settings, estimator implementation, budget value
  objects, validation, and pure tests.
- Out of scope: `ConversationHistory`, message ordering, search, retrieval,
  orchestration, and backend calls.

## Requirements

- Add exactly the `[history]` fields, defaults, and safety margins approved by
  task 3. Do not invent alternatives during implementation.
- Reject unknown keys, booleans-as-integers, non-positive limits, impossible
  reserve combinations, and any configured prompt capacity incompatible with
  `backend.num_ctx`.
- Add a pure estimator interface and the approved production implementation.
- Add a pure allocation result that separates at least:
  - fixed prompt input;
  - recent verbatim history;
  - automatic retrieval;
  - tool/result reserve;
  - reasoning/generation reserve.
- Allocation failure is explicit and typed. No component silently borrows
  another component's mandatory reserve.
- No file, database, bus, Ollama, or UI dependency enters the pure policy
  module.

## Acceptance criteria

- [ ] Existing configs retain previous behavior through defaults.
- [ ] Valid `[history]` values load into typed settings.
- [ ] Every invalid or impossible combination fails with a clear
      `ConfigError`.
- [ ] Pure policy tests cover empty, exact-fit, over-budget, Unicode/Russian,
      and tool-reserve cases.
- [ ] The approved estimator and margin are implemented exactly once.

## Stop conditions

- Stop if task 3 did not record exact defaults and a safe estimator.
- Stop if validation requires a live tokenizer or Ollama call.
- Stop if one configuration field acquires two conflicting meanings between
  prompt capacity and generation reserve.
- Stop if clean validation would require weakening strict config handling.

## Verification

- Focused config and new pure-policy tests.
- `python -m ruff format --check .`
- `python -m ruff check .`
