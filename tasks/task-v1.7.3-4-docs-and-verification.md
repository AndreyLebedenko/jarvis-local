# Task v1.7.3-4: Docs and verification

**Status:** Proposed.
**Story:** `tasks/story-v1.7.3-reasoning-mode-prompts.md`
**Depends on:** `tasks/task-v1.7.3-1-prompt-reference-config.md`,
`tasks/task-v1.7.3-2-effective-reasoning-prompt.md`, and
`tasks/task-v1.7.3-3-code-optimization.md`
**Complexity:** Small. The main risk is documenting the path semantics
precisely enough that the user does not mistake `@/x.md` for a filesystem
absolute path.

## Summary

Document reasoning-mode prompt sections, prompt-file references, and the
final verification state. This task closes the story after implementation and
the code optimization pass are complete.

## Context you need

- Read the story card and completed task cards 1-3.
- `config.example.toml` is the canonical visible config example.
- `README.md` and `README.ru.md` describe user-facing configuration behavior.
- `PROJECT.md` is the source of truth for architectural decisions; update it
  if implementation changes or sharpens a decision recorded in the story.

## Current boundary

- In scope: config example text, README/README.ru updates, PROJECT.md update
  if needed, final automated checks, and story/task status notes.
- Out of scope: new implementation behavior, UI editor work, manual hardware
  verification, and live Ollama checks.

## Requirements

- Document the new `[prompts]` fields:
  `reasoning_low`, `reasoning_medium`, and `reasoning_high`.
- Document that `@<file-path>` is prompt-only syntax, always rooted under
  `./.jarvis/`.
- Document that a leading slash is interpreted inside `./.jarvis/`, while
  `..` is rejected.
- Document that off mode has no separate prompt section.
- Document the effective composition order: base system prompt, memory/self
  material, then active reasoning-mode section.
- Keep English technical docs in English and Russian user docs in Russian,
  matching the repository's communication rule.

## Acceptance criteria

- [ ] `config.example.toml` shows or explains the new fields and reference
      semantics without making them look required.
- [ ] `README.md` and `README.ru.md` explain how to configure inline and
      file-backed reasoning-mode prompt sections.
- [ ] `PROJECT.md` records any implementation-level architectural decision
      not already fully captured by the story.
- [ ] `python -m pytest`, `python -m ruff format --check .`, and
      `python -m ruff check .` are green.
- [ ] Hardware/manual checks are not required; if a live smoke check is useful,
      it is optional and explicitly separate from the acceptance gate.

## Stop conditions

- Stop if documentation reveals an unresolved contradiction between the story
  and implemented behavior.
- Stop if the final checks fail for reasons outside this story's scope.
- Stop if explaining the feature accurately requires documenting a workaround
  rather than a clean design.

## Verification

- Run `python -m pytest`.
- Run `python -m ruff format --check .`.
- Run `python -m ruff check .`.
