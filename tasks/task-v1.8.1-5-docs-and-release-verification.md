# Task v1.8.1-5: Documentation and release verification

**Status:** Not started.
**Story:** `tasks/story-v1.8.1-session-file-operations.md`
**Depends on:** tasks v1.8.1-1 through v1.8.1-4.

## Summary

Record the final session-file architecture, user-facing behavior, limits,
manual handoff, and release verification for v1.8.1.

## Context you need

- `tasks/story-v1.8.1-session-file-operations.md` and all completed v1.8.1
  task cards.
- `PROJECT.md`: single source of truth for architectural decisions and
  verified facts.
- `README.md`, `README.ru.md`, and `config.example.toml`: user-visible docs
  and configuration examples.
- Manual handoff notes from task 3 and task 4.

## Boundary

- Documentation, release notes, task-card reconciliation, and verification
  only.
- No feature implementation or design expansion.
- Do not mark task cards completed or move them to `tasks/done/` until the
  owner has reviewed the implementation handoff, following the project
  workflow.

## Requirements

- Update `PROJECT.md` with the final session-file architecture: loose files,
  generated storage names, create-only model writes, read inheritance, live
  ancestor pointers, no-active-session invariant, lifecycle/delete behavior,
  and persistent UI upload.
- Update user docs to explain what the model can save/read/view, that returned
  `storage_name` values are the stable handles, and that files are removed
  with their session.
- Document `[files]` configuration and defaults in `config.example.toml` and
  any user-facing config docs.
- Record the manual live handoff for builtin tools and persistent UI upload.
- Reconcile story/task status text after verification.
- Run final automated checks and record the exact commands/results.

## Acceptance criteria

- [ ] `PROJECT.md` matches the shipped implementation and does not contradict
      earlier journal/history locality or corpus guarantees.
- [ ] README/user docs explain session-file behavior without promising
      per-file delete, rename, overwrite, or arbitrary cross-session access.
- [ ] Config documentation lists defaults and warns about size caps without
      changing the owner-approved fail-open deny-list semantics.
- [ ] Manual handoff commands cover model write/list/read/stat/view and UI
      persistent upload.
- [ ] Final checks are green: `python -m pytest`,
      `python -m ruff check .`, and `python -m ruff format --check .`.

## Stop conditions

- Stop if documentation reveals a mismatch between the implementation and the
  story's locked decisions.
- Stop if release verification fails outside this task's scope.
- Stop if a manual check cannot be expressed as exact owner-run steps.

## Verification

- Documentation review against the story and implementation.
- `python -m pytest`
- `python -m ruff check .`
- `python -m ruff format --check .`
- Human-run manual handoff steps.
