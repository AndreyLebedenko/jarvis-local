#!/usr/bin/env python3
"""RTSP discovery probe for story-v1.6.2 task 1 (LAN camera half).

Answers three questions the OpenCV spike cannot answer quickly, because a
wrong URL there costs a 30-second VideoCapture timeout:

  1. Are the credentials accepted at all (401 vs 200)?
  2. Does a given stream path exist (200 vs 404)?
  3. What does each channel actually carry (resolution from the SDP)?

Speaks RTSP over a raw socket with Digest auth, so it needs no ffmpeg and
no OpenCV. Hardware-dependent: the human runs it, not CI.

The password is never a command-line argument and is never printed; it is
read interactively unless JARVIS_RTSP_PASSWORD is set in the environment.

Examples:

  python -m manual.manual_check_rtsp_discovery --host 192.168.1.108 --user myuser
  python -m manual.manual_check_rtsp_discovery --host 192.168.1.108 --user myuser \
      --path "/cam/realmonitor?channel=1&subtype=0"
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import socket
import time
from dataclasses import dataclass

DEFAULT_PATHS: tuple[str, ...] = (
    "/cam/realmonitor?channel=1&subtype=0",
    "/cam/realmonitor?channel=1&subtype=1",
    "/cam/realmonitor?channel=2&subtype=0",
    "/cam/realmonitor?channel=2&subtype=1",
)
CONTROL_PATH = "/jarvis/nonexistent/control-path"
SOCKET_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class RtspResponse:
    status_line: str
    headers: dict[str, str]
    body: str
    wall_seconds: float


def parse_response(raw: str, wall_seconds: float) -> RtspResponse:
    head, _, body = raw.partition("\r\n\r\n")
    lines = head.split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return RtspResponse(lines[0], headers, body, wall_seconds)


def send_request(host: str, port: int, request: str) -> RtspResponse:
    started = time.perf_counter()
    with socket.create_connection((host, port), SOCKET_TIMEOUT_SECONDS) as sock:
        sock.settimeout(SOCKET_TIMEOUT_SECONDS)
        sock.sendall(request.encode("ascii"))
        chunks: list[bytes] = []
        while True:
            try:
                chunk = sock.recv(4096)
            except TimeoutError:
                break
            if not chunk:
                break
            chunks.append(chunk)
            if b"\r\n\r\n" in b"".join(chunks):
                break
    raw = b"".join(chunks).decode("utf-8", errors="replace")
    return parse_response(raw, time.perf_counter() - started)


def parse_digest_challenge(header: str) -> dict[str, str]:
    return dict(re.findall(r'(\w+)="([^"]*)"', header))


def digest_response(
    user: str, password: str, challenge: dict[str, str], method: str, uri: str
) -> str:
    def md5(value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    ha1 = md5(f"{user}:{realm}:{password}")
    ha2 = md5(f"{method}:{uri}")
    return md5(f"{ha1}:{nonce}:{ha2}")


def build_request(method: str, uri: str, cseq: int, authorization: str | None) -> str:
    lines = [
        f"{method} {uri} RTSP/1.0",
        f"CSeq: {cseq}",
        "User-Agent: jarvis-rtsp-discovery",
        "Accept: application/sdp",
    ]
    if authorization is not None:
        lines.append(f"Authorization: {authorization}")
    return "\r\n".join(lines) + "\r\n\r\n"


def describe(host: str, port: int, path: str, user: str, password: str) -> RtspResponse:
    uri = f"rtsp://{host}:{port}{path}"
    unauthorized = send_request(host, port, build_request("DESCRIBE", uri, 1, None))
    if not unauthorized.status_line.startswith("RTSP/1.0 401"):
        return unauthorized

    challenge_header = unauthorized.headers.get("www-authenticate", "")
    challenge = parse_digest_challenge(challenge_header)
    response = digest_response(user, password, challenge, "DESCRIBE", uri)
    authorization = (
        f'Digest username="{user}", realm="{challenge.get("realm", "")}", '
        f'nonce="{challenge.get("nonce", "")}", uri="{uri}", response="{response}"'
    )
    authorized = send_request(
        host, port, build_request("DESCRIBE", uri, 2, authorization)
    )
    return RtspResponse(
        authorized.status_line,
        authorized.headers,
        authorized.body,
        unauthorized.wall_seconds + authorized.wall_seconds,
    )


def summarize_sdp(body: str) -> list[str]:
    facts: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith(
            ("m=", "s=", "a=rtpmap:", "a=control:", "a=x-dimensions", "a=framerate:")
        ):
            facts.append(stripped)
    return facts


def read_password() -> str:
    from_env = os.environ.get("JARVIS_RTSP_PASSWORD")
    if from_env:
        return from_env
    return getpass.getpass("RTSP password (not echoed, not logged): ")


def probe_path(args: argparse.Namespace, path: str, password: str) -> None:
    print(f"\n=== DESCRIBE {path} ===")
    try:
        response = describe(args.host, args.port, path, args.user, password)
    except OSError as exc:
        print(f"transport error: {exc}")
        return
    print(f"status: {response.status_line}")
    print(f"wall_seconds: {response.wall_seconds:.3f}")
    if response.body.strip():
        for fact in summarize_sdp(response.body):
            print(f"  {fact}")


def run(args: argparse.Namespace) -> None:
    password = read_password()
    paths = args.path or list(DEFAULT_PATHS)
    print(f"host: {args.host}:{args.port}")
    print(f"user: {args.user}")
    for path in paths:
        probe_path(args, path, password)
    print("\n=== control: a path that cannot exist ===")
    probe_path(args, CONTROL_PATH, password)
    print(
        "\nRead the control result first. If it returns 404 while real paths "
        "return 200, path errors are distinguishable. If it also returns 200, "
        "this camera accepts any path and the channel numbers prove nothing "
        "on their own - compare the SDP media lines instead."
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=554)
    parser.add_argument("--user", required=True)
    parser.add_argument(
        "--path",
        action="append",
        help="Stream path to probe. May be repeated. Defaults to Dahua channel 1-2.",
    )
    return parser


if __name__ == "__main__":
    run(build_arg_parser().parse_args())
