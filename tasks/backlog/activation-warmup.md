# Backlog story: Activation and warmup

**Status:** Backlog.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Target:** v1.4.0 or later

## User-facing goal

Reduce perceived first-response latency after idle periods by giving the user a
clear activation trigger and warming the local Ollama model before the
completed utterance reaches the backend.

Jarvis currently works well when the voice channel is continuously active, but
the idle/return workflow is rough: after a pause, Ollama may unload the model
from VRAM according to `keep_alive`, and the first request pays the cold-start
load cost. This story adds deliberate activation and warmup without weakening
privacy or complicating the main voice pipeline.

## Boundaries

- Wake word is out of scope.
- Final WARMING timeout calibration waits for human-measured data.
- WARMING is runtime activation state, not privacy state or cloud warning.
- Triggering activation and warming Ollama are separate mechanisms joined by a
  shared activation entry point.
- Full migration of existing hotkeys to `HotkeyProvider` is handled by
  `tasks/story-v1.2.6-hotkey-provider-migration.md`.
- Linux/X11/Wayland hotkey implementation is out of scope for this story.

## Key Decisions

- Add `WARMING` as a runtime state between idle and listening/active capture.
- Configurable Ollama `keep_alive` reduces how often warmup is needed.
- Supported activation sources for this story:
  - push-to-talk through `HotkeyProvider`;
  - status-orb click as a UI fallback.
- Wake word through `openWakeWord` remains a separate future story because it
  needs its own false-positive measurement on the human's real environment.

## Acceptance Criteria

- [ ] `keep_alive` is configurable and passed to Ollama chat requests.
- [ ] `warm_up_model()` uses the existing `OllamaBackend`/`httpx` stack.
- [ ] Repeated warmup triggers do not create duplicate warmup requests.
- [ ] WARMING state is visually distinct from LISTENING, ERROR, and
      data-locality/cloud indicators.
- [ ] Speech captured during WARMING is buffered and submitted after readiness
      instead of dropped.
- [ ] Push-to-talk uses `HotkeyProvider`.
- [ ] Orb click uses the same activation path as push-to-talk.
- [ ] `day0_checks.py` includes human-run warmup and trigger checks.
- [ ] Human-confirmed timing is recorded in `PROJECT.md`.

## Task Card Sequence

1. `activation-warmup-task-1-ollama-keepalive-warmup.md`.
   - Configurable `keep_alive`.
   - Async `warm_up_model()`.

2. `activation-warmup-task-2-warming-runtime-state.md`.
   - WARMING runtime state.
   - Timeout and event logging.

3. `activation-warmup-task-3-ptt-hotkey-trigger.md`.
   - Push-to-talk trigger through provider path.

4. `activation-warmup-task-4-orb-click-trigger.md`.
   - Universal UI fallback trigger.

5. `activation-warmup-task-5-day0-checks-extension.md`.
   - Human-run timing and trigger verification.
   - Verified facts update.

## Open Questions

- What idle duration should count as the bursty-usage boundary: 5 minutes, 15
  minutes, or another value? This affects the default `keep_alive` and needs
  human measurement on real usage.
- Should activation produce a short audio or visual acknowledgement before VAD
  begins capturing, so the user knows the trigger was accepted?

## Stop Conditions

- Stop if WARMING requires a larger state-machine redesign than the story
  allows.
- Stop if audio buffering during WARMING conflicts with existing VAD/request
  boundaries.
- Stop if hotkey provider migration has not landed and the implementation would
  create a long-lived mixed privacy model.
- Stop if hardware timing data is required before a default can be chosen.
