from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from jarvis.core.config import MemorySettings


class MemoryFileId(Enum):
    SELF = "self"
    MEMORY = "memory"


@dataclass(frozen=True)
class MemoryFileSpec:
    file_id: MemoryFileId
    path: Path
    max_chars: int
    prompt_label: str


@dataclass(frozen=True)
class LoadedMemoryFile:
    spec: MemoryFileSpec
    content: str
    original_chars: int
    truncated: bool


MemoryFileReader = Callable[[Path], str | None]
MemoryFileWriter = Callable[[Path, str], None]


class MemoryFileLoader:
    def __init__(
        self,
        specs: Mapping[MemoryFileId, MemoryFileSpec],
        *,
        reader: MemoryFileReader | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._specs = dict(specs)
        self._reader = reader or _read_text_if_exists
        self._logger = logger or logging.getLogger(__name__)

    def load(self, file_id: MemoryFileId) -> LoadedMemoryFile:
        spec = self._specs[file_id]
        content = self._reader(spec.path)
        if content is None:
            content = ""
        original_chars = len(content)
        truncated = original_chars > spec.max_chars
        if truncated:
            self._logger.warning(
                "Memory file %s exceeds cap: %d chars > %d chars; "
                "truncating for injection only",
                spec.path,
                original_chars,
                spec.max_chars,
            )
            content = content[: spec.max_chars]
        return LoadedMemoryFile(
            spec=spec,
            content=content,
            original_chars=original_chars,
            truncated=truncated,
        )

    def compose_system_prompt(self, base_prompt: str) -> str:
        parts = [base_prompt]
        for file_id in (MemoryFileId.SELF, MemoryFileId.MEMORY):
            loaded = self.load(file_id)
            if loaded.content == "":
                continue
            parts.append(_prompt_block(loaded.spec.prompt_label, loaded.content))
        return "\n\n".join(parts)


@dataclass(frozen=True)
class MemoryFileRead:
    file_id: MemoryFileId
    content: str
    max_chars: int

    @property
    def chars(self) -> int:
        return len(self.content)


class MemoryFileOverCapError(ValueError):
    def __init__(self, chars: int, max_chars: int) -> None:
        super().__init__("memory file content exceeds the character cap")
        self.chars = chars
        self.max_chars = max_chars


class MemoryFileRepository:
    def __init__(
        self,
        specs: Mapping[MemoryFileId, MemoryFileSpec],
        *,
        reader: MemoryFileReader | None = None,
        writer: MemoryFileWriter | None = None,
    ) -> None:
        self._specs = dict(specs)
        self._reader = reader or _read_text_if_exists
        self._writer = writer or _atomic_write_text

    def read(self, file_id: MemoryFileId) -> MemoryFileRead:
        spec = self._specs[file_id]
        content = self._reader(spec.path) or ""
        return MemoryFileRead(
            file_id=file_id,
            content=content,
            max_chars=spec.max_chars,
        )

    def write(self, file_id: MemoryFileId, content: str) -> MemoryFileRead:
        spec = self._specs[file_id]
        chars = len(content)
        if chars > spec.max_chars:
            raise MemoryFileOverCapError(chars, spec.max_chars)
        self._writer(spec.path, content)
        return MemoryFileRead(
            file_id=file_id,
            content=content,
            max_chars=spec.max_chars,
        )


def build_memory_file_specs(
    settings: MemorySettings,
) -> dict[MemoryFileId, MemoryFileSpec]:
    root = Path(settings.root)
    return {
        MemoryFileId.SELF: MemoryFileSpec(
            file_id=MemoryFileId.SELF,
            path=root / settings.self_file,
            max_chars=settings.self_max_chars,
            prompt_label="self.md",
        ),
        MemoryFileId.MEMORY: MemoryFileSpec(
            file_id=MemoryFileId.MEMORY,
            path=root / settings.memory_file,
            max_chars=settings.memory_max_chars,
            prompt_label="memory.md",
        ),
    }


def _read_text_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        Path(temp_name).replace(path)
    finally:
        if temp_name:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink()


def _prompt_block(label: str, content: str) -> str:
    return f"[Jarvis curated {label}]\n{content}\n[/Jarvis curated {label}]"
