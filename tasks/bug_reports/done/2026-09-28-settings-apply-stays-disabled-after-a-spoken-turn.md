# Bug report: Settings "Apply" stays disabled after a spoken turn

Commit: `526c950` (main) plus the uncommitted `feature/tts-language-mode`
working tree. Observed during that task's manual handoff on 2026-09-28.

**Status:** Fixed (2026-09-30, branch `fix/settings-apply-after-spoken-turn`).
Verified by the human-run check below, with the caveat recorded under
"Human-run result".

## Resolution (2026-09-30)

The spoken turn is incidental. The real trigger is **the second opening of
the Settings view in the same run**, with or without any turn in between.

`UiStateStore._replace()` (`src/jarvis/ui/transport.py`) publishes a state
delta only when the value differs from the stored one. The first Settings
open replaces the empty initial `model_options` / `microphone_options`, so
both deltas arrive and "Apply" enables. Every later open re-arms "Apply" to
disabled (`refreshSettingsOptions()` in `app.js`) and re-requests options;
the engine answers with the same lists, `_replace()` swallows them as
"unchanged", no delta reaches the page, and both `...Loaded` flags stay
false. The log matched: `/api/tags` on every reopen (the request is served),
no enumeration warning (nothing failed). The PortAudio hang hypothesis
below is not needed to explain the evidence.

Fix: `set_model_options()` and `set_microphone_options()` now always emit a
delta (new `UiStateStore._set()`), because options are an answer to a
request, not state that merely changed. Regression test:
`test_state_store_answers_every_options_request_even_when_options_are_unchanged`
in `tests/test_ui_transport.py` (failed before the fix).

### Human-run check

1. Start: `python -m jarvis --status-console` (README, "Usage").
2. In the Status Console click the view toggle "Settings"
   (`index.html`, `#viewToggle`, `data-view="settings"`). Wait until the
   Model and Microphone lists are filled; "Apply" must be enabled.
3. Click the "Journal" view, then "Settings" again - no turn needed.
   Before the fix "Apply" stayed dimmed here. Expected now: enabled within
   a second or two.
4. Send one typed message with TTS on (the original scenario), wait for the
   spoken answer to finish, open "Settings" again. Expected: "Apply"
   enabled.
5. Report step 3 and 4 results. If step 4 still fails while step 3 passes,
   the PortAudio hypothesis below becomes live again.

### Human-run result (owner, 2026-09-30)

- Step 2: "Apply" enabled immediately.
- Step 3 and later reopens, including after spoken turns: "Apply" goes
  dimmed for a fraction of a second, then enables. That flash is the
  expected mechanism - re-armed on open, enabled when both options deltas
  arrive - so the observation supports this fix as the cause, not an
  accidental one.
- Repeated attempts to reproduce the original symptom failed.

Caveat: the pre-fix failure on a plain second open (no turn) was shown by
the regression test and by code reading, not re-run live on the unfixed
build. The conclusion is therefore "consistent with and most likely
explained by the fix", not proven by a live before/after pair. If the
symptom returns after a spoken turn only, reopen with the PortAudio
hypothesis below.


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
