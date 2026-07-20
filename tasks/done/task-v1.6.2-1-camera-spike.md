# Task v1.6.2-1: Camera spike (hard gate)

**Status:** Completed.
**Story:** `tasks/story-v1.6.2-camera.md`
**Depends on:** nothing in this story; must complete before tasks 2-5
begin.

## Summary

Human-run spike proving the whole camera idea end to end before any
module code exists: grab a frame from the Logitech C920 USB camera and,
when available, from the Imou Dual Lens via local RTSP, send each
through the existing `images` path to local Ollama, and record verified
facts in `PROJECT.md`.

## Context you need

- Roadmap v1.6.2 scope: one immediate USB source and one later local
  RTSP source. Current candidate hardware is Logitech C920 for USB and
  Imou Dual Lens (ASIN B0FBG3RPZ8) for LAN.
- Owner-supplied Imou research suggests Dahua-style RTSP URLs such as
  `rtsp://admin:SAFETY_CODE@<ip>:554/cam/realmonitor?channel=1&subtype=0`
  and `channel=2` for the second lens, with media-stream encryption
  disabled in the vendor app if required. Treat this as setup guidance,
  not a verified project fact until the manual run confirms it.
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

- The script, for each available source (USB index/device now, RTSP URL
  from a local config or CLI argument when the Imou camera is available -
  credentials never hardcoded in the repo):
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
  answer quality per available source, capture latency, RTSP connect
  behavior when available, and the dependency decision with its cost.
  If quality is insufficient, the story stops here and goes back to
  planning (roadmap hard gate).

## Acceptance criteria

- [x] Check script and handoff instructions exist and are reproducible
      on the owner's machine.
- [x] The human has run the immediate USB source and reported results;
      Imou RTSP remains pending until that hardware is available.
- [x] `PROJECT.md` records the verified USB facts and the USB go
      outcome; RTSP facts remain pending.
- [x] No changes to `src/jarvis` or `requirements.txt`.

## Closure note

Closed after the USB-only hardware run. The C920 path is a go for task 2
with DirectShow + MJPG + requested 1920x1080. Imou Dual Lens RTSP is not
verified yet and remains a later hardware continuation, not a blocker for
the USB capture core.
