# First capture after hardware microphone mute is degraded

**Detected commit:** `98f389f` plus uncommitted task-v1.5.1-4 manual matrix
script on branch `codex/task-v1.5.1-4-microphone-device-matrix`.
**Detected during:** task-v1.5.1-4 human-run microphone device matrix,
2026-07-18.
**Status:** Open.

## Symptoms

The earlier "distorted voice in a journaled utterance recording" class of bug
reproduced during the device matrix on both a USB microphone and a Bluetooth
headset microphone, using the same pattern: record clean chunks, hold a
hardware mute for about 3 minutes, unmute, wait for the device's ready signal,
then immediately dictate. The first post-unmute capture is degraded; the next
capture recorded immediately afterward is clean again.

USB device and evidence:

- device: `Microphone (Yeti X)`;
- PortAudio host API: `MME`;
- reported device sample rate: 44100.0 Hz, 2 input channels;
- Jarvis captured evidence wavs at the pipeline rate, 16 kHz mono;
- matrix output directory:
  `manual_check_microphone_devices_out/20260718-214650-1-Microphone_Yeti_X/`;
- degraded evidence file: `utterance-007.wav`.

Human-observed sequence:

1. Several chunks were recorded with normal quality.
2. The microphone was muted using its hardware mute button.
3. The device was left muted for about 3 minutes.
4. The microphone was unmuted, the tester waited for the device's green
   "ready" signal, and immediately started dictating. The resulting
   `utterance-007.wav` had low quality.
5. Without changing settings or pressing anything, the tester immediately
   recorded the next chunk. Its quality was good and matched the initial
   chunks.

Bluetooth device and evidence:

- device: `Headset (TicPods ANC)`;
- PortAudio host API: `MME`;
- reported device sample rate: 44100.0 Hz, 1 input channel;
- matrix output directory:
  `manual_check_microphone_devices_out/20260718-215925-4-Headset_TicPods_ANC/`;
- degraded evidence file: `utterance-003.wav`;
- immediate follow-up clean file: `utterance-004.wav`.

The matrix logs show clean shutdown for both runs.

## Suspected current cause

Unknown. The defect is capture-side and transient: the first post-hardware-mute
capture can be degraded even though the next capture on the same still-active
stream returns to normal quality. Reproduction on both USB and Bluetooth makes
this less likely to be a single physical microphone fault, while both observed
devices used PortAudio MME.

Initial waveform inspection of the preserved wavs did not show clipping:

- USB degraded `utterance-007.wav`: 16 kHz, 2.0 s, RMS about 0.00639, peak
  about 0.04196, and 0% near full-scale samples.
- Bluetooth degraded `utterance-003.wav`: 16 kHz, 0.8 s, RMS about 0.00305,
  peak about 0.02618, and 0% near full-scale samples. Clean Bluetooth
  neighbors were much louder (`utterance-002.wav` RMS about 0.03860, peak
  about 0.24567; `utterance-004.wav` RMS about 0.04088, peak about 0.27618).

This points away from simple amplitude saturation and toward a transient
device, driver, buffering, profile, or stream-state artifact after a hardware
mute stall.

## Temporary decision

No capture-path fix in task-v1.5.1-4. This task is a matrix and evidence
handoff; the story boundary says any defect found becomes its own bug report.

Chosen over a blind filter, gain change, or stream-restart workaround because
the failure mode is not yet classified and the second immediate chunk is clean.
A capture-path change here could degrade normal captures without proving it
addresses the device-specific post-mute transition.

## Future considerations and boundaries

- Preserve the evidence wavs from the output directory until this report is
  resolved.
- Re-run USB and Bluetooth with controlled post-unmute delays to learn whether
  the first clean capture requires time after the device-level ready signal.
- Compare MME against WASAPI for the same devices if PortAudio exposes both.
- Check whether closing and reopening the stream after a long hardware mute
  prevents the first post-mute degraded capture, but only under a dedicated
  capture-path task.
- Keep this separate from stale-buffer replay unless logs show the
  `listening -> thinking` near-instant signature or old pre-mute speech is
  replayed. The reported symptom here is degraded quality of fresh speech, not
  confirmed stale utterance publication.
