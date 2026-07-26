# Task v1.7.0-1: AEC spike (hard gate)

**Status:** Completed. No-go for desktop-speaker/general-hardware voice
barge-in; see closure note below. Verified facts recorded in
`PROJECT.md` ("Architecture v1.7.0 spike" section).
**Story:** `tasks/story-v1.7.0-barge-in.md`
**Depends on:** nothing in this story; gated tasks 2-4 as originally
planned. The story has since been re-scoped around this card's result -
see the story card for the current task sequence.

## Summary

Human-run spike proving whether echo cancellation can suppress Jarvis
hearing its own TTS output well enough to keep the mic open during
playback, while still reacting promptly to real user speech that
overlaps it. Candidate approaches are tried against real recordings and
the project's existing Silero VAD (not a new detector), and the results -
suppression quality, false-trigger rate, latency/CPU cost, dependency
choice - are recorded in `PROJECT.md` before any module code exists.

## Context you need

- `PROJECT.md`'s "No echo cancellation in v1.0" verified-facts entry:
  the self-hearing bug this spike must not reintroduce, and the two
  timing-window mitigations this story replaces
  (`Orchestrator.finish_turn()`'s busy-cooldown,
  `AudioInput.auto_pause_for_speech()`/`auto_resume_after_speech()`).
- The story card's "Why a spike gates this story" and "What is already
  known" sections - the open questions this spike must answer, and what
  is already settled (stream cancellation is not this spike's problem).
- `src/jarvis/core/config.py`'s `VadSettings` (`threshold`,
  `max_chunk_seconds`, `request_end_pause_seconds`,
  `resume_cooldown_seconds`) - the spike should feed the AEC residual
  through the project's actual VAD threshold, not an invented metric, so
  the result answers "would today's VAD do the right thing on this
  residual."
- `src/jarvis/audio/tts.py`'s `TtsOutput`/`OrderedPlayback` (how Jarvis's
  own speech is synthesized and played) and `src/jarvis/audio/input.py`'s
  `AudioInput` (mic capture via `sounddevice`/PortAudio) - the spike's
  far-end (speaker) and near-end (mic) signals should come from these
  real paths, not synthetic stand-ins, so results transfer to the real
  pipeline.
- Testing protocol: this is hardware-dependent - the agent writes the
  check script and hands over exact commands; the human runs it and
  reports output. Precedent for a spike-as-hard-gate: v1.3.1
  graded-reasoning spike, v1.4.0 tool-calling spike, v1.6.2 camera spike.

## Boundary

- A standalone check script (existing check-script conventions under
  `manual/`), not module code. Nothing lands in `src/jarvis` from this
  card.
- Any AEC library may be installed ad hoc for the spike (e.g. an
  adaptive-filter/NLMS implementation, `speexdsp` bindings, or a WebRTC
  audio-processing binding - exact candidates are the script author's
  research judgment at implementation time). Whether it becomes a real
  dependency is part of the recorded decision; `requirements.txt` is
  only touched when task 2 makes it real.
- Real-time streaming integration is not built here. Offline/batch
  processing of recorded near-end/far-end pairs is sufficient to answer
  the suppression-quality and false-trigger questions; added-latency
  cost may be estimated qualitatively rather than measured from a live
  loop.
- No OS-level Windows audio-enhancement toggles are assumed controllable
  from the script (PortAudio exposes no such knob); if a candidate
  needs one, record that as a finding, not an assumption.

## Requirements

- A script that, for a human sitting at a normal desk distance:
  - plays a real TTS-synthesized response (via `TtsOutput`/the existing
    engine, not a placeholder WAV) while simultaneously recording the
    mic, for at least two scenarios: (a) the human stays silent through
    the whole response (self-hearing case), and (b) the human speaks
    over Jarvis partway through, to simulate a real interruption
    (barge-in case);
  - captures the exact far-end (speaker) signal actually sent to the
    output device, so it can be used as the AEC reference;
  - applies at least one candidate AEC algorithm to the near-end
    recording using the far-end as reference, and reports suppression in
    dB for the self-hearing case;
  - feeds the AEC residual through the project's real Silero VAD at
    `config.vad.threshold` and reports: whether it still fires on the
    self-heard case (false positive) and whether it fires promptly on
    the real interrupt case (true positive) - this is the actual
    go/no-go signal, not the raw dB number alone.
  - repeats across at least: a quiet room, a room with harder surfaces
    (more reverb), and two speaker/mic distances typical of desk use.
- A short handoff document/section with exact commands, what to vary
  per run, and a result table (candidate approach, suppression dB,
  self-heard false-positive rate, real-interrupt true-positive rate,
  added-latency estimate, notes) for the human to fill in.
- After the human reports: record in `PROJECT.md` as verified facts -
  the go/no-go outcome, the chosen candidate approach and its dependency
  cost if go, or the specific failure mode if no-go.

## Acceptance criteria

- [x] Check script and handoff instructions exist and are reproducible
      on the owner's machine.
- [x] The human has run all required room/distance conditions (both BT
      headphones and desktop speakers, close/far x quiet/reverb x
      silent/interrupt) and reported results.
- [x] `PROJECT.md` records the verified facts and an explicit go/no-go
      outcome.
- [x] No changes to `src/jarvis` or `requirements.txt`.

## Closure note (2026-07-26)

No-go for voice barge-in over desktop speakers / arbitrary hardware.
Full verified facts are in `PROJECT.md`'s "Architecture v1.7.0 spike"
section; summary:

- BT headphones (the owner's normal daily setup): near-zero self-hearing
  by measurement, no AEC needed.
- Desktop speakers, on this machine's PC -> HDMI -> TV -> HDMI ARC ->
  soundbar chain: a real 310-335 ms device/chain latency was found and
  fixed in the check script (cross-correlation delay estimation added),
  but even after the fix and a tuning sweep, the pure-numpy NLMS
  candidate left Silero VAD false-positiving on self-heard TTS in every
  one of the four desktop-speaker conditions.

This did not stay a narrow "try a better library" conclusion. Discussing
the result surfaced a wider architectural problem with the story's
original premise: Jarvis ships to arbitrary user hardware with no
per-device calibration lab (unlike commercial smart speakers, whose
detectors are tuned against known fixed hardware), and ambient noise
compounds with imperfect echo cancellation into a harder joint problem
than either alone - it does not reduce to the project's existing
noise-robustness problem even when AEC nominally works. Owner decision
(2026-07-26): voice-triggered interruption is scoped to an opt-in,
default-off, headphones-only experimental feature, justified by the
headphone finding above; a hotkey becomes the primary,
hardware-independent interruption mechanism. See the revised
`tasks/story-v1.7.0-barge-in.md` for the new task sequence.

Not tried: a production-grade AEC library (WebRTC's AEC3, speexdsp) on
the desktop-speaker path. The candidate here was deliberately the
lowest-packaging-risk option first; the architectural decision above
made further AEC investigation unnecessary for this story rather than
proving the ceiling of what any AEC candidate could achieve.
