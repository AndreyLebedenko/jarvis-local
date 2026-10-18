"""Orchestration of the personal-proxy spike runs, independent of Ollama.

A ModelCaller turns a PlannedRequest into a CallRecord; the live one lives in
manual_check_personal_proxy_spike.py and the tests use a fake. This module
plans the generations, builds each arm's requests, keeps the run resumable,
and refuses to continue a run whose frozen inputs changed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from jarvis.core.config import GenerationOptions
from jarvis.journal.transcription import build_transcription_messages
from manual.personal_proxy_corpus import SEEDS
from manual.personal_proxy_prompts import (
    COMBINED_SCHEMA,
    TEXT_SCHEMA,
    combined_system_messages,
    combined_user_messages,
    sanitize_text_messages,
)
from manual.personal_proxy_records import (
    Arm,
    CallRecord,
    CallStage,
    GenerationRecord,
    generation_exists,
    write_generation,
)

NUM_PREDICT = 2048
WARMUP_NUM_PREDICT = 32
CACHE_RESET_NUM_PREDICT = 1
CACHE_RESET_SYSTEM = "0"
CACHE_RESET_USER = "0"
WARMUP_INSTRUCTION = "Say one short sentence."

ARMS = (Arm.T_PLUS_S, Arm.C_USER, Arm.C_SYSTEM)

Message = dict[str, str]


@dataclass(frozen=True)
class PlannedRequest:
    """`audio` is the WAV bytes attached through the `images` field, or None
    for a text-only or no-media request."""

    stage: CallStage
    messages: tuple[Message, ...]
    audio: bytes | None
    options: GenerationOptions
    response_format: dict[str, Any] | None = None


class ModelCaller(Protocol):
    async def __call__(self, request: PlannedRequest) -> CallRecord: ...


@dataclass(frozen=True)
class GenerationJob:
    subject_id: str
    arm: Arm
    seed: int


def plan_jobs(
    subject_ids: list[str],
    seeds: tuple[int, ...] = SEEDS,
    arms: tuple[Arm, ...] = ARMS,
) -> list[GenerationJob]:
    """Seed by seed, subject by subject, rotating which arm goes first so a
    slow drift in the machine does not always fall on the same arm."""
    jobs: list[GenerationJob] = []
    for seed in seeds:
        for index, subject_id in enumerate(subject_ids):
            shift = index % len(arms)
            for arm in arms[shift:] + arms[:shift]:
                jobs.append(GenerationJob(subject_id, arm, seed))
    return jobs


class GenerationRunner:
    def __init__(
        self,
        caller: ModelCaller,
        base_options: GenerationOptions,
        *,
        transcribe_instruction: str,
        topics: str,
        use_format: bool,
    ) -> None:
        self._caller = caller
        self._base_options = base_options
        self._instruction = transcribe_instruction
        self._topics = topics
        self._use_format = use_format

    async def call(self, request: PlannedRequest) -> CallRecord:
        return await self._caller(request)

    def options_for(self, seed: int) -> GenerationOptions:
        return replace(self._base_options, seed=seed, num_predict=NUM_PREDICT)

    async def run(self, job: GenerationJob, audio: bytes | None) -> GenerationRecord:
        calls: list[CallRecord] = []
        try:
            if job.arm is Arm.T_PLUS_S:
                await self._run_two_step(job, audio, calls)
            else:
                calls.append(await self._caller(self._combined(job, audio)))
        except Exception as exc:
            return GenerationRecord(
                job.subject_id, job.arm, job.seed, tuple(calls), repr(exc)
            )
        return GenerationRecord(job.subject_id, job.arm, job.seed, tuple(calls))

    async def _run_two_step(
        self, job: GenerationJob, audio: bytes | None, calls: list[CallRecord]
    ) -> None:
        transcribe = await self._caller(
            PlannedRequest(
                CallStage.TRANSCRIBE,
                tuple(
                    {"role": m.role, "content": m.content}
                    for m in build_transcription_messages(self._instruction)
                ),
                audio,
                self.options_for(job.seed),
            )
        )
        calls.append(transcribe)
        calls.append(
            await self._caller(
                PlannedRequest(
                    CallStage.SANITIZE_TEXT,
                    tuple(
                        sanitize_text_messages(
                            transcribe.response_text.strip(), self._topics
                        )
                    ),
                    None,
                    self.options_for(job.seed),
                    TEXT_SCHEMA if self._use_format else None,
                )
            )
        )

    def _combined(self, job: GenerationJob, audio: bytes | None) -> PlannedRequest:
        builder = (
            combined_user_messages
            if job.arm is Arm.C_USER
            else combined_system_messages
        )
        return PlannedRequest(
            CallStage.COMBINED,
            tuple(builder(self._topics)),
            audio,
            self.options_for(job.seed),
            COMBINED_SCHEMA if self._use_format else None,
        )

    def warm_up_request(self, audio: bytes | None) -> PlannedRequest:
        return PlannedRequest(
            CallStage.TRANSCRIBE,
            ({"role": "user", "content": WARMUP_INSTRUCTION},),
            audio,
            replace(self._base_options, num_predict=WARMUP_NUM_PREDICT),
        )

    def cache_reset_request(self) -> PlannedRequest:
        return PlannedRequest(
            CallStage.COMBINED,
            (
                {"role": "system", "content": CACHE_RESET_SYSTEM},
                {"role": "user", "content": CACHE_RESET_USER},
            ),
            None,
            GenerationOptions(num_predict=CACHE_RESET_NUM_PREDICT),
        )


@dataclass(frozen=True)
class RunSummary:
    ran: int
    skipped: int
    errored: int


Progress = Callable[[GenerationRecord], None]


async def run_jobs(
    runner: GenerationRunner,
    jobs: list[GenerationJob],
    audio_for: Callable[[str], bytes | None],
    calls_dir: Path,
    *,
    warm_audio: bytes | None,
    progress: Progress = lambda record: None,
) -> RunSummary:
    """Warms the model up (unrecorded), then runs every job that has no
    finished record yet, resetting Ollama's prompt-prefix cache before each."""
    await runner.call(runner.warm_up_request(warm_audio))
    ran = skipped = errored = 0
    for job in jobs:
        if generation_exists(calls_dir, job.arm, job.subject_id, job.seed):
            skipped += 1
            continue
        await runner.call(runner.cache_reset_request())
        record = await runner.run(job, audio_for(job.subject_id))
        write_generation(calls_dir, record)
        ran += 1
        errored += record.error is not None
        progress(record)
    return RunSummary(ran, skipped, errored)


class RunMetaMismatchError(RuntimeError):
    def __init__(self, changed: list[str]) -> None:
        super().__init__(
            "the run's frozen inputs changed: "
            + ", ".join(changed)
            + ". Do not delete run_meta.json; report this instead."
        )
        self.changed = changed


def ensure_run_meta(path: Path, meta: dict[str, Any]) -> None:
    if not path.exists():
        path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return
    existing = json.loads(path.read_text(encoding="utf-8"))
    changed = sorted(
        key
        for key in set(existing) | set(meta)
        if existing.get(key) != json.loads(json.dumps(meta.get(key)))
    )
    if changed:
        raise RunMetaMismatchError(changed)


def choose_use_format(
    constrained_valid: int, constrained_total: int, plain_valid: int, plain_total: int
) -> bool:
    """Stage 0 rule: constrained decoding only if it is strictly more valid."""
    constrained = constrained_valid / constrained_total if constrained_total else 0.0
    plain = plain_valid / plain_total if plain_total else 0.0
    return constrained > plain
