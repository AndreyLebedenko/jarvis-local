# Story v1.6.2: Camera

**Status:** Completed for the USB scope. Gated on the task-1 spike: if frame quality is
insufficient for useful answers, stop and re-plan before building the
module (roadmap boundary).
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.6.2 section; native
sensor module decision 2026-07-18).
**Created:** 2026-07-20.

**Sprint scope update (2026-07-20):** this implementation sprint delivers
USB capture only. Imou/RTSP is deferred until the camera is available and its
hardware spike is complete. All references below to LAN capture describe that
future continuation, not an acceptance criterion for this sprint.

## User-facing goal

Jarvis's first on-command sense: "look at the camera" makes Jarvis
capture a static image from a local USB camera or the later LAN camera
through its own tool call and answer questions about what it sees.

## Boundaries

- Static frames only; no video streams, motion detection, or recording.
- No cloud APIs of any kind; the camera cloud is never contacted. RTSP
  goes directly to the camera on the LAN.
- Native sensor module, not an MCP server (owner decision, 2026-07-18):
  the camera is privacy-sensitive like the microphone and gets a module
  health chip, sound cues, and a user-facing privacy toggle with parity
  to mic sleep.
- Capture is a builtin tool on v1.6.1's provider; this story depends on
  v1.6.1 having landed.
- Data boundaries: local USB capture is `data_boundary = local`; LAN
  RTSP capture is `data_boundary = lan`, reported on the data-source
  axis exactly like LAN MCP tools. Off by default, enabled explicitly,
  per the two-tier locality contract.
- RTSP credentials live in the local config file in plain text; the
  config documentation says so honestly.
- Media stays current-turn only, like every other media source.

## Design decisions (proposed here, confirmed by card approval)

- **Spike is a hard gate** (precedent: v1.3.1/v1.4.0 spikes): a
  human-run check script grabs a frame from the Logitech C920 USB camera
  and, when available, the Imou Dual Lens over local RTSP, sends each
  through the verified `images` path, and
  `PROJECT.md` records answer quality, capture latency, and RTSP
  connect behavior before any module code is written. The spike also
  settles the capture dependency (OpenCV is the expected candidate for
  both USB and RTSP; a large dependency is acceptable only if the spike
  proves it earns its place - record the decision and its size cost).
- **Media-from-tool-result contract is the story's main architectural
  output:** a tool result can carry image media that enters the current
  turn's media through `ToolAwareDialog`, following the same
  current-turn-only rule as every other media source (hotkey
  screenshot, journal attachments). v1.6.0 deliberately kept this seam
  open; this story defines it once, for any future media-producing
  tool, not as a camera special case. History remains text-only.
- **Privacy model mirrors the microphone:** a camera-disabled state is
  the default; enabling is an explicit user action (Control Center
  toggle, config for startup state). While disabled, the capture tool
  is either absent from the model-facing tool list or fails
  immediately with a clear "camera is off" error - decided in task 3;
  the guarantee either way is that no frame is ever captured while the
  toggle is off. Every capture plays an audible cue, parity with
  existing sound-cue behavior. The toggle itself is never delegable
  (cross-cutting rule 9).
- **Two configured sources, one tool:** config defines the USB device
  and the RTSP URL (with credentials); the capture tool takes a source
  selector defaulting sensibly (proposed: USB if configured, else
  LAN). Each source carries its own data boundary; a capture from the
  LAN source is audited as `lan`.

## Candidate hardware for the spike

- Immediate USB source: Logitech C920.
- Later LAN source: Imou Dual Lens, ASIN B0FBG3RPZ8, 5 GHz Wi-Fi.
  The owner-supplied initial research says the camera is expected to
  expose Dahua-style local RTSP streams on port 554, with one channel
  per lens, and ONVIF discovery/control. This is not yet a verified
  project fact; task 1 must treat the RTSP URL as a human-supplied
  local argument and record real behavior only after the hardware run.

## Scope (ordered task cards)

- `tasks/done/task-v1.6.2-1-camera-spike.md` - human-run spike, hard gate;
  verified facts into `PROJECT.md`.
- `tasks/done/task-v1.6.2-2-capture-core.md` - capture module (USB + RTSP
  frame grab), config, pure logic tests.
- `tasks/done/task-v1.6.2-3-camera-tool-and-media-contract.md` - the builtin
  capture tool and the media-from-tool-result contract through
  `ToolAwareDialog`.
- `tasks/done/task-v1.6.2-4-module-integration-and-ui.md` - health chip,
  sound cues, privacy toggle with mic-sleep parity.
- `tasks/done/task-v1.6.2-5-docs-and-release-verification.md` - PROJECT.md,
  config docs (credentials honesty), human-run checklist.

## Acceptance criteria

- [x] USB spike facts (answer quality, capture latency, dependency decision)
      are recorded in `PROJECT.md` before module implementation starts.
      RTSP connect behavior is deferred until Imou is available.
- [x] "Look at the camera" as a voice request produces a model-initiated
      tool call that captures a frame and answers about its content,
      with the image entering only the current turn's media.
- [x] USB captures are audited `local`. LAN `lan` auditing is deferred with
      RTSP.
- [x] The camera is off by default; while off, no code path can capture
      a frame; enabling is an explicit user action; every capture plays
      a cue; the health chip reflects module state.
- [x] The camera toggle is not delegable through any tool.
- [ ] RTSP credential documentation is deferred with the RTSP source; no
      RTSP credentials exist in the USB-only configuration.
- [x] `python -m pytest` and Ruff checks are green; the USB hardware handoff
      is completed and recorded in `PROJECT.md`.

## Stop conditions

- Stop (and re-plan the release) if the spike shows frame quality
  insufficient for useful answers - the roadmap's hard gate.
- Stop if the media-from-tool-result contract cannot reuse the existing
  current-turn media path and would require restructuring
  `ToolAwareDialog` or history semantics.
- Stop if RTSP connect behavior is so slow or flaky that a synchronous
  in-turn capture is a bad experience - buffering/prefetch designs are
  a separate decision, not an improvisation.
- Stop if the capture dependency drags in licensing or packaging
  problems for the Windows setup.
