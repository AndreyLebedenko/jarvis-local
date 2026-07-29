# Task v1.7.3-3: Code optimization pass

**Status:** Completed.
**Story:** `tasks/story-v1.7.3-reasoning-mode-prompts.md`
**Depends on:** `tasks/task-v1.7.3-1-prompt-reference-config.md` and
`tasks/task-v1.7.3-2-effective-reasoning-prompt.md`
**Complexity:** Small. This is a cleanup and complexity-control pass, not a
new behavior task.

## Summary

Review the code introduced by tasks 1 and 2 for avoidable duplication,
misplaced responsibility, and complexity creep. Apply only
behavior-preserving cleanup that makes the implementation easier to test and
extend.

## Context you need

- Read the story card and the first two task cards.
- Read the "Code entropy review practice" section in `PROJECT.md`.
- The likely touched areas are `src/jarvis/core/config.py`,
  `src/jarvis/app.py`, `src/jarvis/memory/files.py`, and their tests.
- This project treats "need-to-document backpressure" and test complexity as
  design signals. If the prompt composition needs extensive comments or brittle
  tests to be understandable, simplify the design instead.

## Current boundary

- In scope: small behavior-preserving refactors in code touched by this story,
  test helper cleanup, naming cleanup, and removal of duplicated validation or
  composition logic.
- Out of scope: new prompt behavior, docs, UI, changing public config
  semantics, broad refactors outside touched modules, and Pyright-wide typing
  cleanup.

## Requirements

- Look specifically for duplicate prompt non-empty validation, duplicate
  path-reference parsing, and duplicated mapping from `ReasoningLevel` to
  prompt field names.
- Keep error messages stable unless a test first proves the existing wording
  is wrong for the new feature.
- Do not introduce `any`, TODO/FIXME comments, silent exception handling, or
  broad type erasure.
- Keep abstractions small. A helper is justified only if it removes real
  duplication or clarifies ownership between config parsing, prompt
  composition, and memory loading.
- If no cleanup is warranted, record that result in this task card when it is
  completed; do not manufacture a refactor to satisfy the card.

## Acceptance criteria

- [ ] The touched prompt/config/runtime code has one clear owner for
      reference resolution and one clear owner for effective prompt
      composition.
- [ ] No duplicated validation or level-to-field mapping remains in sibling
      code paths.
- [ ] Tests remain readable and do not require excessive setup to prove the
      prompt behavior.
- [ ] No unrelated files or unrelated behavior are refactored.
- [ ] The focused test set from tasks 1 and 2 remains green.

## Stop conditions

- Stop if optimization would require changing user-facing behavior or config
  semantics.
- Stop if reducing duplication points toward a wider architecture change
  outside this story's modules.
- Stop if tests start failing for reasons outside this story's scope.

## Verification

- Run the focused tests touched by tasks 1 and 2.
- Run Ruff format/check for touched files or the full project if practical.
