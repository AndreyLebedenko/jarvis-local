# Microphone capture fails after user wake on MME

**Detected commit:** `8534c2b6cb0d0cd7bbefd866f7f4b375cd2b8202`
**Detected during:** v1.2.10 UI Transport manual verification, 2026-07-11

## Symptoms

After the user toggles the microphone asleep and then awake, Jarvis accepts
the wake hotkey and plays the wake cue, but subsequent spoken requests produce
no response. During shutdown, the microphone background task reports:

```text
sounddevice.PortAudioError: Error starting stream: Unanticipated host error
[PaErrorCode -9999]: 'Cannot perform this operation while media data is still
playing. Reset the device, or wait until the data is finished playing.'
[MME error 33]
```

The failure occurs at `audio_in.py`'s `stream.start()` after the wake event.
Once that task exits, no capture loop remains to publish utterances.

## Suspected cause

`AudioInput.run_microphone_loop()` stops one long-lived `sounddevice.InputStream`
on every pause/sleep transition and restarts that same object on wake. This was
the settled v1.1 design because it avoids wake latency. On the verified Windows
MME device, PortAudio rejects the restart while the audio device still reports
media playback. The exception is not recoverable inside the current loop, so it
terminates the microphone task.

This evidence conflicts with the previous assumption in `PROJECT.md` and
`tasks/done/task-09-microphone-sleep-mode.md` that the same stream is always
safe to restart in place.

## Temporary decision

Do not patch this inside v1.2.10 Task 4. That card is limited to manual
verification and documentation, and explicitly requires reporting behavioral
regressions rather than making ad hoc fixes. Keep the story awaiting human
verification.

Do not choose a recovery strategy yet. Recreating the stream after wake,
retrying `start()`, or changing the pause mechanism have non-obvious trade-offs
for privacy guarantees, stale-buffer invalidation, device latency, and the
existing auto-pause-during-speech path.

## Future considerations and boundary

- Create a dedicated microphone-recovery task before changing `audio_in.py`.
- Preserve the hard privacy boundary: no pre-sleep or pause-spanning samples may
  be published after wake.
- Add pure tests for the selected stream-failure/recovery policy; the real MME
  reproduction remains a human-run hardware check.
- Update `PROJECT.md` and the superseded task documentation only after a new
  design is selected and manually verified.
- The requested Russian wording (`Не используется`) and horizontal action-button
  layout are independent UI changes and also remain outside Task 4's "no new
  features" boundary.
