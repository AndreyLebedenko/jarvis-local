# Task v1.6.2-5: Docs and release verification

**Status:** Planned.
**Story:** `tasks/story-v1.6.2-camera.md`
**Depends on:** tasks v1.6.2-1..4.

## Summary

Record the camera module and media-from-tool-result contracts in
`PROJECT.md`, document configuration honestly (RTSP credentials in
plain text), and prepare the human-run release verification checklist
for v1.6.2.

## Context you need

- Story acceptance criteria and the roadmap's v1.6.2 section (data
  boundaries, off-by-default, no-cloud rule).
- `PROJECT.md`: two-tier runtime locality contract wording (the LAN
  camera is a per-component external capability like LAN MCP tools),
  spike facts recorded by task 1, and the media rules section.
- Release verification precedent:
  `tasks/done/task-v1.6.0-10-release-verification.md`.

## Boundary

- Documentation and checklist only; verification-revealed fixes larger
  than trivial become bug reports per the project protocol.

## Requirements

- `PROJECT.md` records as settled contracts:
  - the media-from-tool-result rule (tool-result images enter the
    current turn's media through `ToolAwareDialog`, current-turn only,
    history text-only);
  - the camera module: native sensor (not MCP), off by default,
    toggle never delegable, per-source data boundaries (`local` USB,
    `lan` RTSP), no Tapo cloud contact ever;
  - the dependency decision and any latency facts refined since the
    spike.
- Config documentation covers the `[camera]` section and states
  plainly that RTSP credentials are stored in plain text in the local
  config file, with the resulting handling advice (file permissions,
  no config sharing).
- README/user docs mention the new capability and its privacy model at
  the established level of detail.
- Human-run checklist covering: both sources end to end by voice,
  off-by-default on fresh config, toggle guarantees (no capture while
  off), cue and chip behavior, events panel boundary reporting for
  `lan` captures, credential redaction in logs/events, and behavior
  with the LAN camera unplugged/unreachable.

## Acceptance criteria

- [ ] `PROJECT.md`, config docs, and user docs updated in the same
      release as the feature.
- [ ] The human-run checklist is prepared and handed off; verified
      outcomes are recorded before the story closes.
- [ ] `python -m pytest` and Ruff checks are green.
