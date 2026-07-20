# USB camera release handoff

This is hardware-dependent and must be run by the owner.

1. Copy `config.example.toml` to `config.toml` if needed and keep
   `[camera].enabled = false`.
2. Start Jarvis with `python -m jarvis`. In the Status Console, confirm that
   `capture_camera_image` is disabled in the builtin-tool list.
3. Ask in Russian: `посмотри в камеру, что ты видишь?` Confirm that no camera
   light or capture cue occurs while the tool is disabled.
4. Enable `capture_camera_image` in the same Control Center list. Repeat the
   request with a visible scene and readable text. Confirm one distinct cue,
   a useful answer, and a `local` tool boundary in the events panel.
5. Disable the tool again, repeat the request, and confirm no frame is
   captured. Do not test RTSP in this handoff; it is deferred pending Imou.
