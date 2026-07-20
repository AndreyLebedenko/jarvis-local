# Task v1.6.2-1: Camera spike (hard gate)

**Status:** Planned.
**Story:** `tasks/story-v1.6.2-camera.md`
**Depends on:** nothing in this story; must complete before tasks 2-5
begin.

## Summary

Human-run spike proving the whole camera idea end to end before any
module code exists: grab a frame from a local USB camera and from the
Tapo C230 via RTSP, send each through the existing `images` path to
local Ollama, and record verified facts in `PROJECT.md`.

## Context you need

- Roadmap v1.6.2 scope: RTSP URL form
  `rtsp://user:pass@<ip>:554/stream1`, camera account required on the
  Tapo side (the human sets that up on the device).
- `PROJECT.md`: the verified Ollama media rule (images via the
  `/api/chat` `images` field) and how earlier spikes recorded facts
  (v1.3.1/v1.4.0 precedent).
- Testing protocol: this is hardware-dependent - the agent writes the
  check script and hands over exact commands; the human runs it and
  reports output.

## Boundary

- A standalone check script (existing check-script conventions), not
  module code. Nothing lands in `src/jarvis` from this card.
- Static single frames only. No stream handling beyond what one frame
  grab requires.
- Dependency for the spike may be installed ad hoc (e.g. OpenCV);
  whether it becomes a runtime dependency is part of the recorded
  decision, and `requirements.txt` is only touched when task 2 makes
  it real.

## Requirements

- The script, for each source (USB index/device, RTSP URL from a local
  config or CLI argument - credentials never hardcoded in the repo):
  - captures one frame, saves it to a local file for eyeballing;
  - measures and prints capture latency (open-to-frame), and for RTSP
    also connect time and failure mode when the camera is unreachable
    (wrong IP, wrong credentials);
  - sends the frame through the `images` field to the configured local
    Ollama model with a fixed set of probe questions (scene
    description, reading visible text, counting objects) and prints
    the answers.
- A short handoff document/section with exact commands, what to vary
  (lighting, distance), and a result table for the human to fill in.
- After the human reports: record in `PROJECT.md` as verified facts -
  answer quality per source, capture latency, RTSP connect behavior,
  and the dependency decision with its cost. If quality is
  insufficient, the story stops here and goes back to planning
  (roadmap hard gate).

## Acceptance criteria

- [ ] Check script and handoff instructions exist and are reproducible
      on the owner's machine.
- [ ] The human has run both sources and reported results.
- [ ] `PROJECT.md` records the verified facts and the go/no-go
      outcome; tasks 2-5 remain blocked until the outcome is "go".
- [ ] No changes to `src/jarvis` or `requirements.txt`.
