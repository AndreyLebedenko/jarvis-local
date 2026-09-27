"""Artifact schema for tasks/spike-single-pass-tts-block.md (mode 3b spike).

One CallRecord per model request the harness makes. The grader, the review
sheet generator, and the scorer read only these records, never Ollama.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Level(StrEnum):
    OFF = "off"
    MEDIUM = "medium"


class Stage(StrEnum):
    A_PASS1 = "a_pass1"
    A_PROD_PASS2 = "a_prod_pass2"
    A_EQ_PASS2 = "a_eq_pass2"
    B = "b"


LENGTH_DONE_REASON = "length"


@dataclass(frozen=True)
class StreamChunk:
    """One streamed Ollama chunk; `t` is seconds since its call started."""

    t: float
    content: str = ""
    thinking: str = ""


@dataclass(frozen=True, order=True)
class GenerationKey:
    level: Level
    prompt_id: str
    seed: int

    @property
    def slug(self) -> str:
        return f"{self.level}-{self.prompt_id}-s{self.seed}"


@dataclass(frozen=True)
class CallRecord:
    """`started_at` is time.perf_counter() at request start, so offsets
    between calls of one generation (pass 1 then pass 2) are comparable."""

    key: GenerationKey
    stage: Stage
    started_at: float
    chunks: tuple[StreamChunk, ...]
    done_reason: str | None
    eval_count: int | None
    prompt_eval_count: int | None
    system_prompt_sha256: str
    request: dict[str, Any] = field(default_factory=dict)

    @property
    def content(self) -> str:
        return "".join(chunk.content for chunk in self.chunks)

    @property
    def thinking(self) -> str:
        return "".join(chunk.thinking for chunk in self.chunks)

    @property
    def wall_seconds(self) -> float:
        return self.chunks[-1].t if self.chunks else 0.0

    @property
    def hit_length_cap(self) -> bool:
        return self.done_reason == LENGTH_DONE_REASON

    def to_json(self) -> dict[str, Any]:
        return {
            "level": self.key.level.value,
            "prompt_id": self.key.prompt_id,
            "seed": self.key.seed,
            "stage": self.stage.value,
            "started_at": self.started_at,
            "chunks": [[c.t, c.content, c.thinking] for c in self.chunks],
            "done_reason": self.done_reason,
            "eval_count": self.eval_count,
            "prompt_eval_count": self.prompt_eval_count,
            "system_prompt_sha256": self.system_prompt_sha256,
            "request": self.request,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CallRecord:
        return cls(
            key=GenerationKey(Level(data["level"]), data["prompt_id"], data["seed"]),
            stage=Stage(data["stage"]),
            started_at=data["started_at"],
            chunks=tuple(StreamChunk(t, c, th) for t, c, th in data["chunks"]),
            done_reason=data["done_reason"],
            eval_count=data["eval_count"],
            prompt_eval_count=data["prompt_eval_count"],
            system_prompt_sha256=data["system_prompt_sha256"],
            request=data.get("request", {}),
        )


class Arm(StrEnum):
    A_PROD = "a_prod"
    A_EQ = "a_eq"
    B = "b"


class TagOutcome(StrEnum):
    """In precedence order: the first class that applies is the outcome."""

    TRUNCATED = "truncated"
    MISSING = "missing"
    MULTIPLE = "multiple"
    IN_CODE_FENCE = "in_code_fence"
    UNCLOSED = "unclosed"
    TEXT_AFTER = "text_after"
    EMPTY = "empty"
    WELL_FORMED = "well_formed"


@dataclass(frozen=True)
class VoiceHygiene:
    markdown_markers: int = 0
    table_pipe_lines: int = 0
    code_fences: int = 0
    raw_urls: int = 0


@dataclass(frozen=True)
class GenerationMetrics:
    """One arm of one generation, as the scorer and the review sheet see it.

    `tag_outcome` is set for arm B only. `first_sentence_seconds` is measured
    from the start of the arm's first request; None when the arm produced no
    spoken sentence. `voice_text` is None when the arm has no usable voice
    (B: any tag outcome other than well-formed)."""

    key: GenerationKey
    arm: Arm
    canvas_text: str
    voice_text: str | None
    first_sentence_seconds: float | None
    total_wall_seconds: float
    eval_count_sum: int
    runaway: bool
    hygiene: VoiceHygiene | None
    tag_outcome: TagOutcome | None = None


def record_file_name(key: GenerationKey, stage: Stage) -> str:
    return f"{key.slug}-{stage}.json"


def write_record(directory: Path, record: CallRecord) -> Path:
    path = directory / record_file_name(record.key, record.stage)
    path.write_text(
        json.dumps(record.to_json(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return path


def load_records(directory: Path) -> list[CallRecord]:
    return [
        CallRecord.from_json(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.json"))
    ]
