#!/usr/bin/env python3
"""Manual handoff for story-v1.6.2 task 6: named camera sources.

Captures one static frame from each named source in the loaded config,
through the real capture core - `CameraCapture` over the OpenCV backend -
rather than through spike code, and saves each frame for eyeballing. This
is hardware-dependent and is run by the human, not by automated CI.

The failure paths matter as much as the successful capture: a wrong
password and an unreachable host are checked with `--expect-failure`,
which reports the wall time and asserts that the message names the source
without exposing the password.

Examples:

  python -m manual.manual_check_camera_sources
  python -m manual.manual_check_camera_sources --source wide --source detail
  python -m manual.manual_check_camera_sources --source wide --password WRONG \
      --expect-failure
  python -m manual.manual_check_camera_sources --source wide --host 192.168.1.199 \
      --expect-failure
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import replace
from pathlib import Path

from jarvis.core.config import CameraSettings, LanCameraSource, load_settings
from jarvis.inputs.camera import (
    CameraCapture,
    CameraError,
    CameraState,
    UnknownCameraSourceError,
    describe_source,
)

DEFAULT_OUT_DIR = Path("manual_check_camera_sources_out")


async def run(args: argparse.Namespace) -> int:
    settings = load_settings()
    camera = _override(settings.camera, args)
    names = args.source or [source.name for source in camera.resolved_sources]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Timeout: {camera.capture_timeout_seconds} s")
    print("Configured sources:")
    for source in camera.resolved_sources:
        print(f"  {describe_source(source)} - {source.description or 'no description'}")

    capture = CameraCapture(camera, CameraState(True))
    failures = 0
    for name in names:
        failures += await _capture_one(capture, name, args)
    return failures


async def _capture_one(capture: CameraCapture, name: str, args) -> int:
    print(f"\n--- source: {name} ---")
    started = time.perf_counter()
    try:
        frame = await capture.capture(name)
    except UnknownCameraSourceError as exc:
        # Never absorbed by --expect-failure: a misspelled name would
        # otherwise pass as a proven wrong-password or bad-host result
        # while no camera was ever contacted.
        print(f"USAGE ERROR: {exc}")
        return 1
    except CameraError as exc:
        elapsed = time.perf_counter() - started
        print(f"FAILED after {elapsed:.3f} s: {exc}")
        if args.password and args.password in str(exc):
            print("LEAK: the error message contains the password")
            return 1
        return 0 if args.expect_failure else 1

    elapsed = time.perf_counter() - started
    path = args.out_dir / f"{frame.source}.jpg"
    path.write_bytes(frame.jpeg_bytes)
    print(
        f"OK in {elapsed:.3f} s, {len(frame.jpeg_bytes)} bytes, "
        f"boundary {frame.data_boundary.value}, saved to {path}"
    )
    return 1 if args.expect_failure else 0


def _override(camera: CameraSettings, args: argparse.Namespace) -> CameraSettings:
    """--password and --host rewrite the LAN sources in memory, so the wrong
    credential and unreachable host checks never require editing config.toml."""
    if args.password is None and args.host is None:
        return camera
    sources = tuple(
        replace(
            source,
            password=args.password if args.password is not None else source.password,
            host=args.host if args.host is not None else source.host,
        )
        if isinstance(source, LanCameraSource)
        else source
        for source in camera.resolved_sources
    )
    return replace(camera, sources=sources)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        help="Configured source name. Repeatable. Defaults to every source.",
    )
    parser.add_argument("--password", help="Override every LAN source's password.")
    parser.add_argument("--host", help="Override every LAN source's host.")
    parser.add_argument(
        "--expect-failure",
        action="store_true",
        help="Exit 0 when capture fails; use for wrong password and bad host.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(build_arg_parser().parse_args())))
