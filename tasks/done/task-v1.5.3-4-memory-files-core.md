# Task v1.5.3-4: Memory files core

**Status:** Completed.
**Story:** `tasks/story-v1.5.3-memory-layer-a.md`
**Depends on:** nothing in this story; independent of tasks 1-3.

## Summary

Introduce memory.md and self.md as size-capped local files whose
content is injected into the system prompt at session start. Core and
config only; no transport, no UI.

## Context you need

- `src/jarvis/core/config.py`: settings pattern (`PromptSettings`,
  validation style, `config.example.toml` conventions) - add a
  `[memory]` section (paths, per-file caps; `fork_seed_max_chars` may
  already exist from task-2 depending on landing order - coordinate,
  do not duplicate).
- `src/jarvis/app.py`: where the system prompt is composed and where a
  session starts (context reset, fork, process start) - injection must
  happen at every session start, from one code path, not three copies.
- Cross-cutting rule 7 (`tasks/roadmap-v1.5.1-v1.7.md`): size caps and
  auditability are the contract.

## Boundary

- Read path only: loading, capping, injection. No write/edit API (task
  5), no UI (task 6), no model-initiated writes (v1.6.1).
- Missing files are a normal state (fresh install), not an error.
- Do not restructure the existing prompt composition beyond adding the
  injection seam.

## Requirements

- Config: file locations (default: a `memory/` directory beside the
  journal root - state the resolved default in the card outcome) and a
  per-file character cap (proposed default 8000 chars).
- Loader reads each file as UTF-8; a file over its cap is truncated at
  the cap for injection with a logged warning naming the file and both
  sizes - never silently, and the file on disk is never modified.
- Injection composes: base system prompt, then self.md (persona), then
  memory.md (durable facts), each under a short fixed delimiter so the
  model can tell curated memory from the base prompt; empty/missing
  files inject nothing (no empty delimiter blocks).
- Content is sampled at session start (process start, context reset,
  fork); mid-session file edits do not change the live session.
- The loader is a pure, injectable seam so tests need no real files on
  the runtime paths.

## Acceptance criteria

- [ ] Tests cover: missing files, empty files, normal injection order
      and delimiters, over-cap truncation with warning, UTF-8 content
      (Russian text), and session-start sampling (an edit after start
      does not leak into the live prompt).
- [ ] `config.example.toml` documents the new settings.
- [ ] `python -m pytest` and Ruff checks are green.
