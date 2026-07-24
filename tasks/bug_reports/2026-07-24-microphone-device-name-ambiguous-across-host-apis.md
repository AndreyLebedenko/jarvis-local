# Microphone device name is ambiguous across host APIs, so a selected device never opens

**Detected at commit:** `d40150c` (task v1.6.2-7 closed).
**Detected during:** the task v1.6.2-8 LAN camera release checklist, which
needs a live Jarvis. Not caused by camera work; the camera path is
unrelated and unaffected.
**Reported by:** owner, 2026-07-24.

## Symptoms

Jarvis starts normally, plays the listening cue, serves the Status
Console, and answers nothing at all - it does not react to speech for the
entire session. Nothing in the running log says why. The failure only
becomes visible at shutdown, where the microphone task is reported as
having raised instead of exiting cleanly:

```
ValueError: Multiple input devices found for 'Microphone (Yeti X)':
[3] Microphone (Yeti X), MME
[13] Microphone (Yeti X), Windows DirectSound
[25] Microphone (Yeti X), Windows WASAPI
[46] Microphone (Yeti X), Windows WDM-KS
```

Reproduced on two consecutive runs. The second run had no config change of
its own: `[microphone].device = "Microphone (Yeti X)"` was already
persisted in `config.ui.toml` by the first run's Settings save, so the
state is sticky until that file is edited.

## Suspected cause

Windows exposes one physical microphone once per host API, and PortAudio
lists each as a separate device with an identical `name`. Two places
assume the name identifies a device:

- `src/jarvis/ui/status_console.py:462`, `_default_microphone_options_source()`
  returns bare `device["name"]` values for every input device. On this
  machine that is four identical `Microphone (Yeti X)` entries, and the
  selector cannot show which is which.
- `src/jarvis/audio/input.py:52`, `_default_stream_factory()` passes that
  name straight to `sd.InputStream(device=...)`. PortAudio resolves a
  string by matching it against device names, finds four matches, and
  raises `ValueError` rather than picking one.

So the Settings selector offers a value that the capture path cannot open.
The default `device = ""` is unaffected: it passes `device=None` and
PortAudio resolves its own default by index, never by name. That is why
this survived until a device was explicitly selected.

A second, independent defect makes the first one invisible: the
microphone loop's failure does not surface at the time it happens.
`run_microphone_loop()` raises into a background task whose exception is
only observed during shutdown teardown, so a user gets a silently deaf
assistant with a healthy-looking console. The microphone chip confirms
this by construction: `ModuleHealthTracker` only moves it on
`MicSleepToggled`, so a loop that never started still reads as listening.

Note that `manual/manual_check_microphone_devices.py` already models
`host_api` per device (task v1.5.1-4). The knowledge existed in the manual
check and never reached the selector or the capture path.

## Temporary decision

No fix in task v1.6.2-8. That card's boundary is documentation and human
verification of the LAN camera, and this is neither; folding an audio
input fix into it would put an untested capture-path change into a
release-verification commit.

The LAN checklist is not blocked by this: the Journal tab's text input
drives a normal turn, tool calls included, so every camera step can be
verified by typing instead of speaking.

Workaround for the owner in the meantime: remove the `[microphone]`
section from `config.ui.toml` to fall back to the system default device.

Chosen over the nearby alternatives:

- *Fix it inline now.* Rejected - it needs a device-identity design
  decision (below) and human-run hardware verification of its own, which
  is exactly what a release-verification card must not absorb.
- *Only dedupe the selector list.* Rejected as a complete fix: it would
  hide the duplicates while still storing an ambiguous name, so the same
  `ValueError` returns whenever two different physical devices share a
  name, which is common for identical webcam or headset models.

## Future considerations and boundaries

- The real question is what identifies a device in config. A bare name is
  not enough; a PortAudio index is stable only within one enumeration and
  breaks when devices are added or removed. A name plus host API is the
  candidate that is both human-readable in config and resolvable, and it
  matches what the existing manual check already records.
- Host API choice is not cosmetic on Windows: PROJECT.md's 2026-07-11 and
  2026-07-18 entries tie MME to both the wake-recovery fix and the
  post-mute degraded-capture finding. Whatever design lands should let the
  human pick the host API deliberately rather than accept whichever match
  sorts first, and must not silently change which API an existing
  configuration resolves to.
- Backward compatibility: an existing bare-name config must keep working
  where the name is unambiguous, and fail with a message naming the
  candidates where it is not - a config error at startup, not a background
  task that dies quietly.
- The silent-failure half deserves its own attention regardless of how
  device identity is solved: a microphone loop that cannot start should
  degrade the microphone module chip and say so in the events panel at the
  moment it happens.
