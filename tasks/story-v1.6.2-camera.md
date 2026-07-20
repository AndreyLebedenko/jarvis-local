# Story v1.6.2: Camera

**Status:** Planned. Gated on the task-1 spike: if frame quality is
insufficient for useful answers, stop and re-plan before building the
module (roadmap boundary).
**Roadmap:** `tasks/roadmap-v1.5.1-v1.7.md` (v1.6.2 section; native
sensor module decision 2026-07-18).
**Created:** 2026-07-20.

## User-facing goal

Jarvis's first on-command sense: "look at the camera" makes Jarvis
capture a static image from a local USB camera or the LAN camera
(TP-Link Tapo C230 via RTSP) through its own tool call and answer
questions about what it sees.

## Boundaries

- Static frames only; no video streams, motion detection, or recording.
- No cloud APIs of any kind; the Tapo cloud is never contacted. RTSP
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
  human-run check script grabs a frame from the USB camera and from the
  Tapo C230, sends each through the verified `images` path, and
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

## Scope (ordered task cards)

- `tasks/task-v1.6.2-1-camera-spike.md` - human-run spike, hard gate;
  verified facts into `PROJECT.md`.
- `tasks/task-v1.6.2-2-capture-core.md` - capture module (USB + RTSP
  frame grab), config, pure logic tests.
- `tasks/task-v1.6.2-3-camera-tool-and-media-contract.md` - the builtin
  capture tool and the media-from-tool-result contract through
  `ToolAwareDialog`.
- `tasks/task-v1.6.2-4-module-integration-and-ui.md` - health chip,
  sound cues, privacy toggle with mic-sleep parity.
- `tasks/task-v1.6.2-5-docs-and-release-verification.md` - PROJECT.md,
  config docs (credentials honesty), human-run checklist.

## Acceptance criteria

- [ ] Spike facts (answer quality, capture latency, RTSP connect
      behavior, dependency decision) are recorded in `PROJECT.md`
      before module implementation starts.
- [ ] "Look at the camera" as a voice request produces a model-initiated
      tool call that captures a frame and answers about its content,
      with the image entering only the current turn's media.
- [ ] USB captures are audited `local`; LAN captures are audited `lan`
      and reported on the data-source axis like LAN MCP tools.
- [ ] The camera is off by default; while off, no code path can capture
      a frame; enabling is an explicit user action; every capture plays
      a cue; the health chip reflects module state.
- [ ] The camera toggle is not delegable through any tool.
- [ ] Config documentation states plainly that RTSP credentials are
      stored in plain text in the local config file.
- [ ] `python -m pytest` and Ruff checks are green; camera hardware
      verification is a prepared human-run handoff.

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
