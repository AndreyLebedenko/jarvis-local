"""Artifact schema of the personal-proxy spike: one JSON file per generation.

A generation is one arm answering one subject (a corpus utterance or a
control) at one seed; it holds the model calls that arm needed (two for the
two-step arm, one for a combined arm). The scorer reads only these files and
never touches Ollama.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

COLD_LOAD_SECONDS = 1.0


class Arm(StrEnum):
    T_PLUS_S = "t_plus_s"
    C_USER = "c_user"
    C_SYSTEM = "c_system"


class CallStage(StrEnum):
    TRANSCRIBE = "transcribe"
    SANITIZE_TEXT = "sanitize_text"
    COMBINED = "combined"


@dataclass(frozen=True)
class CallRecord:
    """`request` is the exact payload sent, with every base64 image replaced
    by a marker carrying the WAV's SHA-256, so the file stays small and the
    audio stays identifiable."""

    stage: CallStage
    request: dict[str, Any]
    response_text: str
    done_reason: str | None
    eval_count: int
    prompt_eval_count: int
    load_seconds: float
    total_seconds: float


@dataclass(frozen=True)
class GenerationRecord:
    subject_id: str
    arm: Arm
    seed: int
    calls: tuple[CallRecord, ...]
    error: str | None = None

    @property
    def slug(self) -> str:
        return generation_slug(self.arm, self.subject_id, self.seed)

    @property
    def total_seconds(self) -> float:
        return sum(call.total_seconds for call in self.calls)

    @property
    def is_cold(self) -> bool:
        return any(call.load_seconds > COLD_LOAD_SECONDS for call in self.calls)

    def call_for(self, stage: CallStage) -> CallRecord | None:
        return next((call for call in self.calls if call.stage is stage), None)


def generation_slug(arm: Arm, subject_id: str, seed: int) -> str:
    return f"{arm.value}-{subject_id}-s{seed}"


def write_generation(calls_dir: Path, record: GenerationRecord) -> Path:
    """Written once, whole, so a crash never leaves a half generation."""
    calls_dir.mkdir(parents=True, exist_ok=True)
    path = calls_dir / f"{record.slug}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)
    return path


def generation_exists(calls_dir: Path, arm: Arm, subject_id: str, seed: int) -> bool:
    return (calls_dir / f"{generation_slug(arm, subject_id, seed)}.json").exists()


def read_generation(path: Path) -> GenerationRecord:
    document = json.loads(path.read_text(encoding="utf-8"))
    return GenerationRecord(
        subject_id=document["subject_id"],
        arm=Arm(document["arm"]),
        seed=document["seed"],
        calls=tuple(
            CallRecord(
                stage=CallStage(call["stage"]),
                request=call["request"],
                response_text=call["response_text"],
                done_reason=call["done_reason"],
                eval_count=call["eval_count"],
                prompt_eval_count=call["prompt_eval_count"],
                load_seconds=call["load_seconds"],
                total_seconds=call["total_seconds"],
            )
            for call in document["calls"]
        ),
        error=document.get("error"),
    )


def load_generations(calls_dir: Path) -> list[GenerationRecord]:
    if not calls_dir.exists():
        return []
    return [read_generation(path) for path in sorted(calls_dir.glob("*.json"))]
