# Task: Configuration menu iteration 1

**Story:** `tasks/story-v1.2.4-status-console-control-plane.md`
**Status:** Completed.
**Release:** v1.2.4
**Depends on:** `tasks/done/story-v1.2.4-task-2-config-layering-contract.md`

## Summary

Add the first Status Console configuration menu for model and microphone
selection with restart-to-apply semantics.

## Current Boundary

- Model and microphone only.
- Status Console writes only `config.ui.toml`.
- Do not implement TTS, language, voice, VAD, or live reconfiguration here.

## Acceptance Criteria

- [x] Model selector reads from local Ollama `GET /api/tags`.
- [x] Microphone selector reads from `sounddevice.query_devices()`.
- [x] Source failure degrades each selector to the current configured value.
- [x] Saving writes only the UI config layer.
- [x] Pending restart state is visible.
- [x] Pure tests cover payload/state behavior without live Ollama or real
      devices.

## Verification

- Run `python -m pytest`.
- Prepare manual handoff for real source enumeration if needed.

## Stop Conditions

- Stop if source enumeration blocks the UI thread.
- Stop if pure tests require live Ollama or real audio devices.
- Stop if writing `config.ui.toml` risks overwriting user `config.toml`.

## Resolution

**Config plumbing:**

- `config.py` gained `MicrophoneSettings` (`device: str = ""`, empty
  meaning sounddevice's default input device) and `write_ui_config()` -
  the only writer of `config.ui.toml` anywhere in the project, always
  rewriting the whole file with exactly `[backend].model` and
  `[microphone].device` (iteration 1 has nothing else to preserve there),
  never opening `config.toml` (structurally cannot risk overwriting it -
  the Stop Condition never had a code path to trigger). Values are
  `json.dumps()`-escaped into TOML basic strings (stdlib `tomllib` is
  read-only; this avoids a new TOML-writing dependency).
- `audio_in.py` gained `stream_factory_for_device(device)`, binding
  `config.microphone.device` into a `StreamFactory` via
  `functools.partial` without changing `AudioInput`'s constructor or the
  `StreamFactory` type (every existing fake-injecting test is unaffected).
  `main.py`'s `build_app()` uses it when `audio_input` is not injected -
  this is what makes microphone selection actually restart-to-apply
  rather than a saved value nothing reads. Model selection needed no
  equivalent wiring: `backend.model` already flowed from
  `load_settings()` into `OllamaBackend` since before task-2.

**Config menu backend (`status_console.py`):**

- `StatusConsoleApi` gained `request_model_options()`/
  `request_microphone_options()`/`save_config_selection()`. Enumeration
  goes through injectable async sources (real defaults:
  `httpx.AsyncClient` GET to local Ollama's `/api/tags` with a 3 s
  timeout; `sounddevice.query_devices()` off-loop via
  `asyncio.to_thread()`) and degrades to `[current_value]` on any
  exception - satisfies "never live Ollama or real audio devices in a
  pure test" and "never blocks the caller."
- Results never reach a window directly from this class - matching every
  other piece of state here, they are published as bus events
  (`ModelOptionsAvailable`/`MicrophoneOptionsAvailable`) that `main.py`'s
  `wire_status_console()` turns into `push_model_options()`/
  `push_microphone_options()` calls, pushed to the desktop window only.
  `save_config_selection()` writes via `write_ui_config()` and publishes
  `UiConfigSaved`, turned into `push_pending_restart(True)`.
- **Desktop-only by Scope decision:** `TouchstripWindow` overrides all
  three new `push_*()` methods to raise `NotImplementedError`, the same
  pattern already used for `push_system_event()` - the touchstrip stays a
  narrow glance/actions surface, no settings menu.

**Front-end:** `index.html`/`demo.html` gained a collapsible "⚙
Настройки" panel (model/microphone `<select>`s + "Применить"), cyan
throughout (not amber/red - saving here only ever touches
`config.ui.toml`, applied on next restart, so it carries no
warning/severity coloring). `toggleConfigMenu()` re-fetches both
selectors' options every time the panel opens, never on close. An
empty-string microphone option renders as "(системный микрофон по
умолчанию)". A successful save shows an amber pending-restart banner
immediately - unlike every other control on this page, there is no engine
confirmation event to wait for, since nothing in the running process
changes until the next start.

**Verified live** via the Preview tools against `demo.html` (config panel
open/close, dropdown population from demo buttons simulating both a
success case and a degraded/enumeration-failure case, pending-restart
banner) and the real `index.html` (renders correctly, no console errors,
no hardcoded model name).

**Tests added:** `tests/test_config.py` (`MicrophoneSettings` parsing/
defaults, `write_ui_config()` round-trip through `load_settings()`, never
touching the base config file, quote/backslash escaping),
`tests/test_audio_in.py` (`stream_factory_for_device()` binding, via
`functools.partial` inspection only - never calls the real factory, which
would touch real hardware), `tests/test_main.py` (`build_app()` wires the
configured device into the stream factory; `wire_status_console()` routes
the three new events to the desktop surface only, never touchstrip),
`tests/test_status_console.py` (model/microphone options success +
degrade-on-failure paths, `save_config_selection()` writes only the UI
path and never the base config file, no-op-before-`set_loop()`,
touchstrip `NotImplementedError` guards, front-end structural checks).
`python -m pytest` passes (300 passed).

**Docs:** `config.example.toml` gained a documented `[microphone]`
section; `PROJECT.md`'s "Architecture v1.2.4" section gained a task-3
entry; `README.md`/`README.ru.md` mention the new config menu in the
Status Console overview and Features list.

## Manual handoff (real source enumeration)

Prepared here; not run by the agent (per CLAUDE.md's testing protocol -
live Ollama and real audio devices are human-run checks). Consolidated
further, if needed, by task-4.

```
python main.py --status-console
```

1. Click "⚙ Настройки" to open the config menu; confirm the Model
   dropdown populates from a real `GET /api/tags` (matches `ollama list`)
   and the Microphone dropdown populates from real input-capable devices
   (matches what Windows Sound settings shows as inputs), each defaulting
   to the currently configured value.
2. Stop the local Ollama service (or block port 11434) and reopen/refetch
   the panel: confirm the Model dropdown degrades to just the current
   configured value (no crash, no empty dropdown) and a WARN system event
   appears. Restart Ollama afterward.
3. Change the Model and/or Microphone selection and click "Применить":
   confirm the amber "restart to apply" banner appears immediately, and
   that `config.ui.toml` now exists with exactly those two values (and
   `config.toml`, if present, is untouched).
4. Restart Jarvis (`python main.py --status-console` again): confirm the
   newly selected microphone device is actually used for capture (speak
   into the new device only, if testing with more than one) and that
   `backend.model`'s pushed label matches the saved model.

Human report pending.
