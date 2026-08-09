# Task: TTS enable/disable - runtime toggle plus config default

**Story:** `tasks/story-ui-ux-maturity.md`
**Status:** Proposed. Independent of tasks 1-2 (may be done in parallel);
its Status-view toggle benefits from task 1's focus/radiogroup work but
does not require it.
**Release:** post-v1.8.0 (owner to assign).
**Created:** 2026-08-09.
**Scope class:** engine + config + transport + front-end. The only task in
this story that crosses the thin-client boundary.

## Summary

Jarvis always speaks when a route is configured: `TtsOutput` subscribes to
`ResponseToken`/`ResponseComplete` (wired in `app.py`, `wire()`), and
`TtsSettings` has only `languages` - no on/off. The owner wants to turn
speech off, both as a live dashboard toggle and as a default-mode option
in config.

TTS is *output*, not a sensor, so unlike the microphone/MCP controls a
plain runtime toggle is acceptable. It must, however, stay off the
model-delegable allowlist (roadmap cross-cutting rule 9): this is a
UI/config control only.

## Settled sub-decisions (owner, 2026-08-09)

- Mute silences **speech only**. Sound cues (`SoundCuePlayer`) keep
  playing - they are the user's feedback that Jarvis heard and finished.
- The runtime mute is **not** self-persisting. The default lives in config
  (`[tts].enabled`); startup seeds the initial runtime value from it.
  Toggling at runtime does not rewrite config (mirrors visibility mode
  being runtime-only while its config analogues persist explicitly).

## Proposed direction

1. **Runtime state owner** `TtsMuteState` (small, single-responsibility,
   like `VisibilityModeState`/`ReasoningLevelState`): holds enabled/muted,
   publishes a `TtsSpeechEnabledChanged` bus event on change. Seeded at
   startup from `settings.tts.enabled`.

2. **Mute-gating in `TtsOutput`**: `on_token`/`on_response_complete`
   short-circuit while muted (no synthesis scheduled), and switching to
   muted calls the existing `cancel()` so in-flight speech stops at once.
   The gate reads the state owner; `TtsOutput` gains no persistence
   responsibility.

3. **Control command** `set_tts_enabled` (boolean): validated in
   `transport.py` `_dispatch_control` (add handler + `ControlApi` method +
   `StatusConsoleApi.set_tts_enabled` scheduling the state change), exactly
   like `set_mcp_enabled`.

4. **Status projection + honest indication**: project `tts` (enabled +
   effective status) into `UiStateStore`'s snapshot/delta; render a toggle
   on Status and reflect state truthfully - **muted** (user turned speech
   off) is distinct from **off-by-failure** (engine load failed,
   `TtsEngineLoadFailed`) and from **speaking** - reuse the module-health
   mechanism rather than inventing a parallel indicator.

5. **Config default** `[tts].enabled` (bool, default true) on
   `TtsSettings`, parsed in `_build_tts_section`, and plumbed through
   `UiConfigSelection` / `write_ui_config` / the Settings form so the
   dashboard's default-mode option persists restart-to-apply. Document it
   in `config.example.toml`. In the Settings UI it renders as a master
   on/off switch at the **top** of the "Синтез речи (TTS)" section,
   gating the existing per-language voice block beneath it (which today
   is a wall of raw fields with no on/off control above them).

6. Update `PROJECT.md` in the same commit if any settled TTS fact changes
   (per CLAUDE.md rule: architectural decision changes travel with the
   code).

## Boundary

- Speech only; sound cues unaffected.
- Runtime toggle does not persist; config default is a separate,
  restart-to-apply value.
- TTS stays off the model-delegable allowlist - no builtin tool, no voice
  command path in this task.
- No change to the verified Ollama media transport or the TTS
  routing/engine-selection contracts.

## Acceptance criteria

- [ ] A single owner holds TTS speech-enabled state and publishes its
      change event; startup seeds it from `[tts].enabled`.
- [ ] While muted, `TtsOutput` schedules no synthesis, and switching to
      muted cancels in-flight speech; sound cues still play.
- [ ] `set_tts_enabled` is validated and dispatched like `set_mcp_enabled`;
      a bad payload raises `ProtocolError`.
- [ ] The Status view shows a working toggle and distinguishes muted vs
      off-by-failure vs speaking honestly.
- [ ] `[tts].enabled` parses, defaults to true, round-trips through
      config save, and is documented in `config.example.toml`.
- [ ] Settings renders the default as a master on/off switch at the top of
      the "Синтез речи (TTS)" section, gating the per-language voice block.
- [ ] Pure tests cover: mute-gating in `TtsOutput` (no synthesis while
      muted, cancel on disable, cues untouched), `[tts].enabled`
      parse/write round trip, and `set_tts_enabled` validation.
- [ ] Human hardware handoff prepared for live speaker on/off (per the
      testing protocol - agent does not run speaker tests).
- [ ] `python -m pytest` passes; `ruff check` and `ruff format --check`
      are clean.

## Verification record

(to be filled at completion)
