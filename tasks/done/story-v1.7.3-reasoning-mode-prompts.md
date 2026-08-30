# Story v1.7.3: Reasoning-mode prompt sections

**Status:** Completed.
**Roadmap:** `tasks/done/roadmap-v1.5.1-v1.8.0.md` (v1.7.3 section). Version
chosen 2026-07-29: v1.7.1 and v1.7.2 are already reserved for memory
consolidation and retrieval, and this story is small enough to follow them
without disturbing that sequence.
**Created:** 2026-07-29.

## User-facing goal

The user can give Jarvis extra system-prompt guidance for the active
reasoning level. When reasoning is low, medium, or high, Jarvis receives
the base system prompt plus an optional level-specific prompt section for
that mode. When reasoning is off, Jarvis behaves exactly as it does today.

The user may keep prompt text inline in `config.toml`, or store larger
prompts as Markdown files under `./.jarvis/` and reference them from
`[prompts]`.

## Background

Jarvis already has three relevant contracts:

- `[prompts].system` is the configurable base system prompt.
- `ReasoningLevelState` owns the persistent `off`/`low`/`medium`/`high`
  level, and `Orchestrator._start_turn()` samples it once at turn start.
- Memory files are injected into the system prompt through
  `MemoryFileLoader.compose_system_prompt()`, without hot reload or
  per-token mutation.

This story keeps those contracts. It adds optional prompt material to the
same turn-start sampling point; it does not expose reasoning traces, change
Ollama's `think` payload values, or alter the reasoning-token isolation rule.

## Complexity estimate

Small-to-medium. The code volume should be modest, but the implementation
crosses a strict boundary between config parsing, file loading, memory prompt
composition, and per-turn orchestration. The task split below is designed to
keep those seams visible for the coder agent:

- task 1 owns config shape and prompt-reference resolution only;
- task 2 owns runtime prompt composition only;
- task 3 is a code-optimization pass after the behavior is working;
- task 4 owns documentation and final verification.

## Boundaries

In scope:

- New optional `[prompts]` fields for reasoning levels:
  `reasoning_low`, `reasoning_medium`, and `reasoning_high`.
- Prompt fields may be either literal prompt strings or file references of
  the form `"@<file-path>"`.
- File references are resolved relative to the project-local `./.jarvis/`
  directory, regardless of whether `<file-path>` looks absolute. For example,
  `"@/root/think-level-1.md"` resolves under
  `./.jarvis/root/think-level-1.md`.
- Any parent-directory traversal component is rejected before path
  resolution. `..` is a config error, not something silently removed.
- A configured file reference that cannot be read is a startup `ConfigError`.
  Prompt configuration must fail loudly when it is wrong.
- Effective prompt composition for a turn is deterministic and sampled once
  at turn start.

Out of scope:

- No separate `reasoning_off` field. Off mode is the base prompt only.
- No live prompt hot reload while Jarvis is running.
- No Status Console editor for prompt files in this story.
- No change to memory write tools or memory file caps.
- No display, logging, or storage of reasoning traces.
- No model or backend change beyond the existing `think` value already sent
  for each `ReasoningLevel`.

## Design decisions

- **Prompt references are prompt-only syntax.** The `@file` convention lives
  in prompt configuration, not in the generic TOML section builder, so it
  does not become accidental magic for unrelated settings.
- **Bad references fail startup.** A configured prompt section is a promise
  that the model will see that text. Missing files, unreadable files, empty
  resolved prompts, and illegal paths raise `ConfigError`.
- **Path traversal is rejected, not normalized away.** Silent rewriting would
  make the config mean something other than what the user typed.
- **The `.jarvis` directory is the prompt-file root.** Even a leading slash
  in the reference is treated as a path inside that root, not as a filesystem
  absolute path.
- **Composition order:** base system prompt, memory/self prompt material,
  then the active reasoning-mode section. The mode-specific section is
  closest to the request, but cannot replace identity or memory unless the
  user explicitly writes contradictory prompt text.
- **Reasoning level is still sampled once.** Changing the level while a turn
  is in flight cannot alter that turn's already-built message list.

## Scope (ordered task cards, to be opened one at a time)

1. `task-v1.7.3-1-prompt-reference-config.md` - extend `PromptSettings`
   with optional reasoning prompt fields and prompt-file references; add pure
   config tests for literals, file reads, `./.jarvis/` anchoring, traversal
   rejection, unreadable/missing files, and empty resolved prompts.
2. `task-v1.7.3-2-effective-reasoning-prompt.md` - compose the effective
   system prompt at turn start from base prompt, memory files, and the sampled
   reasoning level; add orchestration tests proving the selected section is
   included only for the active level and only for that turn.
3. `task-v1.7.3-3-code-optimization.md` - read the touched config/runtime
   prompt code for duplicated logic, misplaced responsibility, and avoidable
   complexity; make only behavior-preserving cleanup with tests kept green.
4. `task-v1.7.3-4-docs-and-verification.md` - document the new `[prompts]`
   fields, `@` reference semantics, `.jarvis` root, off-mode behavior, and
   final verification state in config and user docs; run the standard pure
   checks.

## Acceptance criteria

- [ ] Existing configs continue to load unchanged and produce the same system
      prompt when no new fields are set.
- [ ] `reasoning_low`, `reasoning_medium`, and `reasoning_high` may each be
      omitted, literal text, or an `@` file reference.
- [ ] File references resolve only under `./.jarvis/`, reject `..`, and fail
      with a clear `ConfigError` when the resolved prompt cannot be read or is
      empty.
- [ ] A turn at `off` receives no extra reasoning prompt section.
- [ ] A turn at `low`, `medium`, or `high` receives exactly the section for
      its sampled level, after base prompt and memory material.
- [ ] Reasoning-token isolation is unchanged: `message.thinking` still never
      reaches TTS, history, UI text, journal content, or `ResponseToken`.
- [ ] `python -m pytest`, `python -m ruff format --check .`, and
      `python -m ruff check .` are green for the implementation tasks.

## Stop conditions

- Stop if adding prompt references requires weakening the existing strict
  config behavior for unknown keys, wrong types, or empty prompts.
- Stop if the `.jarvis` anchoring rule conflicts with an existing project
  path convention not recorded in this story or `PROJECT.md`.
- Stop if the implementation would require generic file-reference semantics
  for all config fields rather than an isolated prompt-only resolver.
- Stop if composing the prompt per reasoning level requires changing the
  backend message shape or the reasoning-token isolation rule.
- Stop if tests cannot cover the resolver and effective prompt composition
  without live Ollama or hardware.
