from __future__ import annotations

from pathlib import Path

from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BUILTIN_TOOL_PROVIDER_NAME,
    CameraSettings,
    CameraSource,
    DataBoundary,
    LanCameraSource,
    McpSettings,
    MemorySettings,
    UsbCameraSource,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelChanged,
    ReasoningLevelState,
)
from jarvis.inputs.camera import CameraCapture, CameraState
from jarvis.memory.files import (
    MemoryFileId,
    MemoryFileRepository,
    build_memory_file_specs,
)
from jarvis.tools.builtin import BuiltinToolProvider
from jarvis.tools.host import McpHost, McpModuleStatus
from jarvis.tools.registry import ToolRegistry


async def _collect(bus: EventBus, event_type) -> list:
    events: list = []

    async def handler(event):
        events.append(event)

    bus.subscribe(event_type, handler)
    return events


def _provider(
    bus: EventBus,
    repository: MemoryFileRepository,
) -> tuple[ReasoningLevelState, BuiltinToolProvider]:
    state = ReasoningLevelState(bus)
    return state, BuiltinToolProvider(
        thinking_mode=state,
        memory_file_repository=repository,
    )


async def test_builtin_provider_registers_reserved_local_tools(tmp_path) -> None:
    bus = EventBus()
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    _, provider = _provider(bus, repository)
    registry = ToolRegistry()

    provider.register_tools(registry)

    tools = {tool.name: tool for tool in registry.all()}
    assert set(tools) == {"set_reasoning_level", "remember", "capture_camera_image"}
    assert all(tool.provider == BUILTIN_TOOL_PROVIDER_NAME for tool in tools.values())
    assert all(tool.provider_kind == "builtin" for tool in tools.values())
    assert all(tool.data_boundary is DataBoundary.LOCAL for tool in tools.values())


async def test_builtin_reasoning_tool_changes_state_through_dispatch(tmp_path) -> None:
    bus = EventBus()
    events = await _collect(bus, ReasoningLevelChanged)
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    state, provider = _provider(bus, repository)
    registry = ToolRegistry()
    provider.register_tools(registry)
    host = McpHost(
        bus,
        settings=McpSettings(),
        registry=registry,
        builtin_clients={BUILTIN_TOOL_PROVIDER_NAME: provider},
    )

    result = await host.dispatcher.dispatch("set_reasoning_level", {"level": "high"})

    assert result.ok is True
    assert state.level is ReasoningLevel.HIGH
    assert events == [ReasoningLevelChanged(ReasoningLevel.HIGH, "TOOL")]
    assert "next accepted turn" in result.content
    assert host.status is McpModuleStatus.OFF


async def test_builtin_reasoning_tool_rejects_invalid_level_without_state_change(
    tmp_path,
) -> None:
    bus = EventBus()
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    state, provider = _provider(bus, repository)

    result = await provider.call_tool("set_reasoning_level", {"level": "max"})

    assert result.is_error is True
    assert state.level is ReasoningLevel.OFF


async def test_builtin_reasoning_tool_redundant_set_succeeds_without_event(
    tmp_path,
) -> None:
    bus = EventBus()
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    state, provider = _provider(bus, repository)
    await state.set_level(ReasoningLevel.LOW, source="UI")
    events = await _collect(bus, ReasoningLevelChanged)

    result = await provider.call_tool("set_reasoning_level", {"level": "low"})

    assert result.is_error is False
    assert "already active" in result.content
    assert events == []


async def test_builtin_memory_tool_appends_to_empty_and_non_empty_file(
    tmp_path,
) -> None:
    bus = EventBus()
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    _, provider = _provider(bus, repository)

    first = await provider.call_tool(
        "remember",
        {"file": "memory", "mode": "append", "content": "Пользователь любит TDD."},
    )
    second = await provider.call_tool(
        "remember",
        {"file": "memory", "mode": "append", "content": "Писать кратко."},
    )

    assert first.is_error is False
    assert second.is_error is False
    assert repository.read(MemoryFileId.MEMORY).content == (
        "Пользователь любит TDD.\n\nПисать кратко."
    )
    assert not (tmp_path / "memory.md.bak").exists()


async def test_builtin_memory_tool_replaces_self_file(tmp_path) -> None:
    bus = EventBus()
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    repository.write(MemoryFileId.SELF, "old")
    _, provider = _provider(bus, repository)

    result = await provider.call_tool(
        "remember",
        {"file": "self", "mode": "replace", "content": "new persona"},
    )

    assert result.is_error is False
    assert repository.read(MemoryFileId.SELF).content == "new persona"
    assert (tmp_path / "self.md.bak").read_text(encoding="utf-8") == "old"
    assert "Previous version saved to self.md.bak" in result.content
    assert result.structured_content["backup"] == "self.md.bak"
    assert "next session start" in result.content


async def test_builtin_memory_tool_replace_missing_file_reports_empty_backup(
    tmp_path,
) -> None:
    bus = EventBus()
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    _, provider = _provider(bus, repository)

    result = await provider.call_tool(
        "remember",
        {"file": "memory", "mode": "replace", "content": "new fact"},
    )

    assert result.is_error is False
    assert (tmp_path / "memory.md.bak").read_text(encoding="utf-8") == ""
    assert "Previous version saved to memory.md.bak" in result.content
    assert result.structured_content["backup"] == "memory.md.bak"


async def test_builtin_memory_tool_rejects_over_cap_without_writing(tmp_path) -> None:
    bus = EventBus()
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path), memory_max_chars=10))
    )
    repository.write(MemoryFileId.MEMORY, "old")
    _, provider = _provider(bus, repository)

    result = await provider.call_tool(
        "remember",
        {"file": "memory", "mode": "append", "content": "too much text"},
    )

    assert result.is_error is True
    assert "current size is 3" in result.content
    assert repository.read(MemoryFileId.MEMORY).content == "old"


async def test_builtin_memory_tool_rejects_over_cap_replace_without_backup(
    tmp_path,
) -> None:
    bus = EventBus()
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path), memory_max_chars=3))
    )
    repository.write(MemoryFileId.MEMORY, "old")
    _, provider = _provider(bus, repository)

    result = await provider.call_tool(
        "remember",
        {"file": "memory", "mode": "replace", "content": "too much text"},
    )

    assert result.is_error is True
    assert "current size is 3" in result.content
    assert repository.read(MemoryFileId.MEMORY).content == "old"
    assert not (tmp_path / "memory.md.bak").exists()


async def test_builtin_memory_tool_rejects_empty_content(tmp_path) -> None:
    bus = EventBus()
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    _, provider = _provider(bus, repository)

    result = await provider.call_tool(
        "remember", {"file": "memory", "mode": "append", "content": "   "}
    )

    assert result.is_error is True
    assert repository.read(MemoryFileId.MEMORY).content == ""


async def test_builtin_memory_tool_uses_repository_writer_seam() -> None:
    calls: list[tuple[Path, str]] = []
    settings = MemorySettings(root="memory-root")
    specs = build_memory_file_specs(settings)
    repository = MemoryFileRepository(
        specs,
        reader=lambda path: "old persona"
        if path == specs[MemoryFileId.SELF].path
        else None,
        writer=lambda path, content: calls.append((path, content)),
    )
    _, provider = _provider(EventBus(), repository)

    await provider.call_tool(
        "remember", {"file": "self", "mode": "replace", "content": "persona"}
    )

    assert calls == [
        (Path("memory-root") / "self.md.bak", "old persona"),
        (Path("memory-root") / "self.md", "persona"),
    ]


def _camera_provider(
    repository: MemoryFileRepository,
    *,
    sources: tuple[CameraSource, ...],
    backend: object,
    enabled: bool = True,
    on_camera_capture=None,
    on_camera_failure=None,
) -> BuiltinToolProvider:
    return BuiltinToolProvider(
        thinking_mode=ReasoningLevelState(EventBus()),
        memory_file_repository=repository,
        camera_capture=CameraCapture(
            CameraSettings(sources=sources), CameraState(enabled), backend
        ),
        on_camera_capture=on_camera_capture,
        on_camera_failure=on_camera_failure,
    )


class _CameraBackend:
    def __init__(self) -> None:
        self.lan_calls: list[str] = []
        self.usb_calls: list[int] = []

    def probe_usb(self, device_index: int) -> None:
        self.usb_calls.append(device_index)

    def capture_usb(
        self, device_index: int, width: int, height: int, fourcc: str
    ) -> bytes:
        del width, height, fourcc
        self.usb_calls.append(device_index)
        return b"usb-frame"

    def probe_lan(self, url: str, timeout_seconds: float) -> None:
        del timeout_seconds
        self.lan_calls.append(url)

    def capture_lan(self, url: str, timeout_seconds: float) -> bytes:
        del timeout_seconds
        self.lan_calls.append(url)
        return b"lan-frame"


_DESK = UsbCameraSource(name="desk", device_index=1, description="Webcam on the desk.")
_WIDE = LanCameraSource(
    name="wide",
    host="192.168.1.108",
    stream_path="/cam/realmonitor?channel=2&subtype=0",
    user="admin",
    password="pa#ss",
    description="Fixed wide-angle lens.",
)


async def test_camera_tool_without_a_source_uses_the_default_one(tmp_path) -> None:
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    backend = _CameraBackend()
    provider = _camera_provider(repository, sources=(_DESK, _WIDE), backend=backend)

    result = await provider.call_tool("capture_camera_image", {})

    assert result.is_error is False
    assert result.structured_content == {"source": "desk", "data_boundary": "local"}
    assert result.data_boundary is DataBoundary.LOCAL
    assert backend.lan_calls == []


async def test_camera_tool_captures_the_named_source_and_reports_its_boundary(
    tmp_path,
) -> None:
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    backend = _CameraBackend()
    provider = _camera_provider(repository, sources=(_DESK, _WIDE), backend=backend)

    result = await provider.call_tool("capture_camera_image", {"source": "wide"})

    assert result.structured_content == {"source": "wide", "data_boundary": "lan"}
    assert result.data_boundary is DataBoundary.LAN
    assert "wide" in str(result.content)
    assert "USB" not in str(result.content)
    assert backend.usb_calls == []


async def test_camera_tool_answers_an_unknown_source_with_the_catalogue(
    tmp_path,
) -> None:
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    failures: list[str] = []

    async def on_failure() -> None:
        failures.append("failed")

    provider = _camera_provider(
        repository,
        sources=(_DESK, _WIDE),
        backend=_CameraBackend(),
        on_camera_failure=on_failure,
    )

    result = await provider.call_tool("capture_camera_image", {"source": "garage"})

    assert result.is_error is True
    assert "garage" in str(result.content)
    assert "Fixed wide-angle lens." in str(result.content)
    assert "Webcam on the desk." in str(result.content)
    # Nothing was captured, so the module must not be marked degraded.
    assert failures == []


async def test_camera_tool_refuses_every_source_while_the_privacy_switch_is_off(
    tmp_path,
) -> None:
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    backend = _CameraBackend()
    provider = _camera_provider(
        repository, sources=(_DESK, _WIDE), backend=backend, enabled=False
    )

    result = await provider.call_tool("capture_camera_image", {"source": "wide"})

    assert result.is_error is True
    assert backend.lan_calls == []
    assert backend.usb_calls == []


async def test_camera_tool_declaration_lists_every_source_for_the_model(
    tmp_path,
) -> None:
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    provider = _camera_provider(
        repository, sources=(_DESK, _WIDE), backend=_CameraBackend()
    )
    registry = ToolRegistry()

    provider.register_tools(registry)

    tool = {entry.name: entry for entry in registry.all()}["capture_camera_image"]
    assert "desk - Webcam on the desk." in tool.description
    assert "wide - Fixed wide-angle lens." in tool.description
    assert "Omitting 'source' uses desk." in tool.description
    assert tool.schema["properties"]["source"]["enum"] == ["desk", "wide"]


async def test_camera_tool_rejects_arguments_it_does_not_understand(tmp_path) -> None:
    repository = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path)))
    )
    backend = _CameraBackend()
    provider = _camera_provider(repository, sources=(_DESK,), backend=backend)

    result = await provider.call_tool("capture_camera_image", {"zoom": 2})

    assert result.is_error is True
    assert "zoom" in str(result.content)
    assert backend.usb_calls == []
