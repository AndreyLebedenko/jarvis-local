# Task v1.7.3-1: Prompt reference config

**Status:** Proposed.
**Story:** `tasks/story-v1.7.3-reasoning-mode-prompts.md`
**Depends on:** story approval.
**Complexity:** Medium. The implementation should be small, but it sits in
`core/config.py`, where strict error behavior and type validation are already
part of the architecture.

## Summary

Extend prompt configuration so `[prompts]` can carry optional
reasoning-level prompt sections and prompt-file references. This task stops
at loading and validating settings; it must not change runtime prompt
composition or backend calls.

## Context you need

- Read the story card first.
- `src/jarvis/core/config.py` owns `PromptSettings`, `_build_prompts_section()`,
  strict unknown-key rejection, and `ConfigError` wording.
- Existing prompt tests live in `tests/test_config.py` around the
  `[prompts]` section.
- Config parsing currently receives only config file paths. If resolving
  `./.jarvis/` relative to the repository root needs a root parameter, make
  that explicit and test it. Do not guess based on process-global cwd in a
  way that makes tests brittle.

## Current boundary

- In scope: `PromptSettings`, prompt field validation, prompt-file reference
  resolution, config tests, and any minimal helper needed to keep this logic
  isolated.
- Out of scope: `Orchestrator`, `MemoryFileLoader`, backend request shape,
  docs, UI, live reload, and any runtime use of the new fields.

## Requirements

- Add optional `PromptSettings.reasoning_low`,
  `PromptSettings.reasoning_medium`, and `PromptSettings.reasoning_high`
  fields. Omitted fields must remain absent/empty in a way task 2 can
  distinguish from configured prompt text.
- Accept each new field as either a literal non-empty string or a file
  reference of the form `"@<file-path>"`.
- Resolve file references under `./.jarvis/` only. A leading slash in the
  reference is stripped for interpretation inside that root:
  `"@/root/think-level-1.md"` resolves to
  `./.jarvis/root/think-level-1.md`.
- Reject any path component equal to `..` before constructing the resolved
  path. This is a `ConfigError`, not silent normalization.
- A configured reference that cannot be read, cannot be decoded as UTF-8,
  resolves to a directory, or resolves to an empty/blank prompt is a
  `ConfigError` naming the `[prompts].<field>` that failed. Cover
  unreadable cases with deterministic inputs such as missing files,
  directories, undecodable files, or an explicit reader seam if one is added;
  do not depend on OS permission tricks in tests.
- Keep `@` syntax prompt-only. Do not add generic file-reference behavior to
  `_build_plain_section()` or unrelated settings.

## Acceptance criteria

- [ ] Existing config files without the new fields still load unchanged.
- [ ] Literal `reasoning_low`, `reasoning_medium`, and `reasoning_high`
      values parse and preserve exact text.
- [ ] File references read UTF-8 prompt files under `./.jarvis/`, including
      references with a leading slash.
- [ ] `..`, missing files, directories, undecodable files, and blank resolved
      prompts raise `ConfigError` with the failing prompt field in the
      message.
- [ ] Unknown `[prompts]` keys and wrong field types still fail exactly as
      before.
- [ ] Pure tests cover the resolver without live Ollama, hardware, or network.

## Stop conditions

- Stop if resolving `./.jarvis/` cannot be made deterministic from the config
  loading boundary without changing broad application startup behavior.
- Stop if the implementation requires generic `@file` semantics for every
  config field.
- Stop if preserving strict config errors would require a wide rewrite of
  `_build_plain_section()` or layered config handling.

## Verification

- Run focused config tests for `[prompts]`.
- Run `python -m pytest tests/test_config.py`.
