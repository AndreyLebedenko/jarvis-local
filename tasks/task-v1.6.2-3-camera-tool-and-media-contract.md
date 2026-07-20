# Task v1.6.2-3: Camera tool and media-from-tool-result contract

**Status:** Planned.
**Story:** `tasks/story-v1.6.2-camera.md`
**Depends on:** task-v1.6.2-2 (capture core); v1.6.1 builtin provider.

**Sprint scope update (2026-07-20):** the first tool has no source selector
and captures only local USB. The generic tool-result-image contract remains
the task's scope; LAN boundary behavior is deferred with RTSP.

## Summary

Expose capture as a builtin tool and define the story's main
architectural output: a tool result whose image media enters the
current turn's media through `ToolAwareDialog`, under the same
current-turn-only rule as every other media source.

## Context you need

- `src/jarvis/dialog/tool_presentation.py` (`ToolAwareDialog`): how
  tool results are fed back to the model today (text), and where the
  turn's media is assembled - the seam this card opens for image
  content from a tool result.
- `src/jarvis/tools/interception.py`: `ToolDispatchResult.content` /
  `structured_content` - decide how image bytes travel from the builtin
  tool to the dialog layer without stuffing base64 into audit event
  summaries.
- v1.6.1 builtin provider (task-v1.6.1-1): registration, audit events,
  per-tool toggle. Per-source data boundary: the camera tool's audited
  boundary must reflect the actual source used on each call (`local`
  for USB, `lan` for RTSP), not a single static declaration - if the
  registry's static `data_boundary` cannot express that, surface it,
  don't fudge it.
- Story design decisions: one tool with a source selector; while the
  camera toggle is off, either the tool is absent from the model-facing
  list or it fails with a clear "camera is off" error - this card
  decides which and records why.
- Verified media rules: images go through the `/api/chat` `images`
  field, current-turn only, history stays text-only.

## Boundary

- The media contract is defined generically (a tool result can carry
  current-turn image media), the camera is its first user - but no
  speculative features beyond what the camera needs (no multi-image
  results, no non-image media).
- No UI work (task 4). No journal schema changes beyond what recording
  the tool turn already does; if journaling the captured frame as
  turn media needs anything new, coordinate with the existing
  journal media transport rather than inventing storage.
- History remains text-only: the frame must not leak into
  `ConversationHistory` or fork seeds.

## Requirements

- Builtin tool (working name `capture_camera_image`): optional source
  argument (`usb`/`lan`) with the story's default rule; returns a
  short text part (for the model's narration and the audit trail) plus
  the image for the current turn's media.
- `ToolAwareDialog` places the returned image into the current turn's
  outbound media exactly like a hotkey screenshot would be placed:
  same normalization, same `images` field, gone after the turn.
- Audit events: outbound summary names the tool and source, never
  embeds image data; the per-call data boundary matches the source
  used.
- Toggle-off behavior per the decision above; either way no frame is
  captured while off, verified by test at this layer too
  (defense-in-depth with task 2's check).
- Capture failure (timeout, unreachable camera) surfaces to the model
  as a normal tool error it can relay conversationally.

## Acceptance criteria

- [ ] Tests cover: a successful tool call producing both the text part
      and current-turn media entering payload construction; media
      absent from history and from the next turn; per-source boundary
      on audit events; toggle-off behavior; failure mapping to a tool
      error; no image bytes in any event summary.
- [ ] A human-run handoff scenario exists: "посмотри в камеру, что ты
      видишь?" by voice for both sources, checking answer content,
      latency feel, and the events panel's boundary reporting.
- [ ] `python -m pytest` and Ruff checks are green.
