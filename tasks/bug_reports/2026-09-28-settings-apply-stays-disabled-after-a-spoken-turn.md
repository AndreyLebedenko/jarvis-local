# Bug report: Settings "Apply" stays disabled after a spoken turn

Commit: `526c950` (main) plus the uncommitted `feature/tts-language-mode`
working tree. Observed during that task's manual handoff on 2026-09-28.

**Status:** Preliminary. Cause not verified; not yet known whether `main`
reproduces it. Deferred by the owner so the TTS language mode handoff can
continue.

## Symptoms

- Fresh start: Settings view -> change any field -> "Apply" is enabled and
  saving works.
- After at least one exchange with the model, opening the Settings view
  leaves "Apply" disabled (dimmed), before and after changing a field.
  Observed with a typed request (Journal "Message Jarvis"), not a voice
  one; the answer was spoken (response mode Voice / Text+voice, TTS on).
- The Model and Microphone drop-downs still show full option lists, but a
  `<select>` keeps its options from an earlier load, so this does not prove
  that fresh options arrived.
- `logs/jarvis.log` shows `GET /api/tags` on each reopen of the Settings
  view (11:44:37, 11:45:33), and no "Failed to enumerate microphone
  devices" warning.

## How "Apply" is enabled (current code)

`_updateApplyButtonEnabled()` in `src/jarvis/ui/status_console_ui/app.js`:
enabled only when `_modelOptionsLoaded && _microphoneOptionsLoaded &&
_configInputsValid()`. `refreshSettingsOptions()` resets both flags (button
disabled) every time the Settings view opens and re-requests
`request_model_options` / `request_microphone_options`. The flags are set
only when the matching `model_options` / `microphone_options` state delta
arrives. There is no dirty tracking; changing a field does not matter.

## Suspected cause (hypothesis, unverified)

The microphone options request never completes after a spoken turn:
`StatusConsoleApi._request_microphone_options_async()` ->
`asyncio.to_thread(enumerate_input_devices)` -> `sd.query_devices()`
(`src/jarvis/audio/devices.py`). Model options do complete (`/api/tags` in
the log), and enumeration failures are logged, so a hang fits the evidence
better than an error.

What a spoken turn does to PortAudio that a fresh start has not done, even
for a typed request:

- TTS playback through `sd.play` / `sd.wait` (`TtsOutput._default_play`).
- Microphone auto-pause: `Orchestrator.on_response_token()` ->
  `AudioInput.auto_pause_for_speech()` -> `stream.stop()` on the capture
  stream, then resume after speech (`src/jarvis/audio/input.py`,
  `_apply_combined_state`).

Other candidates not excluded: an exception inside `_configInputsValid()`
(for example a missing route element) after some state delta, or the
`microphone_options` delta not reaching the page.

## Temporary decision

Not fixed. The TTS language mode handoff works around it: every step
changes Settings right after a fresh start (it needs a restart anyway).
Chosen over investigating now because the owner deferred it, and nothing in
the feature branch touches the options/Apply path (only the new select's
population and the Apply payload), so it is unlikely to be caused by that
branch - but that is by code inspection, not by a run on `main`.

## Next steps (for whoever picks this up)

1. Reproduce on `main` (`git stash -u`, run, one typed spoken turn, open
   Settings, wait 15-20 s, `git stash pop`). Human-run: hardware.
2. Discriminate the audio cause, each from a fresh start with a typed
   request:
   - microphone asleep (`[hotkeys].mic_sleep_toggle`, default
     `ctrl+alt+m`) before the request: playback only, no capture
     pause/resume;
   - TTS muted (TTS chip "Mute") with the microphone awake: capture
     pause/resume still happens (it is triggered by the first response
     token, not by audio), no playback.
3. Add start/finish logging around the enumeration in
   `_request_microphone_options_async()` to confirm or rule out the hang.

## Boundaries

A fix must not re-enable "Apply" before real options arrive: the
empty-model regression guard (2026-07-07, comment above
`_modelOptionsLoaded` in `app.js`) exists for that reason. If enumeration
can hang, the likely shape is a bounded wait that degrades to the current
value with the existing "microphone options failed" event, not skipping
the microphone flag.
