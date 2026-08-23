from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.core.bus import EventBus
from jarvis.core.config import (
    BUILTIN_TOOL_PROVIDER_NAME,
    DataBoundary,
    FilesSettings,
    McpSettings,
    MemorySettings,
)
from jarvis.dialog.thinking_mode import ReasoningLevelState
from jarvis.files import (
    SessionFileRepository,
    SessionFileScope,
    resolve_session_file_scope,
)
from jarvis.journal import JournalEvent, JournalStore
from jarvis.memory.files import MemoryFileRepository, build_memory_file_specs
from jarvis.tools.builtin import BuiltinToolProvider
from jarvis.tools.host import McpHost
from jarvis.tools.registry import ToolRegistry

_SESSION = "20260716-153000-ab12"
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f0f0000000049454e44ae42"
    "6082"
)
_SESSION_FILE_TOOLS = {
    "write_session_file",
    "read_session_text",
    "view_session_image",
    "stat_session_file",
    "list_session_files",
}


def _store_with_session(tmp_path: Path) -> JournalStore:
    store = JournalStore(tmp_path)
    store.append(
        JournalEvent(
            session_id=_SESSION,
            timestamp="2026-07-16T15:30:00+01:00",
            source="voice",
            role="user",
            text="hi",
            media=[],
            transcript=None,
        )
    )
    return store


def _provider(
    tmp_path: Path,
    *,
    store: JournalStore | None = None,
    config: FilesSettings | None = None,
    scope: SessionFileScope | None = None,
) -> BuiltinToolProvider:
    bus = EventBus()
    store = store or _store_with_session(tmp_path)
    memory = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path / "memory")))
    )
    repository = SessionFileRepository(
        store.root,
        config=config or FilesSettings(),
        session_is_visible=lambda sid: bool(store.read_session(sid).records),
    )

    def scope_provider() -> SessionFileScope:
        if scope is not None:
            return scope
        return resolve_session_file_scope(store, _SESSION)

    return BuiltinToolProvider(
        thinking_mode=ReasoningLevelState(bus),
        memory_file_repository=memory,
        session_file_repository=repository,
        session_file_scope=scope_provider,
    )


# ----------------------------------------------------------------- registration


def test_provider_registers_all_five_session_file_tools(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    registry = ToolRegistry()
    provider.register_tools(registry)

    tools = {tool.name: tool for tool in registry.all()}
    assert set(tools) >= _SESSION_FILE_TOOLS
    for name in _SESSION_FILE_TOOLS:
        tool = tools[name]
        assert tool.provider == BUILTIN_TOOL_PROVIDER_NAME
        assert tool.provider_kind == "builtin"
        assert tool.data_boundary is DataBoundary.LOCAL
        assert tool.schema["additionalProperties"] is False
        assert "session_id" not in tool.schema.get("properties", {})


def test_session_file_tools_absent_without_a_repository(tmp_path: Path) -> None:
    bus = EventBus()
    memory = MemoryFileRepository(
        build_memory_file_specs(MemorySettings(root=str(tmp_path / "memory")))
    )
    provider = BuiltinToolProvider(
        thinking_mode=ReasoningLevelState(bus), memory_file_repository=memory
    )
    registry = ToolRegistry()
    provider.register_tools(registry)

    assert _SESSION_FILE_TOOLS.isdisjoint({tool.name for tool in registry.all()})


# --------------------------------------------------------------- dispatch success


async def test_write_reports_generated_storage_name(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    result = await provider.call_tool(
        "write_session_file", {"name": "note.md", "content": "hello"}
    )

    assert result.is_error is False
    storage_name = result.structured_content["storage_name"]
    assert storage_name != "note.md"
    assert result.structured_content["bytes"] == 5
    assert "changed" in result.content
    assert (tmp_path / _SESSION / storage_name).exists()


async def test_read_returns_plain_text(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    written = await provider.call_tool(
        "write_session_file", {"name": "note.txt", "content": "body text"}
    )
    storage_name = written.structured_content["storage_name"]

    result = await provider.call_tool("read_session_text", {"name": storage_name})

    assert result.is_error is False
    assert result.content == "body text"
    assert result.structured_content is None


async def test_view_returns_image_through_images_b64(tmp_path: Path) -> None:
    store = _store_with_session(tmp_path)
    (tmp_path / _SESSION / "pic-abcd.png").write_bytes(_PNG_BYTES)
    provider = _provider(tmp_path, store=store)

    result = await provider.call_tool("view_session_image", {"name": "pic-abcd.png"})

    assert result.is_error is False
    assert len(result.images_b64) == 1
    assert result.data_boundary is DataBoundary.LOCAL


async def test_stat_reports_scope_metadata(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    written = await provider.call_tool(
        "write_session_file", {"name": "note.md", "content": "hello"}
    )
    storage_name = written.structured_content["storage_name"]

    result = await provider.call_tool("stat_session_file", {"name": storage_name})

    payload = result.structured_content
    assert result.is_error is False
    assert payload["storage_name"] == storage_name
    assert payload["bytes"] == 5
    assert payload["ext"] == "md"
    assert payload["session_id"] == _SESSION
    assert payload["scope"] == "current"
    assert "mtime_utc" in payload


async def test_list_reports_written_files(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    await provider.call_tool("write_session_file", {"name": "a.md", "content": "1"})
    await provider.call_tool("write_session_file", {"name": "b.md", "content": "2"})

    result = await provider.call_tool("list_session_files", {})

    files = result.structured_content["files"]
    names = {entry["storage_name"] for entry in files}
    assert len(names) == 2
    assert all(entry["scope"] == "current" for entry in files)


# ------------------------------------------------------------------ error mapping


async def test_read_missing_file_is_a_distinct_error(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    result = await provider.call_tool("read_session_text", {"name": "ghost-0.md"})
    assert result.is_error is True
    assert "not found" in result.content


async def test_read_binary_file_reports_not_text(tmp_path: Path) -> None:
    store = _store_with_session(tmp_path)
    (tmp_path / _SESSION / "pic-abcd.png").write_bytes(_PNG_BYTES)
    provider = _provider(tmp_path, store=store)
    result = await provider.call_tool("read_session_text", {"name": "pic-abcd.png"})
    assert result.is_error is True
    assert "not UTF-8" in result.content


async def test_view_non_image_reports_unsupported(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    written = await provider.call_tool(
        "write_session_file", {"name": "note.txt", "content": "x"}
    )
    result = await provider.call_tool(
        "view_session_image", {"name": written.structured_content["storage_name"]}
    )
    assert result.is_error is True
    assert "PNG or JPEG" in result.content


async def test_write_denylisted_extension_is_refused(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    result = await provider.call_tool(
        "write_session_file", {"name": "payload.exe", "content": "x"}
    )
    assert result.is_error is True
    assert "deny-listed" in result.content


async def test_write_invalid_name_is_refused(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    result = await provider.call_tool(
        "write_session_file", {"name": "../escape.txt", "content": "x"}
    )
    assert result.is_error is True


async def test_write_oversize_text_is_refused(tmp_path: Path) -> None:
    provider = _provider(tmp_path, config=FilesSettings(max_text_write_chars=2))
    result = await provider.call_tool(
        "write_session_file", {"name": "big.txt", "content": "too long"}
    )
    assert result.is_error is True
    assert "max_text_write_chars" in result.content


async def test_all_tools_report_no_active_session(tmp_path: Path) -> None:
    provider = _provider(tmp_path, scope=SessionFileScope(None, ()))
    for name, arguments in (
        ("write_session_file", {"name": "n.md", "content": "x"}),
        ("read_session_text", {"name": "n-0.md"}),
        ("view_session_image", {"name": "n-0.png"}),
        ("stat_session_file", {"name": "n-0.md"}),
        ("list_session_files", {}),
    ):
        result = await provider.call_tool(name, arguments)
        assert result.is_error is True, name
        assert "active session" in result.content.lower(), name


# -------------------------------------------------------- no model-supplied scope


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("write_session_file", {"name": "n.md", "content": "x", "session_id": "s"}),
        ("read_session_text", {"name": "n-0.md", "session_id": "s"}),
        ("stat_session_file", {"name": "n-0.md", "session_id": "s"}),
        ("list_session_files", {"session_id": "s"}),
    ],
)
async def test_tools_reject_a_model_supplied_session_id(
    tmp_path: Path, name: str, arguments: dict
) -> None:
    provider = _provider(tmp_path)
    result = await provider.call_tool(name, arguments)
    assert result.is_error is True
    assert "session_id" in result.content


# ------------------------------------------------------- dispatch/audit/enablement


async def test_dispatch_flows_through_host_and_respects_disable(tmp_path: Path) -> None:
    bus = EventBus()
    provider = _provider(tmp_path)
    registry = ToolRegistry()
    provider.register_tools(registry)
    host = McpHost(
        bus,
        settings=McpSettings(),
        registry=registry,
        builtin_clients={BUILTIN_TOOL_PROVIDER_NAME: provider},
    )

    ok = await host.dispatcher.dispatch(
        "write_session_file", {"name": "note.md", "content": "hello"}
    )
    assert ok.ok is True

    registry.set_tool_enabled("write_session_file", False)
    blocked = await host.dispatcher.dispatch(
        "write_session_file", {"name": "note.md", "content": "hello"}
    )
    assert blocked.ok is False
    assert "disabled" in (blocked.error or "")
