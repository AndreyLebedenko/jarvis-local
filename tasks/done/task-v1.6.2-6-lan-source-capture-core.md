# Task v1.6.2-6: Named camera sources and LAN capture core

**Status:** Completed.
**Story:** `tasks/story-v1.6.2-camera.md`
**Depends on:** task 1's RTSP continuation (done, 2026-07-22).
**Verified:** owner-run manual handoff, 2026-07-23.

## Summary

Turn the camera module's single implicit USB source into a registry of
named sources, and add local RTSP as the second kind of source behind the
same seam. Config, capture core, and backend only.

## Context you need

- `PROJECT.md`, the 2026-07-22 LAN camera entries: verified stream URLs and
  latency, the absent HTTP snapshot endpoint, the separate-credential-fields
  decision, and the lens mapping - channel 1 is the motorized upper lens,
  channel 2 the fixed wide lens with an illuminator.
- `src/jarvis/inputs/camera.py`: `CameraBackend` is a Protocol with
  `probe_usb`/`capture_usb`, `CameraFrame` already carries `source` and
  `data_boundary`, and `CameraCapture` owns the privacy check, the timeout,
  and the re-check that the switch did not flip mid-capture.
- `src/jarvis/core/config.py:275`, `CameraSettings`.
- The two-tier locality contract: a LAN camera is an explicit
  per-component capability, off by default, reported honestly on the
  data-source axis. It is not a network dependency of core inference.
- `tasks/backlog/camera-world-changing-controls.md` for what this card
  deliberately does not touch.

## Boundary

- Config, capture core, backend. The tool-facing selector, the media
  contract fix, and UI belong to task 7.
- Reads only. No pan/tilt, no illuminator, no auto-tracking control.
- Single frames. No streaming, reconnection strategy, or session reuse:
  the spike measured a cold open at about 1.87 s, inside the existing
  timeout budget.
- No new runtime dependency; `opencv-python` is already present and its
  FFMPEG backend handles RTSP.

## Requirements

- `CameraSettings` describes a list of named sources rather than one
  implicit USB device. USB becomes an ordinary entry in that list, not a
  special case, because the tool in task 7 selects by name and must not
  care what kind of device is behind it.
- Each LAN entry carries host, port, user, password, and stream path as
  separate values, never one assembled URL. A password containing `#`
  must work with the user typing it literally: the spike lost a debugging
  cycle to `#` opening the URL fragment and truncating the authority into
  `Failed to resolve hostname admin`. Every one of `# / @ : ? &` fails the
  same way, so URL assembly with percent-encoding lives in one testable
  function and the human never encodes anything by hand.
- Names describe the source, not the wiring: `wide` and `detail`, not
  `channel1` and `channel2`. Each entry carries a human-readable
  description that task 7 shows the model. The description for a motorized
  lens states that it shows wherever it was last aimed, so the model does
  not present a non-reproducible view as a predictable one.
- An empty or absent source list is a valid USB-only configuration and
  must not error. Existing USB configs keep working with no edits; if the
  config shape changes incompatibly, the migration is part of this card.
- Every error, log line, and event that mentions a LAN source redacts the
  credentials. No assembled URL with a live password may reach a log, an
  event payload, or an exception message.
- The backend grows LAN probe and capture beside the USB pair. Force RTSP
  over TCP instead of relying on the ffmpeg default, so a failure is fast
  and predictable rather than a stall on blocked UDP.
- A LAN capture returns `CameraFrame` with `source` naming the entry and
  `data_boundary = DataBoundary.LAN`. USB captures stay `LOCAL`.
- The privacy switch governs all sources identically, including the
  mid-capture flip `CameraCapture.capture` already re-checks.
- Automated tests are pure logic against a fake backend: URL assembly with
  each reserved character in the password, credential redaction, boundary
  per source kind, unknown-source handling, disabled-state refusal, the
  timeout path, and a USB-only config still working.
- A manual handoff for the human: capture from `wide` and `detail` through
  the module, plus wrong password and unreachable host with their timings.

## Acceptance criteria

- [x] Both Imou lenses and the C920 capture through the module by name.
- [x] A password containing `#` works with nothing encoded by hand.
- [x] No log, event, or error message exposes a password.
- [x] LAN captures carry `LAN`; USB captures carry `LOCAL`; a USB-only
      config is unaffected.
- [x] `python -m pytest` and Ruff are green.

## Outcome

Verified by the owner on 2026-07-23 with
`python -m manual.manual_check_camera_sources`: the C920 captured in
3.518 s as `local`, the wide lens in 1.914 s and the motorized one in
2.206 s as `lan`. A wrong password failed in 0.123 s and an unreachable
host in 5.006 s, both naming the source and neither exposing the password;
OpenCV's own stderr line reported `401 Unauthorized` without the URL.

Three defects surfaced only on hardware and were fixed before closing:

- Source names matched case-sensitively, so `wide` missed a source
  configured as `Wide`. Names are human labels a person types and a model
  repeats back from a description, not code identifiers; they now match
  case- and whitespace-insensitively, and config rejects two names
  differing only that way.
- The manual script counted a misspelled source name as an expected
  failure, so the wrong-password and bad-host checks could pass without
  contacting a camera. An unknown name is now a distinct
  `UnknownCameraSourceError` and a usage error the `--expect-failure`
  flag never absorbs.
- Forcing the capture budget through ffmpeg's `timeout` capture option did
  not work: OpenCV's own 30 s `CAP_PROP_OPEN_TIMEOUT_MSEC` default kept the
  capture thread alive about 25 s after the asyncio timeout had already
  answered the caller. The budget is now applied through OpenCV's
  open/read timeout properties, verified at 5.022 s against an unreachable
  host.

Note for task 8: "the capture thread ended on time" is a manual-check
claim, not an automated one. The suite exercises `asyncio.wait_for` against
a fake backend and cannot observe a thread that outlives it.

Raised and deferred, not part of this card: LAN credentials sit in
`config.toml` in plain text. The owner reopened this as a project-wide
question on 2026-07-23; see `tasks/backlog/secret-storage.md`.
