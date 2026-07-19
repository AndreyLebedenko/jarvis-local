from __future__ import annotations

import logging
from pathlib import Path

from jarvis.core.config import MemorySettings
from jarvis.memory.files import (
    MemoryFileId,
    MemoryFileLoader,
    MemoryFileOverCapError,
    MemoryFileRepository,
    build_memory_file_specs,
)


def test_memory_prompt_skips_missing_and_empty_files() -> None:
    settings = MemorySettings(root="unused")
    specs = build_memory_file_specs(settings)
    reader_values = {
        specs[MemoryFileId.SELF].path: None,
        specs[MemoryFileId.MEMORY].path: "",
    }
    loader = MemoryFileLoader(specs, reader=reader_values.get)

    assert loader.compose_system_prompt("base") == "base"


def test_memory_prompt_injects_self_before_memory_with_delimiters() -> None:
    settings = MemorySettings(root="unused")
    specs = build_memory_file_specs(settings)
    reader_values = {
        specs[MemoryFileId.SELF].path: "persona",
        specs[MemoryFileId.MEMORY].path: "durable facts",
    }
    loader = MemoryFileLoader(specs, reader=reader_values.get)

    assert loader.compose_system_prompt("base") == (
        "base\n\n"
        "[Jarvis curated self.md]\n"
        "persona\n"
        "[/Jarvis curated self.md]\n\n"
        "[Jarvis curated memory.md]\n"
        "durable facts\n"
        "[/Jarvis curated memory.md]"
    )


def test_memory_prompt_preserves_utf8_content() -> None:
    settings = MemorySettings(root="unused")
    specs = build_memory_file_specs(settings)
    reader_values = {
        specs[MemoryFileId.SELF].path: "Джарвис говорит коротко.",
        specs[MemoryFileId.MEMORY].path: "Пользователь любит локальность.",
    }
    loader = MemoryFileLoader(specs, reader=reader_values.get)

    prompt = loader.compose_system_prompt("base")

    assert "Джарвис говорит коротко." in prompt
    assert "Пользователь любит локальность." in prompt


def test_memory_loader_truncates_over_cap_for_injection_only(tmp_path, caplog) -> None:
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    self_path = memory_root / "self.md"
    self_path.write_text("abcdef", encoding="utf-8")
    settings = MemorySettings(root=str(memory_root), self_max_chars=3)
    loader = MemoryFileLoader(
        build_memory_file_specs(settings), logger=logging.getLogger("memory-test")
    )

    with caplog.at_level(logging.WARNING, logger="memory-test"):
        loaded = loader.load(MemoryFileId.SELF)

    assert loaded.content == "abc"
    assert loaded.original_chars == 6
    assert loaded.truncated
    assert self_path.read_text(encoding="utf-8") == "abcdef"
    assert "self.md exceeds cap: 6 chars > 3 chars" in caplog.text


def test_memory_repository_reads_missing_as_empty_and_round_trips_utf8(
    tmp_path,
) -> None:
    settings = MemorySettings(root=str(tmp_path), memory_max_chars=100)
    repository = MemoryFileRepository(build_memory_file_specs(settings))

    missing = repository.read(MemoryFileId.MEMORY)
    written = repository.write(MemoryFileId.MEMORY, "Память: локально.")
    reread = repository.read(MemoryFileId.MEMORY)

    assert missing.content == ""
    assert written.content == "Память: локально."
    assert written.chars == len("Память: локально.")
    assert reread == written


def test_memory_repository_rejects_over_cap_without_writing(tmp_path) -> None:
    settings = MemorySettings(root=str(tmp_path), memory_max_chars=3)
    repository = MemoryFileRepository(build_memory_file_specs(settings))
    repository.write(MemoryFileId.MEMORY, "old")

    try:
        repository.write(MemoryFileId.MEMORY, "new text")
    except MemoryFileOverCapError as error:
        assert error.chars == len("new text")
        assert error.max_chars == 3
    else:
        raise AssertionError("expected MemoryFileOverCapError")

    assert repository.read(MemoryFileId.MEMORY).content == "old"


def test_memory_repository_write_uses_injected_atomic_writer() -> None:
    settings = MemorySettings(root="memory-root")
    calls: list[tuple[Path, str]] = []
    repository = MemoryFileRepository(
        build_memory_file_specs(settings),
        writer=lambda path, content: calls.append((path, content)),
    )

    repository.write(MemoryFileId.SELF, "persona")

    assert calls == [(Path("memory-root") / "self.md", "persona")]
