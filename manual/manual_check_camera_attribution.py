#!/usr/bin/env python3
"""Manual handoff for story-v1.6.2 task 7: frame provenance.

Drives one real turn through the production path - `ToolAwareDialog` over
the live Ollama endpoint, the real builtin camera tool, the real capture
core - and asks the model a question it can only answer correctly if each
frame is bound to the source that produced it.

This is the check that proves the provenance fix. Set it up so the answer
cannot be guessed: aim the motorized `detail` lens at something the fixed
`wide` lens cannot see, then ask which camera shows it. Two frames in one
turn used to arrive as an unlabeled pair of images appended to the user
message, and the model could only attribute them by order.

Hardware- and endpoint-dependent, so the human runs it and reports the
output.

Usage:
  python -m manual.manual_check_camera_attribution
  python -m manual.manual_check_camera_attribution --expect-captures 1 \
      --ask "What does the detail lens see?"
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx

from jarvis.core.bus import EventBus
from jarvis.core.config import BUILTIN_TOOL_PROVIDER_NAME, load_settings
from jarvis.dialog.backend import OllamaBackend, ResponseToken
from jarvis.dialog.thinking_mode import ReasoningLevelState
from jarvis.dialog.tool_presentation import ToolAwareDialog, build_tool_presentation
from jarvis.inputs.camera import CameraCapture, CameraState, describe_source
from jarvis.memory.files import MemoryFileRepository, build_memory_file_specs
from jarvis.tools.builtin import BuiltinToolProvider
from jarvis.tools.host import McpHost
from jarvis.tools.interception import ToolCallFinished
from jarvis.tools.registry import ToolRegistry

DEFAULT_QUESTION = (
    "Look through every camera you have and describe what each one shows. "
    "Name the camera before describing it."
)


async def run(args: argparse.Namespace) -> int:
    settings = load_settings()
    bus = EventBus()
    camera_state = CameraState(True)
    camera_capture = CameraCapture(settings.camera, camera_state)

    print("Configured sources:")
    for source in camera_capture.sources:
        print(f"  {describe_source(source)} - {source.description}")

    captures: list[str] = []
    boundaries: list[str] = []

    async def on_capture(source: str) -> None:
        captures.append(source)

    async def on_tool_finished(event: ToolCallFinished) -> None:
        boundaries.append(event.data_boundary.value)
        print(
            f"  [tool] {event.tool_name} ok={event.ok} "
            f"boundary={event.data_boundary.value} in {event.duration_seconds:.2f} s"
        )

    bus.subscribe(ToolCallFinished, on_tool_finished)

    answer: list[str] = []

    async def on_token(event: ResponseToken) -> None:
        answer.append(event.text)

    bus.subscribe(ResponseToken, on_token)

    registry = ToolRegistry()
    provider = BuiltinToolProvider(
        thinking_mode=ReasoningLevelState(bus),
        memory_file_repository=MemoryFileRepository(
            build_memory_file_specs(settings.memory)
        ),
        camera_capture=camera_capture,
        on_camera_capture=on_capture,
    )
    provider.register_tools(registry)
    for tool in registry.all():
        registry.set_tool_enabled(tool.name, tool.name == "capture_camera_image")

    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        host = McpHost(
            bus,
            settings.mcp,
            registry=registry,
            builtin_clients={BUILTIN_TOOL_PROVIDER_NAME: provider},
            ui_language=settings.ui.language,
        )
        dialog = ToolAwareDialog(
            OllamaBackend(bus, settings.backend, client=client),
            bus,
            registry,
            host.dispatcher,
            build_tool_presentation(settings.mcp.presentation_strategy),
            max_tool_calls_per_turn=settings.mcp.max_tool_calls_per_turn,
        )

        print(f"\nModel: {settings.backend.model}")
        print(f"Presentation: {settings.mcp.presentation_strategy}")
        print(f"Tool call budget: {settings.mcp.max_tool_calls_per_turn}")
        print(f"\n--- asking ---\n{args.ask}\n")
        started = time.perf_counter()
        await dialog.chat(
            [
                {"role": "system", "content": settings.prompts.system},
                {"role": "user", "content": args.ask},
            ]
        )
        elapsed = time.perf_counter() - started

    print(f"\n--- answer in {elapsed:.2f} s ---")
    print("".join(answer).strip())
    print(f"\nCaptured from: {captures}; boundaries reported: {boundaries}")
    if len(captures) < args.expect_captures:
        print(
            f"NOTE: expected at least {args.expect_captures} capture(s) and got "
            f"{len(captures)}, so this run does not check what it was meant to. "
            "Ask again, naming the cameras explicitly."
        )
        return 1
    print(
        "Judge the answer yourself: it passes only if each camera is described "
        "with what that camera actually shows."
    )
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ask", default=DEFAULT_QUESTION)
    parser.add_argument(
        "--expect-captures",
        type=int,
        default=2,
        help=(
            "Captures this question should produce. Attribution needs at "
            "least two; a question naming one camera checks source selection "
            "and needs one."
        ),
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(build_arg_parser().parse_args())))
