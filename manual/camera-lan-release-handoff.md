# LAN camera release handoff

Hardware-dependent, so the owner runs this, not the agent. It extends
`camera-usb-release-handoff.md` rather than replacing it: run that one
first if the USB path has not been checked since the source registry
landed.

Prerequisites: at least one `kind = "lan"` entry under
`[[camera.sources]]` in `config.toml`, its RTSP account created in the
camera's own app with media-stream encryption off, and one USB source so
the mixed-boundary steps have something local to capture.

Report the output of each step, not a verdict. Steps 4 and 5 are the ones
that cannot be replaced by an automated test.

1. **Both lenses answer, by name.** Run
   `python -m manual.manual_check_camera_sources`. Every configured source
   should return a frame; LAN frames report `boundary lan` and USB frames
   `boundary local`. Open the saved files and confirm each shows what its
   description claims.

2. **The privacy switch still governs everything.** With
   `[camera].enabled = false`, start Jarvis and ask it to look at the LAN
   camera. Confirm no capture cue, no frame, and a refusal - the switch
   answers "may Jarvis look at all", so a LAN source must be no more
   reachable than a USB one while it is off.

3. **The tool switch is separately non-delegable.** Enable the camera but
   leave `capture_camera_image` disabled in the Status Console. Ask again
   and confirm the model cannot capture, and does not claim to have.

4. **Attribution across two cameras in one turn.** Aim the motorized lens
   at something the fixed lens cannot see. Enable both switches and run
   `python -m manual.manual_check_camera_attribution`. The answer passes
   only if each camera is described with what that camera actually shows -
   an answer that swaps them, or describes one view twice, is a failure
   even if both descriptions are individually accurate.

5. **Addressed capture.** Ask for one named camera, for example
   `python -m manual.manual_check_camera_attribution --expect-captures 1
   --ask "What does the detail lens see?"`. Confirm exactly one capture,
   from the named source.

6. **The audit panel tells the truth.** In the live Status Console, run a
   turn that captures from the LAN camera and confirm the events panel
   reports the call with a `lan` boundary, and that the header's data-source
   indicator widens from local to LAN for that turn. Then run a turn
   capturing both a USB and a LAN source and confirm the turn reports LAN,
   not whichever call happened first.

7. **Wrong password.** Run
   `python -m manual.manual_check_camera_sources --source <lan-source>
   --password WRONG --expect-failure`. Confirm it fails quickly, the message
   names the source, and no password text appears anywhere in the output -
   including OpenCV's own stderr lines.

8. **Unreachable camera.** Run the same command with `--host` pointing at an
   address nothing answers on. Confirm the failure arrives at roughly
   `[camera].capture_timeout_seconds`, and that any OpenCV stream-timeout
   line reports about the same figure rather than its own 30 s default -
   a much larger number means the capture thread outlived the caller's wait.

9. **Degraded is not silently cleared.** With a LAN source configured but
   powered off or unplugged, enable the camera. The camera chip should show
   degraded rather than ready. Then capture successfully from the USB
   source and confirm the chip stays degraded: one working camera must not
   report the whole module ready. Restore the LAN camera, capture from it,
   and confirm the chip returns to ready.

10. **Vision honesty holds.** Ask the model to read something written on a
    small label through the LAN camera. A wrong confident answer here is the
    expected documented behavior, not a regression - confirm the README's
    claim matches what you see, and report it if scene description itself is
    unreliable.
