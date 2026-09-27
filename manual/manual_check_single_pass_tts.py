#!/usr/bin/env python3
"""Human-run harness for tasks/spike-single-pass-tts-block.md (mode 3b).

Needs a live local Ollama; run it from the repository root so config.toml and
the memory files resolve. The handoff is
tasks/spike-single-pass-tts-block-handoff.md.

  python -m manual.manual_check_single_pass_tts run
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.app import (
    _compose_effective_system_prompt,
    _dialog_profile_name,
    _history_limits_from_settings,
    _profile_reasoning,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    SPOKEN_DERIVATIVE_PROFILE,
    GenerationOptions,
    GenerationSettings,
    HistorySettings,
    Settings,
    load_settings,
)
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.dialog.time_context import format_time_context
from jarvis.history.context_budget import ContextBudgetLimits
from jarvis.history.working_context import (
    WorkingContextRequest,
    assemble_working_context,
)
from jarvis.memory.files import MemoryFileLoader, build_memory_file_specs
from manual.single_pass_tts_corpus import B_CONTRACT, CORPUS, SEEDS, corpus_sha256
from manual.single_pass_tts_files import (
    CALLS_DIR_NAME,
    ReviewStepError,
    write_equalized_review,
    write_production_review,
    write_report,
)
from manual.single_pass_tts_records import (
    CallRecord,
    GenerationKey,
    Level,
    Stage,
    StreamChunk,
    record_file_name,
    write_record,
)

NUM_PREDICT = 8192
CACHE_RESET_NUM_PREDICT = 1
LEVELS = (Level.OFF, Level.MEDIUM)
FIXED_TURN_EPOCH = datetime(2026, 9, 27, 11, 0, tzinfo=UTC).timestamp()
DEFAULT_OUT = Path("manual_check_single_pass_tts_out")
META_FILE_NAME = "run_meta.json"
# Must share no leading text with any measured system prompt: its only job is
# to evict the previous request's prompt prefix from Ollama's cache.
CACHE_RESET_SYSTEM = "0"
CACHE_RESET_USER = "0"

Message = dict[str, Any]


@dataclasses.dataclass(frozen=True)
class PlannedRequest:
    messages: tuple[Message, ...]
    reasoning: ReasoningLevel
    options: GenerationOptions


class RunMetaMismatchError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class RequestFactory:
    generation: GenerationSettings
    history_limits: ContextBudgetLimits
    base_system_prompt: str
    time_context: str

    @classmethod
    def from_settings(
        cls,
        generation: GenerationSettings,
        history: HistorySettings,
        *,
        base_system_prompt: str,
        time_context: str,
    ) -> RequestFactory:
        return cls(
            generation=generation,
            history_limits=_history_limits_from_settings(history, generation),
            base_system_prompt=base_system_prompt,
            time_context=time_context,
        )

    def pass1_system_prompt(self, level: Level) -> str:
        return _compose_effective_system_prompt(
            self.base_system_prompt, _reasoning(level), self.generation
        )

    def b_system_prompt(self, level: Level) -> str:
        return f"{self.pass1_system_prompt(level)}\n\n{B_CONTRACT}"

    def pass1(self, key: GenerationKey, prompt_text: str) -> PlannedRequest:
        return self._dialog_turn(key, self.pass1_system_prompt(key.level), prompt_text)

    def b(self, key: GenerationKey, prompt_text: str) -> PlannedRequest:
        return self._dialog_turn(key, self.b_system_prompt(key.level), prompt_text)

    def pass2(self, key: GenerationKey, stage: Stage, canvas: str) -> PlannedRequest:
        profile = self.generation.profile(SPOKEN_DERIVATIVE_PROFILE)
        if stage is Stage.A_PROD_PASS2:
            reasoning = _profile_reasoning(profile)
        elif stage is Stage.A_EQ_PASS2:
            reasoning = _reasoning(key.level)
        else:
            raise ValueError(f"{stage} is not a pass-2 stage")
        return PlannedRequest(
            messages=(
                {"role": "system", "content": profile.prompt or ""},
                {"role": "user", "content": canvas},
            ),
            reasoning=reasoning,
            options=self._options(SPOKEN_DERIVATIVE_PROFILE, key.seed),
        )

    def cache_reset(self) -> PlannedRequest:
        return PlannedRequest(
            messages=(
                {"role": "system", "content": CACHE_RESET_SYSTEM},
                {"role": "user", "content": CACHE_RESET_USER},
            ),
            reasoning=ReasoningLevel.OFF,
            options=GenerationOptions(num_predict=CACHE_RESET_NUM_PREDICT),
        )

    def _dialog_turn(
        self, key: GenerationKey, system_prompt: str, prompt_text: str
    ) -> PlannedRequest:
        context = assemble_working_context(
            WorkingContextRequest(
                system_prompt=system_prompt,
                recent_history=(),
                retrieved_passages=(),
                time_context=self.time_context,
                current_request_text=prompt_text,
                limits=self.history_limits,
            )
        )
        return PlannedRequest(
            messages=tuple(context.messages),
            reasoning=_reasoning(key.level),
            options=self._options(
                _dialog_profile_name(_reasoning(key.level)), key.seed
            ),
        )

    def _options(self, profile_name: str, seed: int) -> GenerationOptions:
        return dataclasses.replace(
            self.generation.options_for(profile_name),
            seed=seed,
            num_predict=NUM_PREDICT,
        )


def _reasoning(level: Level) -> ReasoningLevel:
    return ReasoningLevel(level.value)


def generation_stages(level: Level) -> tuple[Stage, ...]:
    pass2_stages = (
        (Stage.A_PROD_PASS2, Stage.A_EQ_PASS2)
        if level is Level.MEDIUM
        else (Stage.A_PROD_PASS2,)
    )
    return (Stage.A_PASS1, *pass2_stages, Stage.B)


def arm_order(prompt_id: str, seed: int, seeds: Sequence[int]) -> tuple[str, str]:
    prompt_index = [prompt.prompt_id for prompt in CORPUS].index(prompt_id)
    a_first = (prompt_index + seeds.index(seed)) % 2 == 0
    return ("a", "b") if a_first else ("b", "a")


def needs_pass2(pass1: CallRecord) -> bool:
    return not (pass1.hit_length_cap and not pass1.content.strip())


def is_generation_complete(directory: Path, key: GenerationKey) -> bool:
    pass1_path = directory / record_file_name(key, Stage.A_PASS1)
    if not pass1_path.exists():
        return False
    required = set(generation_stages(key.level))
    if not needs_pass2(CallRecord.from_json(_read_json(pass1_path))):
        required -= {Stage.A_PROD_PASS2, Stage.A_EQ_PASS2}
    return all((directory / record_file_name(key, s)).exists() for s in required)


def discard_partial_generation(directory: Path, key: GenerationKey) -> None:
    for stage in Stage:
        (directory / record_file_name(key, stage)).unlink(missing_ok=True)


def check_or_write_meta(directory: Path, meta: dict[str, Any]) -> None:
    path = directory / META_FILE_NAME
    if not path.exists():
        path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return
    recorded = _read_json(path)
    changed = sorted(
        name
        for name in meta.keys() | recorded.keys()
        if meta.get(name) != recorded.get(name)
    )
    if changed:
        raise RunMetaMismatchError(
            f"{path} was written by a different setup; changed: {', '.join(changed)}"
        )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_meta(settings: Settings, factory: RequestFactory) -> dict[str, Any]:
    profiles = {
        name: dataclasses.asdict(settings.generation.options_for(name))
        for name in (*(_dialog_profile_name(_reasoning(lv)) for lv in LEVELS),)
    } | {
        SPOKEN_DERIVATIVE_PROFILE: dataclasses.asdict(
            settings.generation.options_for(SPOKEN_DERIVATIVE_PROFILE)
        )
    }
    return {
        "model": settings.backend.model,
        "endpoint": settings.backend.endpoint,
        "num_ctx": settings.backend.num_ctx,
        "flash_attention": settings.backend.flash_attention,
        "kv_cache_type": settings.backend.kv_cache_type,
        "profile_options": profiles,
        "spoken_derivative_prompt_sha256": _sha256(
            settings.generation.profile(SPOKEN_DERIVATIVE_PROFILE).prompt or ""
        ),
        "pass1_system_prompt_sha256": {
            level.value: _sha256(factory.pass1_system_prompt(level)) for level in LEVELS
        },
        "corpus_sha256": corpus_sha256(),
        "time_context": factory.time_context,
        "num_predict": NUM_PREDICT,
        "seeds": list(SEEDS),
    }


class LiveRunner:
    def __init__(self, backend: OllamaBackend, factory: RequestFactory) -> None:
        self._backend = backend
        self._factory = factory

    async def run_generation(
        self, key: GenerationKey, prompt_text: str
    ) -> list[CallRecord]:
        records: list[CallRecord] = []
        for arm in arm_order(key.prompt_id, key.seed, SEEDS):
            await self._call(self._factory.cache_reset())
            if arm == "a":
                records.extend(await self._run_a(key, prompt_text))
            else:
                b = self._factory.b(key, prompt_text)
                records.append(await self._measured(key, Stage.B, b))
        return records

    async def _run_a(self, key: GenerationKey, prompt_text: str) -> list[CallRecord]:
        pass1 = await self._measured(
            key, Stage.A_PASS1, self._factory.pass1(key, prompt_text)
        )
        records = [pass1]
        if not needs_pass2(pass1):
            return records
        for stage in generation_stages(key.level):
            if stage in (Stage.A_PROD_PASS2, Stage.A_EQ_PASS2):
                request = self._factory.pass2(key, stage, pass1.content)
                records.append(await self._measured(key, stage, request))
        return records

    async def _measured(
        self, key: GenerationKey, stage: Stage, request: PlannedRequest
    ) -> CallRecord:
        started_at, chunks, done = await self._call(request)
        record = CallRecord(
            key=key,
            stage=stage,
            started_at=started_at,
            chunks=tuple(chunks),
            done_reason=done.get("done_reason"),
            eval_count=done.get("eval_count"),
            prompt_eval_count=done.get("prompt_eval_count"),
            system_prompt_sha256=_sha256(request.messages[0]["content"]),
            request=self._payload(request),
        )
        print(
            f"  {key.slug:<34} {stage:<13} {record.wall_seconds:7.1f}s "
            f"eval={record.eval_count} prompt_eval={record.prompt_eval_count} "
            f"done={record.done_reason}",
            flush=True,
        )
        return record

    async def _call(
        self, request: PlannedRequest
    ) -> tuple[float, list[StreamChunk], dict[str, Any]]:
        chunks: list[StreamChunk] = []
        done: dict[str, Any] = {}
        started_at = time.perf_counter()
        async for chunk in self._backend.iter_chat(
            list(request.messages), None, request.reasoning, options=request.options
        ):
            message = chunk.get("message") or {}
            chunks.append(
                StreamChunk(
                    t=time.perf_counter() - started_at,
                    content=message.get("content", ""),
                    thinking=message.get("thinking", ""),
                )
            )
            if chunk.get("done"):
                done = chunk
        return started_at, chunks, done

    def _payload(self, request: PlannedRequest) -> dict[str, Any]:
        return self._backend.build_payload(
            list(request.messages), None, request.reasoning, options=request.options
        )


def _load_factory(config_path: Path) -> tuple[Settings, RequestFactory]:
    settings = load_settings(config_path)
    loader = MemoryFileLoader(build_memory_file_specs(settings.memory))
    factory = RequestFactory.from_settings(
        settings.generation,
        settings.history,
        base_system_prompt=loader.compose_system_prompt(
            settings.prompts.system, include_memory=True
        ),
        time_context=format_time_context(FIXED_TURN_EPOCH),
    )
    return settings, factory


def _selected_keys(levels: Sequence[Level], prompt_ids: Sequence[str] | None):
    unknown = set(prompt_ids or ()) - {prompt.prompt_id for prompt in CORPUS}
    if unknown:
        raise SystemExit(f"Unknown prompt ids: {', '.join(sorted(unknown))}")
    for level in levels:
        for prompt in CORPUS:
            if prompt_ids and prompt.prompt_id not in prompt_ids:
                continue
            for seed in SEEDS:
                yield GenerationKey(level, prompt.prompt_id, seed), prompt.text


async def run(args: argparse.Namespace) -> int:
    settings, factory = _load_factory(args.config)
    calls_dir = args.out / CALLS_DIR_NAME
    calls_dir.mkdir(parents=True, exist_ok=True)
    check_or_write_meta(args.out, build_meta(settings, factory))
    runner = LiveRunner(OllamaBackend(EventBus(), settings.backend), factory)
    keys = list(_selected_keys(args.levels, args.prompts))
    started = time.perf_counter()
    for index, (key, prompt_text) in enumerate(keys, start=1):
        if is_generation_complete(calls_dir, key):
            continue
        discard_partial_generation(calls_dir, key)
        print(f"[{index}/{len(keys)}] {key.slug}", flush=True)
        for record in await runner.run_generation(key, prompt_text):
            write_record(calls_dir, record)
    elapsed = time.perf_counter() - started
    print(f"Done in {elapsed / 60:.1f} min. Records: {calls_dir}")
    return 0


_FILE_STEPS = {
    "review": write_production_review,
    "review-equalized": write_equalized_review,
    "score": lambda out_dir: [write_report(out_dir)],
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="generate every arm (live Ollama)")
    run_parser.add_argument(
        "--levels", nargs="+", type=Level, default=list(LEVELS), choices=LEVELS
    )
    run_parser.add_argument("--prompts", nargs="+", default=None)
    commands.add_parser("review", help="production blind-review sheet and key")
    commands.add_parser(
        "review-equalized", help="equalized sheet, after production answers"
    )
    commands.add_parser("score", help="unblind, apply the decision rule, report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        return asyncio.run(run(args))
    try:
        written = _FILE_STEPS[args.command](args.out)
    except ReviewStepError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for path in written:
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
