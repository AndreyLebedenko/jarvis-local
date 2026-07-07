# Story v1.2.4: Status Console control plane

**Status:** Backlog.
**Roadmap:** `tasks/roadmap-v1.2-v1.3.md`
**Release:** v1.2.4
**Related:** `tasks/task-ui-09-status-console-shutdown-control.md`

## User-facing goal

Let the live Status Console control core runtime actions that already have
engine support: clean shutdown first, then a small restart-to-apply
configuration surface for model and microphone selection.

## Boundaries

- Shutdown must use the same clean path as the existing shutdown hotkey.
- Configuration iteration 1 is restart-to-apply only.
- The Status Console writes only the UI config layer.
- Do not implement live reconfiguration.
- Do not fake module reset success where no engine reset API exists.
- A lifecycle controller is created only if `task-ui-09` hits its stop
  condition; it is not assumed before implementation.

## Acceptance Criteria

- [ ] `task-ui-09-status-console-shutdown-control.md` is completed.
- [ ] Desktop Status Console exposes a guarded Shutdown control.
- [ ] Shutdown request is visible in system events before teardown when the
      event panel is still available.
- [ ] Clean shutdown cancels background tasks, awaits pending TTS/sound cues,
      unsubscribes bus handlers, and unregisters hotkeys.
- [ ] Configuration menu iteration 1 supports model and microphone selection.
- [ ] Config layering is documented and tested:
      built-in defaults, `config.toml`, then `config.ui.toml`.
- [ ] Restart-to-apply is visible in UI and recorded in `PROJECT.md`.
- [ ] Source unavailability degrades dropdowns to current configured values.

## Task Card Sequence

1. Status Console shutdown control.
   - Start from existing `task-ui-09`.
   - Stop and split lifecycle controller only if the card's stop condition
     triggers.

2. Configuration layering contract.
   - Define built-in, user config, and UI config precedence.
   - Record restart-to-apply behavior.

3. Configuration menu iteration 1.
   - Model dropdown from local Ollama tags.
   - Microphone dropdown from sounddevice devices.
   - Pending restart indicator.

4. Manual verification handoff.
   - Real WebView shutdown.
   - Real model/microphone source degradation behavior where applicable.

## Stop Conditions

- Stop if exposing shutdown through `StatusConsoleApi` creates a circular
  dependency with `run()` lifecycle ownership.
- Stop if model or microphone enumeration requires blocking the UI thread.
- Stop if restart-to-apply semantics conflict with existing config loading.
