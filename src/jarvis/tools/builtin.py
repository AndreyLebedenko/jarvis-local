"""In-process builtin tools for delegated local control and sensors."""

import base64
from collections.abc import Awaitable, Callable

from jarvis.core.config import BUILTIN_TOOL_PROVIDER_NAME, DataBoundary
from jarvis.dialog.thinking_mode import ReasoningLevel, ReasoningLevelState
from jarvis.files import (
    SessionFileError,
    SessionFileRepository,
    SessionFileScope,
    SessionFileStat,
)
from jarvis.inputs.camera import (
    CameraCapture,
    CameraDisabledError,
    CameraError,
    UnknownCameraSourceError,
)
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
_WRITE_SESSION_FILE_TOOL_NAME = "write_session_file"
_READ_SESSION_TEXT_TOOL_NAME = "read_session_text"
_VIEW_SESSION_IMAGE_TOOL_NAME = "view_session_image"
_STAT_SESSION_FILE_TOOL_NAME = "stat_session_file"
_LIST_SESSION_FILES_TOOL_NAME = "list_session_files"
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
        on_camera_capture: Callable[[str], Awaitable[None]] | None = None,
        on_camera_failure: Callable[[str], Awaitable[None]] | None = None,
        session_file_repository: SessionFileRepository | None = None,
        session_file_scope: Callable[[], SessionFileScope] | None = None,
    ) -> None:
        self._thinking_mode = thinking_mode
        self._memory_file_repository = memory_file_repository
        self._camera_capture = camera_capture
        self._on_camera_capture = on_camera_capture
        self._on_camera_failure = on_camera_failure
        self._session_file_repository = session_file_repository
        self._session_file_scope = session_file_scope

    def register_tools(self, registry: ToolRegistry) -> None:
        registry.set_provider_tools(
            BUILTIN_TOOL_PROVIDER_NAME,
            _builtin_tools(
                self._camera_capture,
                include_session_files=self._session_file_repository is not None,
            ),
        )

    async def call_tool(self, name: str, arguments: ToolArguments) -> ToolCallResult:
        if name == _REASONING_TOOL_NAME:
            return await self._set_reasoning_level(arguments)
        if name == _MEMORY_TOOL_NAME:
            return self._remember(arguments)
        if name == CAMERA_TOOL_NAME:
            return await self._capture_camera_image(arguments)
        if name == _WRITE_SESSION_FILE_TOOL_NAME:
            return self._write_session_file(arguments)
        if name == _READ_SESSION_TEXT_TOOL_NAME:
            return self._read_session_text(arguments)
        if name == _VIEW_SESSION_IMAGE_TOOL_NAME:
            return self._view_session_image(arguments)
        if name == _STAT_SESSION_FILE_TOOL_NAME:
            return self._stat_session_file(arguments)
        if name == _LIST_SESSION_FILES_TOOL_NAME:
            return self._list_session_files(arguments)
        return ToolCallResult(
            content=f"Unknown builtin tool: {name}",
            is_error=True,
        )

    def _write_session_file(self, arguments: ToolArguments) -> ToolCallResult:
        rejected = _reject_unknown_arguments(arguments, {"name", "content"})
        if rejected is not None:
            return rejected
        name = arguments.get("name")
        content = arguments.get("content")
        if not isinstance(name, str):
            return ToolCallResult(content="name must be a string", is_error=True)
        if not isinstance(content, str):
            return ToolCallResult(content="content must be a string", is_error=True)
        repository, scope = self._session_files()
        if repository is None:
            return _SESSION_FILES_UNAVAILABLE
        try:
            result = repository.write_text(scope, name, content)
        except SessionFileError as exc:
            return _session_file_error_result(exc)
        except OSError as exc:
            return _filesystem_error_result(exc)
        return ToolCallResult(
            content=(
                f"Saved as {result.storage_name} ({result.bytes} bytes). The "
                "requested name was changed; use this storage name for future "
                "read/view/stat calls."
            ),
            structured_content={
                "storage_name": result.storage_name,
                "bytes": result.bytes,
            },
        )

    def _read_session_text(self, arguments: ToolArguments) -> ToolCallResult:
        parsed = self._session_file_name(arguments)
        if isinstance(parsed, ToolCallResult):
            return parsed
        repository, scope, name = parsed
        try:
            return ToolCallResult(content=repository.read_text(scope, name))
        except SessionFileError as exc:
            return _session_file_error_result(exc)
        except OSError as exc:
            return _filesystem_error_result(exc)

    def _view_session_image(self, arguments: ToolArguments) -> ToolCallResult:
        parsed = self._session_file_name(arguments)
        if isinstance(parsed, ToolCallResult):
            return parsed
        repository, scope, name = parsed
        try:
            view = repository.view_image_bytes(scope, name)
        except SessionFileError as exc:
            return _session_file_error_result(exc)
        except OSError as exc:
            return _filesystem_error_result(exc)
        return ToolCallResult(
            content=f"Loaded image {name} for this turn.",
            images_b64=(base64.b64encode(view.data).decode("ascii"),),
            data_boundary=DataBoundary.LOCAL,
        )

    def _stat_session_file(self, arguments: ToolArguments) -> ToolCallResult:
        parsed = self._session_file_name(arguments)
        if isinstance(parsed, ToolCallResult):
            return parsed
        repository, scope, name = parsed
        try:
            info = repository.stat(scope, name)
        except SessionFileError as exc:
            return _session_file_error_result(exc)
        except OSError as exc:
            return _filesystem_error_result(exc)
        return ToolCallResult(
            content=f"{info.storage_name}: {info.bytes} bytes, {info.scope} scope.",
            structured_content=_stat_payload(info),
        )

    def _list_session_files(self, arguments: ToolArguments) -> ToolCallResult:
        rejected = _reject_unknown_arguments(arguments, set())
        if rejected is not None:
            return rejected
        repository, scope = self._session_files()
        if repository is None:
            return _SESSION_FILES_UNAVAILABLE
        try:
            entries = repository.list(scope)
        except SessionFileError as exc:
            return _session_file_error_result(exc)
        except OSError as exc:
            return _filesystem_error_result(exc)
        return ToolCallResult(
            content=f"{len(entries)} session file(s) in scope.",
            structured_content={"files": [_stat_payload(entry) for entry in entries]},
        )

    def _session_files(
        self,
    ) -> tuple[SessionFileRepository, SessionFileScope] | tuple[None, None]:
        if self._session_file_repository is None or self._session_file_scope is None:
            return None, None
        return self._session_file_repository, self._session_file_scope()

    def _session_file_name(
        self, arguments: ToolArguments
    ) -> tuple[SessionFileRepository, SessionFileScope, str] | ToolCallResult:
        rejected = _reject_unknown_arguments(arguments, {"name"})
        if rejected is not None:
            return rejected
        name = arguments.get("name")
        if not isinstance(name, str):
            return ToolCallResult(content="name must be a string", is_error=True)
        repository, scope = self._session_files()
        if repository is None:
            return _SESSION_FILES_UNAVAILABLE
        return repository, scope, name

    async def _capture_camera_image(self, arguments: ToolArguments) -> ToolCallResult:
        unknown_arguments = set(arguments) - {"source"}
        if unknown_arguments:
            return ToolCallResult(
                content=(
                    "capture_camera_image takes only an optional 'source': "
                    f"{', '.join(sorted(unknown_arguments))}"
                ),
                is_error=True,
            )
        if self._camera_capture is None:
            return ToolCallResult(content="Camera is not configured", is_error=True)
        source_name = arguments.get("source")
        if source_name is not None and not isinstance(source_name, str):
            return ToolCallResult(content="source must be a string", is_error=True)
        try:
            frame = await self._camera_capture.capture(source_name)
        except CameraDisabledError as exc:
            return ToolCallResult(content=str(exc), is_error=True)
        except UnknownCameraSourceError as exc:
            # No camera was touched, so this is not a capture failure and
            # must not degrade the module. The model gets the catalogue
            # back and can correct itself within the same turn.
            return ToolCallResult(
                content=f"{exc}. {_camera_source_catalogue(self._camera_capture)}",
                is_error=True,
            )
        except CameraError as exc:
            if self._on_camera_failure is not None:
                await self._on_camera_failure(
                    self._camera_capture.resolve_source_name(source_name)
                )
            return ToolCallResult(content=str(exc), is_error=True)
        if self._on_camera_capture is not None:
            await self._on_camera_capture(frame.source)
        return ToolCallResult(
            content=f"Captured one camera image from {frame.source} for this turn.",
            structured_content={
                "source": frame.source,
                "data_boundary": frame.data_boundary.value,
            },
            images_b64=(base64.b64encode(frame.jpeg_bytes).decode("ascii"),),
            data_boundary=frame.data_boundary,
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


_SESSION_FILES_UNAVAILABLE = ToolCallResult(
    content="Session files are not available.", is_error=True
)


def _reject_unknown_arguments(
    arguments: ToolArguments, allowed: set[str]
) -> ToolCallResult | None:
    unknown = set(arguments) - allowed
    if not unknown:
        return None
    return ToolCallResult(
        content=f"Unexpected argument(s): {', '.join(sorted(unknown))}",
        is_error=True,
    )


def _session_file_error_result(exc: SessionFileError) -> ToolCallResult:
    # Every SessionFileError subclass carries its own distinct, model-facing
    # message (missing / not-text / not-image / oversize / deny-listed /
    # invalid-name / no-active-session), so the model gets a specific reason
    # rather than one flattened "failed".
    return ToolCallResult(content=str(exc), is_error=True)


def _filesystem_error_result(exc: OSError) -> ToolCallResult:
    return ToolCallResult(content=f"Filesystem error: {exc}", is_error=True)


def _stat_payload(info: SessionFileStat) -> JSONObject:
    return {
        "storage_name": info.storage_name,
        "bytes": info.bytes,
        "ext": info.ext,
        "session_id": info.session_id,
        "scope": info.scope,
        "mtime_utc": info.mtime_utc,
    }


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


def _camera_source_catalogue(camera_capture: CameraCapture) -> str:
    """What the model is told about the cameras it may address. The
    description is the source's own, so a motorized lens can say that it
    shows wherever it was last aimed instead of implying a fixed view."""
    entries = "; ".join(
        f"{source.name} - {source.description}" if source.description else source.name
        for source in camera_capture.sources
    )
    return f"Configured sources: {entries}."


def _camera_tool_description(camera_capture: CameraCapture | None) -> str:
    base = (
        "Capture one image from a camera when the user asks to look. "
        "One call captures from one camera; to look through several, "
        "make several calls."
    )
    if camera_capture is None:
        return base
    default_source = camera_capture.sources[0].name
    return (
        f"{base} {_camera_source_catalogue(camera_capture)} "
        f"Omitting 'source' uses {default_source}."
    )


def _camera_schema(camera_capture: CameraCapture | None) -> JSONObject:
    source: JSONObject = {
        "type": "string",
        "description": "Name of the camera to capture from.",
    }
    if camera_capture is not None:
        source["enum"] = [entry.name for entry in camera_capture.sources]
    return {
        "type": "object",
        "properties": {"source": source},
        "additionalProperties": False,
    }


def _builtin_tools(
    camera_capture: CameraCapture | None = None,
    *,
    include_session_files: bool = False,
) -> list[RegisteredTool]:
    tools = [
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
            description=_camera_tool_description(camera_capture),
            schema=_camera_schema(camera_capture),
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
    if include_session_files:
        tools.extend(_session_file_tools())
    return tools


def _session_file_tools() -> list[RegisteredTool]:
    name_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Storage name returned by write_session_file or list_session_files."
                ),
            }
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    return [
        RegisteredTool(
            name=_WRITE_SESSION_FILE_TOOL_NAME,
            description=(
                "Save a UTF-8 text file into the current chat session. Returns a "
                "generated storage name; the requested name is a label only. "
                "Create-only: it never overwrites and cannot delete."
            ),
            schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Requested file label, e.g. notes.md.",
                    },
                    "content": {"type": "string"},
                },
                "required": ["name", "content"],
                "additionalProperties": False,
            },
            provider=BUILTIN_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
        RegisteredTool(
            name=_READ_SESSION_TEXT_TOOL_NAME,
            description=(
                "Read a text file from the session file scope by its storage "
                "name. Errors if the file is binary; use stat or view instead."
            ),
            schema=name_schema,
            provider=BUILTIN_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
        RegisteredTool(
            name=_VIEW_SESSION_IMAGE_TOOL_NAME,
            description=(
                "Look at a PNG or JPEG image from the session file scope by its "
                "storage name; the image is attached for this turn."
            ),
            schema=name_schema,
            provider=BUILTIN_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
        RegisteredTool(
            name=_STAT_SESSION_FILE_TOOL_NAME,
            description=(
                "Get metadata (size, extension, session, scope, mtime) for a "
                "session file by its storage name, including binary files."
            ),
            schema=name_schema,
            provider=BUILTIN_TOOL_PROVIDER_NAME,
            provider_kind="builtin",
            data_boundary=DataBoundary.LOCAL,
        ),
        RegisteredTool(
            name=_LIST_SESSION_FILES_TOOL_NAME,
            description=(
                "List files in the session file scope with their storage name, "
                "size, mtime, session id, and scope."
            ),
            schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
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
