# Task: Update project verification policy

**Story:** `tasks/story-v1.2.2-project-verification-contract.md`
**Status:** Backlog.
**Release:** v1.2.2

## Summary

Update project documentation so cloud CI is allowed for pure checks while the
runtime locality guarantee remains intact.

## Current Boundary

- Edit policy documentation only.
- Runtime code is out of scope.
- GitHub Actions workflow is out of scope for this task.

## Acceptance Criteria

- [ ] `AGENTS.md` distinguishes runtime locality from pure CI verification.
- [ ] `PROJECT.md` records the same decision as project architecture.
- [ ] Documentation says CI may install dependencies from the network.
- [ ] Documentation says Jarvis runtime must not require network access beyond
      the configured local Ollama endpoint.
- [ ] Documentation excludes live Ollama, model downloads, secrets, hardware,
      GPU/VRAM, WebView visual review, microphone, speakers, global hotkeys,
      and screen capture from CI.

## Verification

- Read updated docs with `Get-Content -Raw -Encoding UTF8`.
- Run `python -m pytest` unless a documentation-only review explicitly defers
  it.

## Stop Conditions

- Stop if the new CI wording conflicts with another project guarantee.
- Stop if any hardware/live check is still described as CI-runnable.
