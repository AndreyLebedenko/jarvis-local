# Task v1.6.2-8: LAN camera docs and release verification

**Status:** Completed.
**Story:** `tasks/story-v1.6.2-camera.md`
**Depends on:** tasks 6 and 7.
**Verified:** owner-run checklist, 2026-07-24.

## Summary

Close the LAN half of v1.6.2: document how to configure a LAN camera
honestly, including what the stored credentials mean, and run the human
verification checklist on real hardware.

## Context you need

- Task 5 already produced the USB documentation and checklist. This card
  extends them rather than starting a parallel set.
- `PROJECT.md`'s 2026-07-22 LAN spike entries, especially the two facts a
  user will otherwise rediscover painfully: the camera needs its RTSP
  account created in the vendor app with media-stream encryption off, and
  a wrong stream path is indistinguishable from wrong credentials because
  the camera answers `401` before it looks at the path.

## Boundary

- Documentation and human verification. No behavior changes; a defect
  found here becomes its own fix, and a defect that should not be fixed
  now becomes a report under `tasks/bug_reports/`.

## Requirements

- Config documentation states plainly that the LAN camera password is
  stored in the local config file in clear text, what an attacker with
  that file can reach, and that the password is written literally because
  the code encodes it - the user never percent-encodes anything by hand.
- Setup guidance covers the vendor-app prerequisites and the fact that
  finding the right stream path is trial and error against a camera that
  returns `401` for everything until credentials are correct.
  `manual/manual_check_rtsp_discovery.py` is the documented way to do that
  quickly instead of waiting out OpenCV's 30-second open timeout.
- Vision honesty carries into user-facing docs: scene description is the
  supported answer. Reading text and counting objects are not guaranteed,
  and the observed failure mode is a confident wrong answer rather than an
  admission of doubt. A user who reads only the README should not expect
  the camera to reliably read labels.
- Source naming is documented for what the hardware is: channel 1 is the
  motorized upper lens, channel 2 the fixed wide lens with an illuminator.
  Documentation states that a capture from the motorized lens is not
  reproducible, since it shows wherever it was last aimed, including by
  the camera's own auto-tracking.
- Documentation states that Jarvis reads frames only and does not aim the
  lens or switch the light, pointing at
  `tasks/backlog/camera-world-changing-controls.md` for why that is a
  separate decision rather than a missing feature.
- A human checklist covering both lenses, a turn capturing two sources and
  attributing them correctly, capture while the toggle is off, a wrong
  password, an unreachable camera, and the audit panel showing `lan`.

## Acceptance criteria

- [x] Config and README documentation cover the LAN source, its clear-text
      credentials, and the vision limitations without overclaiming.
- [x] The human has run the checklist on the Imou camera and reported the
      result.
- [x] `PROJECT.md` records the LAN release verification outcome.
- [x] `python -m pytest` and Ruff are green.

## Outcome

Documentation landed in both READMEs and `config.example.toml`, and the
checklist is `manual/camera-lan-release-handoff.md`. The owner ran it on
2026-07-24 and everything claimed works: the privacy switch blocks every
source, attribution picks the right camera, the audit panel reports the
call with its source and boundary, and one working camera out of three
keeps the chip DEGRADED rather than clearing it. The full result is
recorded in `PROJECT.md`.

Two observations from the run, neither a blocker:

- Camera OCR is poor even on relatively large text. This is the
  vision-model limitation the spike already recorded, now confirmed at
  product level, and it is exactly what this card's documentation claims -
  so the check validated the wording rather than contradicting it.
- Jarvis does not reach for the camera unprompted. Not an acceptance
  criterion, but worth recording: it is the behavior the privacy model
  assumes.

Out-of-scope defect found while setting up the live checks: an explicitly
selected microphone device never opens, because Windows exposes one
physical microphone once per host API and the config stores only its name.
Jarvis runs deaf with a healthy-looking console. Reported in
`tasks/bug_reports/2026-07-24-microphone-device-name-ambiguous-across-host-apis.md`
rather than fixed here - it needs a device-identity decision and its own
hardware verification. The checklist itself was unblocked by typing in the
Journal tab instead of speaking.

Also fixed here, since this card rewrote the text anyway: the USB camera
section had been sitting between the README title and the project's own
introduction since `0ff5079`. It is now one "Camera" section covering both
kinds, in document order.
