#!/usr/bin/env python3
"""Manual handoff for story-v1.6.2 task 1: camera spike.

Captures one static frame from a USB camera and/or RTSP URL, saves the
frame for eyeballing, then sends it to the configured local Ollama model
through the verified `images` field. This is hardware-dependent and is
run by the human, not by automated CI.

OpenCV is intentionally an ad hoc spike dependency here. Install it only
for this manual run unless task 2 later promotes it to a real runtime
dependency:

  python -m pip install --force-reinstall "numpy==1.26.4" "opencv-python==4.11.0.86"

Do not install unpinned `opencv-python`: as of 2026-07-20 it resolves to
OpenCV 5 and NumPy 2.4.6, which conflicts with the owner's SciPy 1.12.0
environment.

Examples:

  python -m manual.manual_check_camera_spike --usb-index 0 --label c920
  python -m manual.manual_check_camera_spike --usb-index 0 --opencv-backend dshow
  python -m manual.manual_check_camera_spike --rtsp-url RTSP_URL --label imou-fixed
  python -m manual.manual_check_camera_spike --rtsp-url BAD_URL --expect-capture-failure
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx

from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel

DEFAULT_OUT_DIR = Path("manual_check_camera_spike_out")
DEFAULT_PROBES: tuple[str, ...] = (
    "Describe the scene in the attached camera frame in one concise paragraph.",
    "Read any visible text in the attached camera frame. "
    "If there is no readable text, say so.",
    "Count the prominent objects or people visible in the attached camera frame "
    "and mention uncertainty.",
)

SourceKind = Literal["usb", "rtsp"]
OpenCvBackend = Literal["auto", "dshow", "msmf", "ffmpeg"]


@dataclass(frozen=True)
class CameraSource:
    kind: SourceKind
    label: str
    address: int | str
    opencv_backend: OpenCvBackend
    frame_width: int | None
    frame_height: int | None
    fourcc: str | None


@dataclass(frozen=True)
class CaptureResult:
    source: CameraSource
    success: bool
    output_path: Path | None
    open_seconds: float
    open_to_frame_seconds: float
    width: int | None = None
    height: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class ProbeRequest:
    source_label: str
    question: str
    payload: dict[str, object]


@dataclass(frozen=True)
class ProbeResult:
    source_label: str
    question: str
    wall_seconds: float
    success: bool
    content_text: str
    eval_count: int | None
    error: str | None = None


def safe_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    cleaned = cleaned.strip(".-")
    return cleaned or "camera"


def redact_uri(uri: str) -> str:
    split = urlsplit(uri)
    if not split.username and not split.password:
        return uri
    host = split.hostname or ""
    port = f":{split.port}" if split.port is not None else ""
    redacted = SplitResult(
        scheme=split.scheme,
        netloc=f"<credentials>@{host}{port}",
        path=split.path,
        query=split.query,
        fragment=split.fragment,
    )
    return urlunsplit(redacted)


def read_frame_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build_probe_request(
    backend: OllamaBackend,
    source_label: str,
    frame_b64: str,
    question: str,
) -> ProbeRequest:
    message: dict[str, object] = {"role": "user", "content": question}
    payload = backend.build_payload(
        [message], [frame_b64], reasoning_level=ReasoningLevel.OFF
    )
    return ProbeRequest(source_label=source_label, question=question, payload=payload)


def classify_chunks(
    source_label: str,
    question: str,
    chunks: list[dict[str, object]],
    wall_seconds: float,
    error: str | None = None,
) -> ProbeResult:
    content = ""
    eval_count: int | None = None
    saw_done = False
    for chunk in chunks:
        message = chunk.get("message")
        if isinstance(message, dict):
            text = message.get("content")
            if isinstance(text, str):
                content += text
        if chunk.get("done") is True:
            saw_done = True
            raw_eval_count = chunk.get("eval_count")
            if isinstance(raw_eval_count, int):
                eval_count = raw_eval_count
    return ProbeResult(
        source_label=source_label,
        question=question,
        wall_seconds=wall_seconds,
        success=saw_done and error is None,
        content_text=content,
        eval_count=eval_count,
        error=error,
    )


def import_cv2():
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV is required for the camera spike. Run: "
            "python -m pip install opencv-python"
        ) from exc
    return cv2


def capture_one_frame(source: CameraSource, out_dir: Path) -> CaptureResult:
    cv2 = import_cv2()
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / (
        f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_label(source.label)}.jpg"
    )

    t0 = time.perf_counter()
    capture = open_video_capture(cv2, source)
    apply_capture_settings(cv2, capture, source)
    open_seconds = time.perf_counter() - t0
    if not capture.isOpened():
        capture.release()
        return CaptureResult(
            source=source,
            success=False,
            output_path=None,
            open_seconds=open_seconds,
            open_to_frame_seconds=time.perf_counter() - t0,
            error="VideoCapture did not open",
        )

    ok, frame = capture.read()
    open_to_frame_seconds = time.perf_counter() - t0
    capture.release()
    if not ok or frame is None:
        return CaptureResult(
            source=source,
            success=False,
            output_path=None,
            open_seconds=open_seconds,
            open_to_frame_seconds=open_to_frame_seconds,
            error="VideoCapture opened but did not return a frame",
        )

    saved = cv2.imwrite(str(output_path), frame)
    if not saved:
        return CaptureResult(
            source=source,
            success=False,
            output_path=None,
            open_seconds=open_seconds,
            open_to_frame_seconds=open_to_frame_seconds,
            error=f"OpenCV failed to write {output_path}",
        )
    height, width = frame.shape[:2]
    return CaptureResult(
        source=source,
        success=True,
        output_path=output_path,
        open_seconds=open_seconds,
        open_to_frame_seconds=open_to_frame_seconds,
        width=width,
        height=height,
    )


async def run_probe(client: httpx.AsyncClient, request: ProbeRequest) -> ProbeResult:
    chunks: list[dict[str, object]] = []
    error: str | None = None
    t0 = time.perf_counter()
    try:
        async with client.stream("POST", "/api/chat", json=request.payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    chunks.append(json.loads(line))
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        error = str(exc)
    return classify_chunks(
        request.source_label,
        request.question,
        chunks,
        time.perf_counter() - t0,
        error,
    )


def print_capture_result(result: CaptureResult) -> None:
    address = (
        result.source.address
        if result.source.kind == "usb"
        else redact_uri(str(result.source.address))
    )
    print(f"\n=== capture: {result.source.label} ({result.source.kind}) ===")
    print(f"address: {address}")
    print(f"opencv_backend: {result.source.opencv_backend}")
    print(f"requested_resolution: {format_requested_resolution(result.source)}")
    print(f"requested_fourcc: {result.source.fourcc or 'default'}")
    print(f"success: {result.success}")
    print(f"open_seconds: {result.open_seconds:.3f}")
    print(f"open_to_frame_seconds: {result.open_to_frame_seconds:.3f}")
    if result.output_path is not None:
        print(f"frame_path: {result.output_path}")
    if result.width is not None and result.height is not None:
        print(f"resolution: {result.width}x{result.height}")
    if result.error:
        print(f"error: {result.error}")


def print_request(request: ProbeRequest) -> None:
    payload = dict(request.payload)
    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        message = dict(messages[0])
        if "images" in message:
            message["images"] = ["<base64 image omitted; count=1>"]
        payload["messages"] = [message]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_probe_result(result: ProbeResult) -> None:
    print(f"\n--- probe: {result.source_label} ---")
    print(f"question: {result.question}")
    print(f"wall_seconds: {result.wall_seconds:.2f}")
    print(f"success: {result.success}")
    print(f"eval_count: {result.eval_count}")
    if result.error:
        print(f"error: {result.error}")
    print(f"answer: {result.content_text!r}")


async def run(args: argparse.Namespace) -> None:
    source = build_source(args)
    result = capture_one_frame(source, args.out_dir)
    print_capture_result(result)
    if not result.success:
        if args.expect_capture_failure:
            return
        raise SystemExit(2)
    if args.expect_capture_failure:
        raise SystemExit("Expected capture failure, but capture succeeded.")
    if result.output_path is None:
        raise SystemExit("Capture succeeded without an output path.")

    frame_b64 = read_frame_b64(result.output_path)
    settings = load_settings()
    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = OllamaBackend(EventBus(), settings.backend, client=client)
        print(f"\nOllama endpoint: {settings.backend.endpoint}")
        print(f"Model: {settings.backend.model}")
        for question in args.probe:
            request = build_probe_request(backend, source.label, frame_b64, question)
            print(f"\n--- request: {source.label} ---")
            print_request(request)
            print_probe_result(await run_probe(client, request))


def build_source(args: argparse.Namespace) -> CameraSource:
    fourcc = normalize_fourcc(args.fourcc)
    if args.rtsp_url:
        return CameraSource(
            "rtsp",
            args.label or "rtsp-camera",
            args.rtsp_url,
            args.opencv_backend,
            args.frame_width,
            args.frame_height,
            fourcc,
        )
    return CameraSource(
        "usb",
        args.label or f"usb-{args.usb_index}",
        args.usb_index,
        args.opencv_backend,
        args.frame_width,
        args.frame_height,
        fourcc,
    )


def open_video_capture(cv2, source: CameraSource):
    if source.opencv_backend == "auto":
        return cv2.VideoCapture(source.address)
    backend_api = {
        "dshow": cv2.CAP_DSHOW,
        "msmf": cv2.CAP_MSMF,
        "ffmpeg": cv2.CAP_FFMPEG,
    }[source.opencv_backend]
    return cv2.VideoCapture(source.address, backend_api)


def apply_capture_settings(cv2, capture, source: CameraSource) -> None:
    if source.fourcc:
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*source.fourcc))
    if source.frame_width is not None:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, source.frame_width)
    if source.frame_height is not None:
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, source.frame_height)


def format_requested_resolution(source: CameraSource) -> str:
    if source.frame_width is None and source.frame_height is None:
        return "default"
    width = source.frame_width if source.frame_width is not None else "default"
    height = source.frame_height if source.frame_height is not None else "default"
    return f"{width}x{height}"


def normalize_fourcc(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.upper()
    if len(normalized) != 4:
        raise ValueError("--fourcc must be exactly four characters, for example MJPG")
    return normalized


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--usb-index", type=int, default=0)
    source.add_argument("--rtsp-url")
    parser.add_argument(
        "--opencv-backend",
        choices=("auto", "dshow", "msmf", "ffmpeg"),
        default="auto",
        help="OpenCV VideoCapture backend. Try dshow for slow Windows USB capture.",
    )
    parser.add_argument("--frame-width", type=int, help="Requested capture width.")
    parser.add_argument("--frame-height", type=int, help="Requested capture height.")
    parser.add_argument(
        "--fourcc",
        help="Requested four-character pixel format, for example MJPG for C920 1080p.",
    )
    parser.add_argument("--label", help="Human-readable source label for output files.")
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Frame output directory."
    )
    parser.add_argument(
        "--probe",
        action="append",
        default=list(DEFAULT_PROBES),
        help="Probe question to ask about the captured frame. May be repeated.",
    )
    parser.add_argument(
        "--expect-capture-failure",
        action="store_true",
        help="Use for wrong IP/credentials RTSP checks; exits 0 when capture fails.",
    )
    return parser


if __name__ == "__main__":
    asyncio.run(run(build_arg_parser().parse_args()))
