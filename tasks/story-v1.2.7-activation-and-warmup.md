# Story v1.2.7: Activation and warmup

**Status:** Backlog.
**Roadmap:** `tasks/roadmap-v1.2-v1.3.md`
**Release:** v1.2.7
**Detailed story:** `tasks/story-voice-trigger-warmup.md`

## User-facing goal

Reduce perceived first-response latency after idle periods by giving the user a
clear activation trigger and warming the local Ollama model before the
completed utterance reaches the backend.

## Boundaries

- The detailed activation design lives in `tasks/story-voice-trigger-warmup.md`.
- Existing task cards `task-01` through `task-05` define the implementation
  slices.
- Wake word is out of scope.
- Final WARMING timeout calibration waits for human-measured data.
- WARMING is runtime activation state, not privacy state or cloud warning.

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

1. `task-01-ollama-keepalive-warmup.md`.
   - Configurable `keep_alive`.
   - Async `warm_up_model()`.

2. `task-02-status-orb-warming-state.md`.
   - WARMING runtime state.
   - Timeout and event logging.

3. `task-03-ptt-hotkey-provider.md`.
   - Push-to-talk trigger through provider path.

4. `task-04-orb-click-trigger.md`.
   - Universal UI fallback trigger.

5. `task-05-day0-checks-extension.md`.
   - Human-run timing and trigger verification.
   - Verified facts update.

## Stop Conditions

- Stop if WARMING requires a larger state-machine redesign than the story
  allows.
- Stop if audio buffering during WARMING conflicts with existing VAD/request
  boundaries.
- Stop if hotkey provider migration has not landed and the implementation would
  create a long-lived mixed privacy model.
- Stop if hardware timing data is required before a default can be chosen.
