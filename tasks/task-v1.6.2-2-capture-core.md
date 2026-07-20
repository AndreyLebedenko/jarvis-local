# Task v1.6.2-2: Capture core

**Status:** Planned.
**Story:** `tasks/story-v1.6.2-camera.md`
**Depends on:** task-v1.6.2-1 spike outcome "go".

**Sprint scope update (2026-07-20):** USB only. RTSP configuration, capture,
timeouts, credential handling, and LAN boundary reporting are deferred.

## Summary

The camera capture module: configured USB and RTSP sources, single-frame
grab returning image bytes ready for the verified `images` path, with
the capture backend behind an injectable seam so all logic is testable
without hardware.

## Context you need

- Spike facts in `PROJECT.md`: chosen dependency, observed latency and
  RTSP connect behavior (they size the timeouts), image
  format/conversion needs.
- `src/jarvis/core/config.py`: settings conventions; add a `[camera]`
  section (enabled-at-startup default off, USB device, RTSP URL with
  credentials, per-source presence optional - a config with neither
  source is valid, the module is just sourceless).
- `src/jarvis/audio/input.py` area: how the microphone module handles
  blocking device IO under asyncio (executor use, shutdown ordering) -
  the v1.5.1 shutdown-race lesson applies to any blocking capture call.
- v1.6.0 image attachment normalization
  (`tasks/done/task-v1.6.0-4-image-attachments.md`): reuse the existing
  image normalization toward the `images` field; do not invent a second
  pipeline.
- Roadmap: USB source is `local`, RTSP source is `lan` - the capture
  result must carry its source identity so callers can audit the right
  boundary.

## Boundary

- Capture and config only. No tool exposure (task 3), no health
  chip/cues/toggle UI (task 4). The privacy state itself (a
  camera-enabled flag the tool layer consults) may be introduced here
  as plain state if task ordering needs it, but its UI and events are
  task 4.
- Single frame per call. No retry loops beyond one bounded attempt; a
  slow or dead source fails within a configured timeout with a clear
  error, it does not hang the caller.
- Blocking capture work must not run on the event loop thread.

## Requirements

- A capture function/object per configured source: returns image bytes
  (format matching what the spike verified works well) plus source
  metadata (which source, its data boundary, capture timestamp).
- Timeouts from config with defaults informed by spike measurements;
  RTSP failure modes observed in the spike (unreachable, bad
  credentials) map to distinct, honest error messages - never a silent
  empty result.
- The device/stream backend (OpenCV or whatever the spike chose) sits
  behind an injectable interface; pure tests exercise selection,
  timeout handling, error mapping, and metadata without hardware.
- `requirements.txt` gains the dependency in the same commit that
  introduces it.
- Credentials never appear in logs or error messages - the RTSP URL is
  redacted wherever it is printed.

## Acceptance criteria

- [ ] Tests cover: source selection from config (USB only, RTSP only,
      both, neither), timeout and failure mapping per source, boundary
      metadata correctness, URL redaction in error paths, and that no
      capture is possible through this module when the camera-enabled
      state is off (if introduced here).
- [ ] A minimal hardware check script (or an extension of the spike
      script) exists for the human to confirm the module path grabs
      real frames on both sources.
- [ ] `python -m pytest` and Ruff checks are green.
