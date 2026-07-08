# Task: graphify semantic documentation extraction

Status: Completed.

## Summary

Added a manual graphify wrapper command for full semantic extraction across
code and documentation. This lets agents refresh the knowledge graph after
meaningful changes to `PROJECT.md`, agent instructions, README/spec files,
task cards, or bug reports.

## Boundary

- Keep `tools/graphify.ps1 update` as the fast code-only path used by local
  hooks.
- Add a separate semantic path for code+docs extraction.
- Do not make semantic extraction part of CI or automatic hooks.
- Use a generative chat/instruct Ollama model for semantic extraction, not an
  embedding-only model.

## Acceptance Criteria

- `tools/graphify.ps1 semantic` runs graphify's headless full extraction.
- Local Ollama defaults to `gemma4:12b-it-qat` with request concurrency `1`.
- `tools/graphify.ps1 docs` is available as a human-friendly alias.
- Agent instructions document when to run semantic extraction and which model
  class it requires.
