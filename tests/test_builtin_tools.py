from __future__ import annotations

from pathlib import Path

from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BUILTIN_TOOL_PROVIDER_NAME,
    DataBoundary,
    McpSettings,
    MemorySettings,
)
from jarvis.dialog.thinking_mode import (
    ReasoningLevel,
    ReasoningLevelChanged,
    ReasoningLevelState,
)
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
    assert set(tools) == {"set_reasoning_level", "remember"}
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
