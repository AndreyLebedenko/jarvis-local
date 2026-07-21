"""In-process builtin tools for delegated local control and sensors."""

import base64
from collections.abc import Awaitable, Callable

from jarvis.core.config import BUILTIN_TOOL_PROVIDER_NAME, DataBoundary
from jarvis.dialog.thinking_mode import ReasoningLevel, ReasoningLevelState
from jarvis.inputs.camera import CameraCapture, CameraDisabledError, CameraError
from jarvis.memory.files import (
    MemoryFileId,
    MemoryFileOverCapError,
    MemoryFileRepository,
)
from jarvis.tools.json_types import JSONObject
from jarvis.tools.registry import RegisteredTool, ToolRegistry
from jarvis.tools.results import ToolArguments, ToolCallResult

_REASONING_TOOL_NAME = "set_reasoning_level"
_MEMORY_TOOL_NAME = "remember"
CAMERA_TOOL_NAME = "capture_camera_image"
_NEXT_SESSION_NOTE = (
    "The new content enters Jarvis's system prompt at the next session start."
)


class BuiltinToolProvider:
    def __init__(
        self,
        *,
        thinking_mode: ReasoningLevelState,
        memory_file_repository: MemoryFileRepository,
        camera_capture: CameraCapture | None = None,
        on_camera_capture: Callable[[], Awaitable[None]] | None = None,
        on_camera_failure: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._thinking_mode = thinking_mode
        self._memory_file_repository = memory_file_repository
        self._camera_capture = camera_capture
        self._on_camera_capture = on_camera_capture
        self._on_camera_failure = on_camera_failure

    def register_tools(self, registry: ToolRegistry) -> None:
        registry.set_provider_tools(BUILTIN_TOOL_PROVIDER_NAME, _builtin_tools())

    async def call_tool(self, name: str, arguments: ToolArguments) -> ToolCallResult:
        if name == _REASONING_TOOL_NAME:
            return await self._set_reasoning_level(arguments)
        if name == _MEMORY_TOOL_NAME:
            return self._remember(arguments)
        if name == CAMERA_TOOL_NAME:
            return await self._capture_camera_image(arguments)
        return ToolCallResult(
            content=f"Unknown builtin tool: {name}",
            is_error=True,
        )

    async def _capture_camera_image(self, arguments: ToolArguments) -> ToolCallResult:
        if arguments:
            return ToolCallResult(
                content="capture_camera_image takes no arguments", is_error=True
            )
        if self._camera_capture is None:
            return ToolCallResult(content="Camera is not configured", is_error=True)
        try:
            frame = await self._camera_capture.capture()
        except CameraDisabledError as exc:
            return ToolCallResult(content=str(exc), is_error=True)
        except CameraError as exc:
            if self._on_camera_failure is not None:
                await self._on_camera_failure()
            return ToolCallResult(content=str(exc), is_error=True)
        if self._on_camera_capture is not None:
            await self._on_camera_capture()
        return ToolCallResult(
            content="Captured one USB camera image for this turn.",
            structured_content={
                "source": frame.source,
                "data_boundary": frame.data_boundary.value,
            },
            images_b64=(base64.b64encode(frame.jpeg_bytes).decode("ascii"),),
        )

    async def _set_reasoning_level(self, arguments: ToolArguments) -> ToolCallResult:
        raw_level = arguments.get("level")
        if not isinstance(raw_level, str):
            return ToolCallResult(
                content="level must be one of: off, low, medium, high",
                is_error=True,
            )
        try:
            level = ReasoningLevel(raw_level)
        except ValueError:
            return ToolCallResult(
                content=f"Unsupported reasoning level: {raw_level!r}",
                is_error=True,
            )

        was_active = self._thinking_mode.level == level
        await self._thinking_mode.set_level(level, source="TOOL")
        state_text = "already active" if was_active else "set"
        return ToolCallResult(
            content=(
                f"Reasoning level {state_text}: {level.value}. "
                "This applies from the next accepted turn."
            ),
            structured_content={
                "level": level.value,
                "already_active": was_active,
                "applies": "next_turn",
            },
        )

    def _remember(self, arguments: ToolArguments) -> ToolCallResult:
        parsed = _parse_memory_arguments(arguments)
        if isinstance(parsed, ToolCallResult):
            return parsed
        file_id, mode, content = parsed
        current = self._memory_file_repository.read(file_id)
        next_content = (
            content
            if mode == "replace" or current.content == ""
            else f"{current.content}\n\n{content}"
        )
        try:
            written = (
                self._memory_file_repository.replace_with_backup(file_id, next_content)
                if mode == "replace"
                else self._memory_file_repository.write(file_id, next_content)
            )
        except MemoryFileOverCapError as error:
            label = _memory_file_label(file_id)
            return ToolCallResult(
                content=(
                    f"{label} is full: write would be {error.chars} chars, "
                    f"cap is {error.max_chars}, current size is {current.chars}. "
                    "Ask the user to prune it in the memory panel."
                ),
                is_error=True,
                structured_content={
                    "file": file_id.value,
                    "current_chars": current.chars,
                    "attempted_chars": error.chars,
                    "max_chars": error.max_chars,
                },
            )

        delta = written.chars - current.chars
        label = _memory_file_label(file_id)
        backup = f"{label}.bak" if mode == "replace" else None
        backup_note = (
            f" Previous version saved to {backup}." if backup is not None else ""
        )
        structured_content: JSONObject = {
            "file": file_id.value,
            "mode": mode,
            "chars": written.chars,
            "delta_chars": delta,
            "applies": "next_session",
        }
        if backup is not None:
            structured_content["backup"] = backup
        return ToolCallResult(
            content=(
                f"Wrote {label} with {mode}; size delta {delta:+d} chars. "
                f"{_NEXT_SESSION_NOTE}{backup_note}"
            ),
            structured_content=structured_content,
        )


def _parse_memory_arguments(
    arguments: ToolArguments,
) -> tuple[MemoryFileId, str, str] | ToolCallResult:
    raw_file = arguments.get("file")
    if raw_file == MemoryFileId.MEMORY.value:
        file_id = MemoryFileId.MEMORY
    elif raw_file == MemoryFileId.SELF.value:
        file_id = MemoryFileId.SELF
    else:
        return ToolCallResult(
            content="file must be either 'memory' or 'self'",
            is_error=True,
        )

    mode = arguments.get("mode")
    if mode not in {"append", "replace"}:
        return ToolCallResult(
            content="mode must be either 'append' or 'replace'",
            is_error=True,
        )

    raw_content = arguments.get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        return ToolCallResult(
            content="content must be a non-empty string",
            is_error=True,
        )
    return file_id, mode, raw_content.strip()


def _memory_file_label(file_id: MemoryFileId) -> str:
    return "memory.md" if file_id is MemoryFileId.MEMORY else "self.md"


def _builtin_tools() -> list[RegisteredTool]:
    return [
        RegisteredTool(
            name=_REASONING_TOOL_NAME,
            description=(
                "Set Jarvis's reasoning level for future turns. "
                "Use only when the user asks to change reasoning."
            ),
            schema=_reasoning_schema(),
            provider=BUILTIN_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
        RegisteredTool(
            name=CAMERA_TOOL_NAME,
            description=(
                "Capture one image from the local USB camera when the user asks "
                "to look at it."
            ),
            schema={"type": "object", "properties": {}, "additionalProperties": False},
            provider=BUILTIN_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
        RegisteredTool(
            name=_MEMORY_TOOL_NAME,
            description=(
                "Append or replace user-auditable Jarvis memory files. "
                "Use for explicit remember/correct-memory requests."
            ),
            schema=_memory_schema(),
            provider=BUILTIN_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
    ]


def _reasoning_schema() -> JSONObject:
    return {
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "enum": [level.value for level in ReasoningLevel],
            }
        },
        "required": ["level"],
        "additionalProperties": False,
    }


def _memory_schema() -> JSONObject:
    return {
        "type": "object",
        "properties": {
            "file": {"type": "string", "enum": ["memory", "self"]},
            "mode": {"type": "string", "enum": ["append", "replace"]},
            "content": {"type": "string", "minLength": 1},
        },
        "required": ["file", "mode", "content"],
        "additionalProperties": False,
    }
