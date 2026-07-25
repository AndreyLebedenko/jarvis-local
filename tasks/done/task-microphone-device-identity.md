# Task: Microphone device identity is name plus host API

**Status:** Completed. Owner-run hardware verification 2026-07-25: a
device selected in Settings now opens and captures. Automated tests and
Ruff green.
**Story:** `tasks/done/story-microphone-device-identity.md`
**Bug report:**
`tasks/bug_reports/2026-07-24-microphone-device-name-ambiguous-across-host-apis.md`

## Summary

Stop asking PortAudio to find a device by name. Resolve the configured
(name, host API) pair to a device index ourselves, in pure code, and pass
the index. Make the Settings selector offer and store both halves.

## Context you need

- `src/jarvis/audio/input.py:51`, `_default_stream_factory()`: passes the
  configured string to `sd.InputStream(device=...)`. PortAudio resolves a
  string by matching device names and raises `ValueError` on multiple
  matches. `device=None` (the `""` default) is unaffected - PortAudio
  resolves its own default by index.
- `src/jarvis/audio/input.py:324`: the stream is re-created on every
  active period, because a paused stream is closed by the context manager
  and Windows MME rejects `start()` on the old object. Resolution
  therefore belongs at stream creation, not once at startup: PortAudio
  indices are stable only within one enumeration.
- `src/jarvis/ui/status_console.py:487`,
  `_default_microphone_options_source()`: returns bare `device["name"]`
  for every input device, so four identical rows appear for one physical
  microphone.
- `manual/manual_check_microphone_devices.py:121`: already parses the
  `hostapi` index into a host API name (task v1.5.1-4). This is the
  knowledge that never reached the product; move it into the package
  rather than writing a second copy.
- `src/jarvis/core/config.py:445`, `MicrophoneSettings`; `write_ui_config()`
  at line 1316 writes the machine-owned `config.ui.toml` snapshot.
- `src/jarvis/ui/config_selection.py:33`, `UiConfigSelection`, and
  `validate_selection()` - the authority for what may be written.
- `src/jarvis/ui/status_console_ui/app.js:455`,
  `applyMicrophoneOptions()`: renders option elements whose value is the
  stored string, and `saveConfig()` at line 673 reads
  `micSelect.value` back.

## Boundary

- Device identity, resolution, and the selector that produces it.
- Reporting a failed resolution to the user is the next card. This card
  raises a typed error and lets it propagate exactly as today's
  `ValueError` does; it must not make the failure louder or quieter.
- No retry, no hotplug handling, no change to VAD or stream lifecycle.

## Requirements

- A new pure module `src/jarvis/audio/devices.py` owns input-device
  enumeration and resolution:
  - `InputDevice(index, name, host_api, default_sample_rate,
    max_input_channels)`.
  - Parsing from raw `sd.query_devices()` / `sd.query_hostapis()`
    mappings, skipping devices with no input channels.
  - `resolve_input_device(devices, name, host_api)` returning an index, or
    `None` for the empty name (the system default).
  - `MicrophoneDeviceError` for "no such device" and for "ambiguous name
    with no host API", carrying the candidate list in its message.
- A configured host API that matches nothing is an error, never a silent
  fallback to another host API (story decision 4).
- `MicrophoneSettings` gains `host_api: str = ""`; `""` means "resolve by
  name alone, and fail if that is ambiguous".
- `stream_factory_for_device(device, host_api)` enumerates at each stream
  creation and passes the resolved index to `sd.InputStream(device=...)`.
- The Status Console microphone selector offers one entry per
  (name, host API) pair, labelled so the two are distinguishable, and the
  save path writes both fields to `config.ui.toml`.
- `manual/manual_check_microphone_devices.py` imports the package module
  instead of parsing raw device mappings itself. Its pure tests move to
  the package's own test module.
- Automated tests, all pure: unambiguous name resolves; ambiguous name
  without host API raises and the message names every candidate; host API
  disambiguates; unknown name raises; unknown host API for a known name
  raises; empty name resolves to `None`; output-only devices are skipped;
  the selector payload carries both halves; a saved selection round-trips
  through `config.ui.toml` into `MicrophoneSettings`.

## Acceptance criteria

- [x] No code path passes a device *name* to `sd.InputStream`.
- [x] A bare unambiguous name in an existing config still resolves, to the
      same device it resolved to before.
- [x] The selector shows the host API of every offered device and stores
      it.
- [x] Device enumeration exists once in the package.
- [x] `python -m pytest` and Ruff are green.

## Outcome

Landed as specified. `src/jarvis/audio/devices.py` owns `InputDevice`,
the parsing that used to live in the manual check, and
`resolve_input_device()`; `MicrophoneDeviceError` names candidates in
every failing case. The selector, `MicrophoneOptionsAvailable`, the
transport payload, `UiConfigSelection`, and `write_ui_config()` all carry
the pair now, and the `<option>` value is the index into the option list
rather than either half, because neither is unique and a joining
delimiter can occur inside a device name.

`manual/manual_check_microphone_devices.py` lost its private copy of the
enumeration and imports the package module; its two pure enumeration
tests moved to `tests/test_audio_devices.py`, which is where the rest of
the resolution rules are pinned.

**Boundary note (outside the stated scope, done anyway):**
`options_payload()` in `status_console.py` was dead code whose docstring
claimed it was "the shared shape for both the model and microphone
selectors". This change made that claim false, so the function and its
test went rather than being left as a lie with no caller. Nothing
referenced it.

**Scope addition (owner UX request, 2026-07-25).** The device listing was
unreadable for Bluetooth headsets, which Windows reports as raw MMDevice
resource strings with an embedded newline - three of them in the owner's
own `--list-only` output, each spilling across two lines. `display_label()`
extracts the parenthesized friendly tail and collapses whitespace;
`InputDevice.label` exposes it as a derived property. Applied to the
Settings selector, the manual check's listing, its RESULT lines and output
directory names, and every resolution error message. The raw name stays
the identity everywhere it matters, and a test pins that the label never
reaches config or PortAudio. `MicrophoneOption` gained an optional
`label`, so the "is the configured device already listed" check now
compares (device, host_api) rather than whole dataclasses - otherwise a
configured Bluetooth headset would appear twice, once raw and once
readable.

**Deliberately not done:** the selector still offers the explicit "system
default" entry only when it is the configured value. Returning to the
default from the UI was already impossible before this card and stays
that way; recovery from a bad selection works by picking a real device,
so nothing here depends on it.
