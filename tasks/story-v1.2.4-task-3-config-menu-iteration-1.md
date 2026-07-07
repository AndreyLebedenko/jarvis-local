# Task: Configuration menu iteration 1

**Story:** `tasks/story-v1.2.4-status-console-control-plane.md`
**Status:** Backlog.
**Release:** v1.2.4
**Depends on:** `tasks/story-v1.2.4-task-2-config-layering-contract.md`

## Summary

Add the first Status Console configuration menu for model and microphone
selection with restart-to-apply semantics.

## Current Boundary

- Model and microphone only.
- Status Console writes only `config.ui.toml`.
- Do not implement TTS, language, voice, VAD, or live reconfiguration here.

## Acceptance Criteria

- [ ] Model selector reads from local Ollama `GET /api/tags`.
- [ ] Microphone selector reads from `sounddevice.query_devices()`.
- [ ] Source failure degrades each selector to the current configured value.
- [ ] Saving writes only the UI config layer.
- [ ] Pending restart state is visible.
- [ ] Pure tests cover payload/state behavior without live Ollama or real
      devices.

## Verification

- Run `python -m pytest`.
- Prepare manual handoff for real source enumeration if needed.

## Stop Conditions

- Stop if source enumeration blocks the UI thread.
- Stop if pure tests require live Ollama or real audio devices.
- Stop if writing `config.ui.toml` risks overwriting user `config.toml`.
