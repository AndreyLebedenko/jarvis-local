# Story v1.2.4: Status Console control plane

**Status:** Implementation complete - awaiting human manual verification
report (see `tasks/done/story-v1.2.4-task-4-control-plane-manual-handoff.md`).
Do not move this story to `tasks/done/` until that report lands.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.4
**Related:** `tasks/done/story-v1.2.4-task-1-shutdown-control.md`

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
- A lifecycle controller is created only if task-1 (shutdown control) hits
  its stop condition; it is not assumed before implementation. (It did
  not - see `tasks/done/story-v1.2.4-task-1-shutdown-control.md`'s
  Resolution.)

## Acceptance Criteria

- [x] `story-v1.2.4-task-1-shutdown-control.md` is completed.
- [x] Desktop Status Console exposes a guarded Shutdown control.
- [x] Shutdown request is visible in system events before teardown when the
      event panel is still available.
- [x] Clean shutdown cancels background tasks, awaits pending TTS/sound cues,
      unsubscribes bus handlers, and unregisters hotkeys.
- [x] Configuration menu iteration 1 supports model and microphone selection.
- [x] Config layering is documented and tested:
      built-in defaults, `config.toml`, then `config.ui.toml`.
- [x] Restart-to-apply is visible in UI and recorded in `PROJECT.md`.
- [x] Source unavailability degrades dropdowns to current configured values.

## Task Card Sequence

1. Status Console shutdown control.
   - See `tasks/done/story-v1.2.4-task-1-shutdown-control.md` (this card's
     content absorbed the old `task-ui-09-status-console-shutdown-control.md`
     during an earlier task-card rename; that file no longer exists).
   - Stop and split lifecycle controller only if the card's stop condition
     triggers.

2. Configuration layering contract.
   - See `tasks/done/story-v1.2.4-task-2-config-layering-contract.md`.
   - Define built-in, user config, and UI config precedence.
   - Record restart-to-apply behavior.

3. Configuration menu iteration 1.
   - See `tasks/done/story-v1.2.4-task-3-config-menu-iteration-1.md`.
   - Model dropdown from local Ollama tags.
   - Microphone dropdown from sounddevice devices.
   - Pending restart indicator.

4. Manual verification handoff.
   - See `tasks/done/story-v1.2.4-task-4-control-plane-manual-handoff.md`.
   - Real WebView shutdown.
   - Real model/microphone source degradation behavior where applicable.
   - Human report pending - this story stays open until it lands.

## Stop Conditions

- Stop if exposing shutdown through `StatusConsoleApi` creates a circular
  dependency with `run()` lifecycle ownership.
- Stop if model or microphone enumeration requires blocking the UI thread.
- Stop if restart-to-apply semantics conflict with existing config loading.
