# Task: Normalize tests, manual checks, and documentation

**Story:** `tasks/story-quality-tooling-and-package-layout.md`
**Status:** Completed.

## Summary

Finish package-qualified imports across tests and manual checks, enforce Ruff
in CI, and document the package and quality contracts.

## Acceptance Criteria

- [ ] Tests do not modify `sys.path` to find production modules.
- [ ] Manual checks use package-qualified imports and documented commands.
- [ ] CI runs Ruff lint, Ruff format check, and `python -m pytest`.
- [ ] README files and `PROJECT.md` describe the new canonical layout.
- [ ] Graphify is refreshed for the meaningful documentation changes.
