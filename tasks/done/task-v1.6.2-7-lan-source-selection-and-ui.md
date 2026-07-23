# Task v1.6.2-7: Source selection, frame provenance, and UI

**Status:** Completed.
**Story:** `tasks/story-v1.6.2-camera.md`
**Depends on:** task 6.
**Verified:** owner-run manual handoff, 2026-07-24.

## Summary

Let the model address a named camera, and fix the media contract so that a
frame stays attached to the tool result that produced it. Without the
second part, multiple sources in one turn arrive as an unlabeled pile of
images and the model has to guess which camera is which.

## Context you need

- `src/jarvis/tools/builtin.py:57`, `_capture_camera_image`: today it takes
  no arguments, always captures USB, and hardcodes the result text
  "Captured one USB camera image for this turn." All three change here.
- `src/jarvis/dialog/tool_presentation.py:309-321` - the defect this card
  fixes. After each tool result, frames are appended to the last message
  with role `user`, found by searching backwards. Under the default
  `native` strategy (`config.example.toml:211`) tool results have role
  `tool`, so the search skips them and lands on the original user message:
  after two camera calls the model receives one user message carrying two
  images in sequence, with nothing binding either image to the tool result
  that names its source. The binding is positional and unstated. Under the
  `prompt` strategy the same code accidentally does the right thing,
  because there tool results have role `user` and each frame lands beside
  the text naming its source.
- The story's stated main architectural output is the
  media-from-tool-result contract. It was written for one source and does
  not survive several.
- Task 4's health chip, sound cue, and non-delegable privacy toggle: the
  LAN sources reuse them rather than growing a parallel set.

## Boundary

- Tool surface, media contract, audit, UI. No config, capture, or backend
  changes - those are task 6.
- The privacy toggle stays one switch for the whole camera module. Per
  source toggles are not in this story: the switch answers "may Jarvis look
  at all", which is what a person actually reasons about.
- Reads only, per `tasks/backlog/camera-world-changing-controls.md`.

## Requirements

- A frame is attached to its own tool-result message rather than
  accumulated onto the original user message, so provenance is structural
  instead of positional and `native` behaves like `prompt`. Whatever the
  mechanism, the model must be able to tell which image came from which
  source without relying on ordering.
- The tool takes an optional source name. With no argument it uses a
  configured default; with a name it uses that source; with an unknown name
  it fails with a message listing the configured names and descriptions, so
  a model that guesses gets a correctable error instead of a silent wrong
  camera.
- Addressing several cameras happens through several tool calls, not a list
  argument. The tool loop already dispatches multiple calls from one model
  response, and a per-call result keeps a single camera's failure from
  invalidating the frames that did arrive.
- Note for whoever implements: `mcp.max_tool_calls_per_turn` defaults to 3
  (`src/jarvis/core/config.py:360`), so three cameras consume the whole
  per-turn budget and leave nothing for other tools. Decide and record
  whether the budget rises or captures are counted differently; do not
  silently bump the constant.
- The result text and structured content name the source actually used.
  The current hardcoded "USB" string is a bug the moment a second source
  exists.
- A LAN capture is audited `lan` and a USB capture `local`. A turn mixing
  both reports both on the data-source axis, not whichever came first.
- The health chip reflects LAN reachability honestly. A camera on Wi-Fi is
  a different failure class from an unplugged USB device: it can be
  configured, enabled, and simply not answering. The chip must not claim
  ready for an unreachable LAN camera, and recovery follows the existing
  camera-chip reset path.
- The capture cue plays for every capture regardless of source.
- Automated tests: default selection, explicit selection, unknown-source
  error text, provenance surviving two captures in one turn, mixed
  boundaries in one turn, result text naming the used source, and refusal
  while the privacy toggle is off.
- Manual attribution check on hardware, which the lens layout makes
  unambiguous: aim the motorized `detail` lens at something the fixed
  `wide` lens cannot see, capture both in one turn, and ask the model which
  image shows what. This is the check that proves the provenance fix; it
  replaces the broader "can the model handle several images" question,
  which belongs to user-supplied media and is out of scope.

## Acceptance criteria

- [x] "Look at the camera" still works with no argument; asking for a named
      source captures from that source.
- [x] With two sources captured in one turn, the model attributes each
      image to the right source on real hardware.
- [x] The audit panel shows `lan` for LAN, `local` for USB, and both for a
      mixed turn.
- [x] No result text claims USB for a LAN frame.
- [x] An unreachable LAN camera does not show a ready chip.
- [x] The privacy toggle remains non-delegable and still blocks every
      source.
- [x] `python -m pytest` and Ruff are green.

## Outcome

Verified by the owner on 2026-07-24 with
`python -m manual.manual_check_camera_attribution` against
`gemma4:12b-it-qat` under the `native` strategy. One turn produced three
captures - `local`, `lan`, `lan` - and three distinct, camera-specific
descriptions, which is exactly what the old contract could not deliver:
the frames used to arrive as an unlabeled pile on the turn's user message.
An addressed question ("Что видно на камере Rotating?") produced a single
LAN capture from the named source.

The three-camera run also exercised the budget decision on real hardware:
all three calls were spent, the loop hit the limit, and the turn still
produced a final answer instead of dropping a frame.

Decisions recorded in `PROJECT.md`: media travels in its own message bound
to its result; a call's data boundary may be widened by its arguments and
is recorded from the finished call too; an unreachable source degrades the
module rather than disabling it; the tool-call budget stays at 3.

Review finding fixed before closing: a successful capture cleared the
DEGRADED chip unconditionally, so a USB frame hid a still-unreachable LAN
camera. The failure path had the same hole in mirror image. Both capture
events now carry their source name and `ModuleHealthTracker` keeps the
unreachable set, so a frame clears only its own source - which also makes
recovery self-healing: a frame from the camera that was unreachable is
what returns the chip to ready.

Known limit, deliberate: `ToolCallStarted` for a camera call still reports
the tool's registered `local` boundary, because which source will run is
unknown until the call finishes. During a capture of about two seconds the
axis reads local and only then widens to lan. Honest within the turn, but
it is a compromise rather than an oversight.
