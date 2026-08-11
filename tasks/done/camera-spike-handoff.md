# Camera spike handoff

Task: `tasks/task-v1.6.2-1-camera-spike.md`.

This is hardware-dependent. The human runs these commands and reports the
filled result table. The script writes captured JPG frames under
`manual_check_camera_spike_out/`; inspect each frame visually before
trusting model answers.

## One-time setup

```powershell
python -m pip install --force-reinstall "numpy==1.26.4" "opencv-python==4.11.0.86"
```

This is an ad hoc spike dependency only. Do not add it to
`requirements.txt` until task 2 decides the runtime dependency.

Do not install unpinned `opencv-python`: on 2026-07-20 it resolved to
`opencv-python 5.0.0.93` and `numpy 2.4.6`, which conflicts with the
owner's installed `scipy 1.12.0` (`numpy <1.29` required). If that already
happened, the command above is also the rollback command.

## USB Logitech C920

Start with the default Windows camera index:

```powershell
python -m manual.manual_check_camera_spike --usb-index 0 --label c920-1080p --opencv-backend dshow --frame-width 1920 --frame-height 1080 --fourcc MJPG
```

If the wrong device opens, retry with `--usb-index 1`, then `--usb-index 2`.
If DirectShow fails, retry once with `--opencv-backend msmf`; record both
latencies.
If the actual printed resolution is not `1920x1080`, keep the output and
rerun once at `--frame-width 1280 --frame-height 720 --fourcc MJPG`.

Run at least three passes:

- normal desk lighting, camera at normal position;
- dimmer lighting;
- visible text placed at expected working distance.

## Imou Dual Lens RTSP

Run this later, after the camera is on the LAN and local RTSP is enabled.
Use the real IP address and safety code from the camera; do not paste the
credentials into committed files.

Fixed lens candidate:

```powershell
python -m manual.manual_check_camera_spike --rtsp-url "rtsp://admin:SAFETY_CODE@IP_ADDRESS:554/cam/realmonitor?channel=1&subtype=0" --label imou-fixed
```

Second lens candidate:

```powershell
python -m manual.manual_check_camera_spike --rtsp-url "rtsp://admin:SAFETY_CODE@IP_ADDRESS:554/cam/realmonitor?channel=2&subtype=0" --label imou-ptz
```

If OpenCV auto backend is slow or fails for RTSP, retry with
`--opencv-backend ffmpeg`.

If RTSP authorization fails, check whether media-stream encryption is
enabled in the vendor app and disable it for local RTSP testing.

Failure-mode checks:

```powershell
python -m manual.manual_check_camera_spike --rtsp-url "rtsp://admin:WRONG_CODE@IP_ADDRESS:554/cam/realmonitor?channel=1&subtype=0" --label imou-wrong-credentials --expect-capture-failure
python -m manual.manual_check_camera_spike --rtsp-url "rtsp://admin:SAFETY_CODE@192.0.2.123:554/cam/realmonitor?channel=1&subtype=0" --label imou-wrong-ip --expect-capture-failure
```

## Result table

| Source | Lighting/distance | Frame path | Capture open seconds | Open-to-frame seconds | Resolution | Probe answers useful? | Notes |
| --- | --- | --- | ---: | ---: | --- | --- | --- |
| C920 | normal |  |  |  |  |  |  |
| C920 | dim |  |  |  |  |  |  |
| C920 | visible text |  |  |  |  |  |  |
| Imou fixed | normal |  |  |  |  |  |  |
| Imou PTZ | normal |  |  |  |  |  |  |
| Imou wrong credentials | failure |  |  |  |  | n/a |  |
| Imou wrong IP | failure |  |  |  |  | n/a |  |

## Go/no-go notes

Report:

- whether scene description is good enough for useful answers;
- whether visible text is readable at expected distance;
- whether object/person counting is roughly reliable;
- capture latency for USB and RTSP;
- RTSP connect behavior for wrong IP and wrong credentials;
- whether OpenCV is acceptable as the task 2 runtime dependency.
