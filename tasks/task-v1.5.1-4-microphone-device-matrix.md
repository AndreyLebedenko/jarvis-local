# Task v1.5.1-4: Microphone device-type quality and stability matrix

**Status:** Ready.
**Story:** `tasks/story-v1.5.1-stabilization.md`
**Depends on:** task-v1.5.1-1 (run the matrix on the fixed shutdown path,
so device findings are not confused with the known race).

## Summary

Add a human-run check script that exercises capture quality and stability
per microphone device type - USB and Bluetooth at minimum, plus whatever
built-in device the host has - and record the verified per-device-class
facts in `PROJECT.md` (owner request, 2026-07-18). The agent writes the
script and hands over exact commands; the human runs it and reports
output, per the Testing protocol.

## Context you need

- `manual/manual_check_audio_in.py`: the existing microphone manual
  check - extend it or add a sibling
  `manual/manual_check_microphone_devices.py`; either way, one script
  owns the device matrix.
- `src/jarvis/audio/input.py`: capture loop, sleep/wake with
  fresh-stream-per-resume (MME wake recovery), buffer invalidation,
  stall handling. The stale-buffer-replay and MME wake bug reports in
  `tasks/bug_reports/` document the device-dependent failure modes
  already seen live.
- Device selection: the config layer already supports choosing a capture
  device (`sounddevice.query_devices()`, v1.2.4 configuration menu); the
  script must make the device under test explicit in its output, never
  implicit via the system default.
- Bluetooth background: activating a Bluetooth headset microphone
  typically switches the headset to the low-quality telephony profile
  (HFP), which can also change the playback side and the effective
  sample rate. Treat profile switching, sample-rate renegotiation, and
  stream stalls as expected hazards to probe, not surprises.

## Boundary

- Checks and documentation only. Any defect found becomes a bug report
  under `tasks/bug_reports/` (per the story boundary: no capture-path
  fixes in this story unless the owner explicitly promotes one).
- The script must run fully offline and must not require the Jarvis app
  or Ollama to be running - `audio_in` machinery plus playback only.

## Requirements

The script guides the human through the same checklist per device:

1. **Identification.** List capture devices, let the human pick one, and
   print the device name, host API, and reported sample rate into every
   result line.
2. **Capture quality.** Record a spoken utterance through the real
   VAD/chunking path, save the exact wav the pipeline would publish, and
   play it back for a listening check (clean / distorted / dropouts).
   Save files under a check-output directory so a distorted capture is
   preserved as evidence (ties into the distorted-voice report's
   recurrence protocol, task-v1.5.1-3).
3. **Sleep/wake stability.** Several sleep/wake cycles; confirm capture
   resumes after each wake (the MME recovery behavior) and no stale
   buffer replays.
4. **Stall/disconnect.** Unplug the USB device / power off or
   out-of-range the Bluetooth device mid-capture, then reconnect:
   confirm no stale-buffer replay, no unhandled exception, and a clear
   log line; document whether capture recovers automatically or needs a
   sleep/wake cycle or restart (whichever is true - record honestly, do
   not require auto-recovery to pass).
5. **Clean shutdown.** End the script with the device still active and
   confirm no ERROR-level teardown output.
6. For Bluetooth additionally: note whether activating capture switched
   the headset profile and whether simultaneous playback (the listening
   check) degraded or interrupted capture.

## Acceptance criteria

- [ ] The manual script covers steps 1-6 and prints per-device result
      lines suitable for pasting into a report.
- [ ] Any pure-logic helpers added for the script (e.g. result
      formatting) have automated tests; the device interactions
      themselves are human-run by definition.
- [ ] The human has run the matrix on at least one USB and one Bluetooth
      microphone; results (including failures) are recorded in
      `PROJECT.md` as verified per-device-class facts, and any defect
      found is filed as its own bug report.
- [ ] `python -m pytest`, `python -m ruff check .`,
      `python -m ruff format --check .` green.

## Stop conditions

- Stop if a device class cannot reach the capture loop at all (e.g. a
  Bluetooth device invisible to PortAudio) - that is an environment/
  driver finding to record, not something to work around in code.
- Stop if the matrix reveals that a documented capture contract (buffer
  invalidation, fresh-stream resume) does not hold for a device class -
  record the failure and stop before changing capture code (story
  boundary).
