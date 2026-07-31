#!/usr/bin/env python3
"""Human-run prompt-token estimator measurement for task v1.8.0-3.

The script sends fixed text-only payloads to the configured local Ollama
endpoint and compares pre-dispatch estimates with terminal
``prompt_eval_count`` values. It covers production message ordering, Russian,
English/code-like text, bounded history, and native/prompt tool follow-ups.

Prompt content is never written to the result file. Each case records only a
hash, sizes, estimates, and Ollama counts.

Usage:
  python -m manual.manual_check_context_token_budget
  python -m manual.manual_check_context_token_budget \
      --sentencepiece-model-path C:\\path\\to\\tokenizer.model
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from jarvis.app import _compose_effective_system_prompt
from jarvis.core.bus import EventBus
from jarvis.core.config import load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.dialog.tool_presentation import (
    NativeToolPresentation,
    PromptToolPresentation,
)
from jarvis.memory.files import MemoryFileLoader, build_memory_file_specs
from jarvis.tools.interception import ToolDispatchResult
from jarvis.tools.registry import RegisteredTool

BASE_TOKEN_OVERHEAD = 32
MESSAGE_TOKEN_OVERHEAD = 12
TOOL_TOKEN_OVERHEAD = 24
BYTES_PER_ESTIMATED_TOKEN = 2
RUNS_PER_CASE = 2
DEFAULT_OUTPUT_PATH = Path("manual_check_context_token_budget_out/results.json")

MaterialCounter = Callable[[str], int]


def sentencepiece_model_path(value: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(
            "expected a filesystem path to an existing SentencePiece model "
            "file, not an Ollama model name"
        )
    return path


@dataclass(frozen=True)
class MeasurementCase:
    key: str
    phase: str
    payload: dict[str, object]


@dataclass(frozen=True)
class LiveMeasurement:
    case_key: str
    run_index: int
    prompt_eval_count: int
    estimates: dict[str, int]


@dataclass(frozen=True)
class CandidateSummary:
    candidate: str
    maximum_underestimation: int
    minimum_headroom: int
    maximum_headroom: int


_HISTORY_TOOL = RegisteredTool(
    name="search_history",
    description="Search local conversation history for relevant passages.",
    schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "required": ["query", "limit"],
        "additionalProperties": False,
    },
    provider="history",
    provider_kind="builtin",
)

_TOOL_ARGUMENTS = {"query": "любимый редактор пользователя", "limit": 3}
_TOOL_RESULT = ToolDispatchResult(
    ok=True,
    correlation_id="context-budget-spike",
    content=(
        "Found 2 local passages. 2026-06-10: user prefers keyboard-driven "
        "editing. 2026-07-03: user asked to keep code examples concise and "
        "to preserve exact identifiers such as parse_user_id and HTTP/2."
    ),
    structured_content={"matches": 2},
)


def canonical_prompt_material(payload: dict[str, object]) -> str:
    """Stable text proxy containing only model-facing messages and tools."""
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("payload messages must be a list")
    material: dict[str, object] = {"messages": messages}
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        material["tools"] = tools
    return json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def estimate_conservative_tokens(payload: dict[str, object]) -> int:
    material = canonical_prompt_material(payload)
    messages = payload["messages"]
    tools = payload.get("tools")
    message_count = len(messages) if isinstance(messages, list) else 0
    tool_count = len(tools) if isinstance(tools, list) else 0
    byte_estimate = math.ceil(len(material.encode("utf-8")) / BYTES_PER_ESTIMATED_TOKEN)
    return (
        byte_estimate
        + BASE_TOKEN_OVERHEAD
        + message_count * MESSAGE_TOKEN_OVERHEAD
        + tool_count * TOOL_TOKEN_OVERHEAD
    )


def estimate_candidates(
    payload: dict[str, object],
    *,
    compatible_counter: MaterialCounter | None = None,
) -> dict[str, int]:
    estimates = {"conservative_utf8": estimate_conservative_tokens(payload)}
    if compatible_counter is not None:
        estimates["compatible_sentencepiece_material"] = compatible_counter(
            canonical_prompt_material(payload)
        )
    return estimates


def parse_prompt_eval_count(chunks: Sequence[dict[str, object]]) -> int:
    for chunk in reversed(chunks):
        if chunk.get("done") is not True:
            continue
        count = chunk.get("prompt_eval_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            return count
        raise ValueError("terminal Ollama chunk has no usable prompt_eval_count")
    raise ValueError("Ollama stream ended without a terminal done:true chunk")


def summarize_candidate(
    measurements: Sequence[LiveMeasurement], candidate: str
) -> CandidateSummary:
    headrooms = [
        measurement.estimates[candidate] - measurement.prompt_eval_count
        for measurement in measurements
        if candidate in measurement.estimates
    ]
    if not headrooms:
        raise ValueError(f"candidate {candidate!r} has no measurements")
    return CandidateSummary(
        candidate=candidate,
        maximum_underestimation=max(0, -min(headrooms)),
        minimum_headroom=min(headrooms),
        maximum_headroom=max(headrooms),
    )


def build_measurement_cases(
    backend: OllamaBackend, effective_system_prompt: str
) -> tuple[MeasurementCase, ...]:
    time_message = {
        "role": "system",
        "content": "пятница, 2026-07-31T14:30+01:00",
    }
    russian_short = [
        {"role": "system", "content": effective_system_prompt},
        time_message,
        {
            "role": "user",
            "content": "Кратко объясни, почему небо кажется голубым.",
        },
    ]
    english_code = [
        {"role": "system", "content": effective_system_prompt},
        time_message,
        {
            "role": "user",
            "content": (
                "Review `async def parse_user_id(value: str) -> UUID` and "
                "explain the HTTP/2 failure mode in two concise sentences."
            ),
        },
    ]
    memory_fixture_prompt = (
        f"{effective_system_prompt}\n\n"
        "[Jarvis curated self.md]\n"
        "Отвечай точно и сохраняй идентификаторы без перевода.\n"
        "[/Jarvis curated self.md]\n\n"
        "[Jarvis curated memory.md]\n"
        "Пользователь предпочитает короткие ответы и Python examples.\n"
        "[/Jarvis curated memory.md]"
    )
    system_memory = [
        {"role": "system", "content": memory_fixture_prompt},
        time_message,
        {"role": "user", "content": "Что ты помнишь о формате моих ответов?"},
    ]
    long_fragment = (
        "Смешанный контекст: обработчик request/response сохраняет UUID, "
        "timestamp и status_code; ответ должен оставаться кратким. "
    )
    mixed_long = [
        {"role": "system", "content": effective_system_prompt},
        {"role": "user", "content": long_fragment * 12},
        {
            "role": "assistant",
            "content": (
                "Принято. I will preserve exact identifiers and explain only "
                "the relevant failure mode. "
            )
            * 8,
        },
        {"role": "user", "content": long_fragment * 18},
        {
            "role": "assistant",
            "content": "Краткий итог с parse_user_id, HTTP/2 и JSONDecoder. " * 8,
        },
        time_message,
        {"role": "user", "content": long_fragment * 24},
    ]

    native = NativeToolPresentation()
    native_prepared = native.prepare((_HISTORY_TOOL,))
    native_initial = [*russian_short[:-1], russian_short[-1]]
    native_followup = [
        *native_initial,
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": _HISTORY_TOOL.name,
                        "arguments": _TOOL_ARGUMENTS,
                    }
                }
            ],
        },
        native.result_message(_TOOL_RESULT),
    ]

    prompt = PromptToolPresentation()
    prompt_prepared = prompt.prepare((_HISTORY_TOOL,))
    prompt_initial = [dict(message) for message in russian_short]
    if prompt_prepared.prompt_suffix is None:
        raise RuntimeError("prompt presentation produced no declaration")
    prompt_initial.insert(
        len(prompt_initial) - 1,
        {"role": "system", "content": prompt_prepared.prompt_suffix},
    )
    prompt_followup = [
        *prompt_initial,
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "tool_call": {
                        "name": _HISTORY_TOOL.name,
                        "arguments": _TOOL_ARGUMENTS,
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
        prompt.result_message(_TOOL_RESULT),
    ]

    return (
        _case(backend, "russian_short_initial", "initial", russian_short),
        _case(backend, "english_code_initial", "initial", english_code),
        _case(backend, "system_memory_initial", "initial", system_memory),
        _case(backend, "mixed_long_initial", "initial", mixed_long),
        _case(
            backend,
            "native_tool_initial",
            "initial",
            native_initial,
            native_prepared.tools,
        ),
        _case(
            backend,
            "native_tool_followup",
            "followup",
            native_followup,
            native_prepared.tools,
        ),
        _case(backend, "prompt_tool_initial", "initial", prompt_initial),
        _case(backend, "prompt_tool_followup", "followup", prompt_followup),
    )


def _case(
    backend: OllamaBackend,
    key: str,
    phase: str,
    messages: Sequence[dict[str, object]],
    tools: Sequence[dict[str, object]] | None = None,
) -> MeasurementCase:
    payload = backend.build_payload(
        messages,
        reasoning_level=ReasoningLevel.HIGH,
        tools=tools,
    )
    options = payload.get("options")
    bounded_options = dict(options) if isinstance(options, dict) else {}
    bounded_options.update({"temperature": 0, "seed": 1, "num_predict": 1})
    payload["options"] = bounded_options
    return MeasurementCase(key=key, phase=phase, payload=payload)


def _sentencepiece_counter(model_path: Path) -> MaterialCounter:
    import sentencepiece

    processor = sentencepiece.SentencePieceProcessor(model_file=str(model_path))

    def count(material: str) -> int:
        return len(processor.encode(material, out_type=int))

    return count


async def _read_chunks(
    client: httpx.AsyncClient, payload: dict[str, object]
) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    async with client.stream("POST", "/api/chat", json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("Ollama stream item is not a JSON object")
                chunks.append(value)
    return chunks


async def _ollama_version(client: httpx.AsyncClient) -> str:
    response = await client.get("/api/version")
    response.raise_for_status()
    value = response.json().get("version")
    return value if isinstance(value, str) else "unknown"


def _case_report(
    case: MeasurementCase, measurements: Sequence[LiveMeasurement]
) -> dict[str, object]:
    material = canonical_prompt_material(case.payload)
    messages = case.payload["messages"]
    tools = case.payload.get("tools")
    return {
        "key": case.key,
        "phase": case.phase,
        "material_sha256": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "material_chars": len(material),
        "material_utf8_bytes": len(material.encode("utf-8")),
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "tool_count": len(tools) if isinstance(tools, list) else 0,
        "runs": [
            {
                "run_index": row.run_index,
                "prompt_eval_count": row.prompt_eval_count,
                "estimates": row.estimates,
            }
            for row in measurements
        ],
        "identical_payload_count_consistent": len(
            {row.prompt_eval_count for row in measurements}
        )
        == 1,
    }


async def run(output_path: Path, tokenizer_model: Path | None) -> None:
    settings = load_settings()
    memory_loader = MemoryFileLoader(build_memory_file_specs(settings.memory))
    base_prompt = memory_loader.compose_system_prompt(settings.prompts.system)
    effective_prompt = _compose_effective_system_prompt(
        base_prompt,
        ReasoningLevel.HIGH,
        settings.prompts,
    )
    compatible_counter = (
        _sentencepiece_counter(tokenizer_model) if tokenizer_model is not None else None
    )

    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint,
        timeout=timeout,
    ) as client:
        backend = OllamaBackend(EventBus(), settings.backend, client=client)
        cases = build_measurement_cases(backend, effective_prompt)
        all_measurements: list[LiveMeasurement] = []
        case_reports: list[dict[str, object]] = []
        for case in cases:
            estimates = estimate_candidates(
                case.payload,
                compatible_counter=compatible_counter,
            )
            rows: list[LiveMeasurement] = []
            for run_index in range(1, RUNS_PER_CASE + 1):
                count = parse_prompt_eval_count(
                    await _read_chunks(client, case.payload)
                )
                row = LiveMeasurement(case.key, run_index, count, estimates)
                rows.append(row)
                all_measurements.append(row)
            case_reports.append(_case_report(case, rows))

        candidate_names = sorted(
            {name for row in all_measurements for name in row.estimates}
        )
        report = {
            "schema_version": 1,
            "ollama_version": await _ollama_version(client),
            "model": settings.backend.model,
            "num_ctx": settings.backend.num_ctx,
            "runs_per_case": RUNS_PER_CASE,
            "candidate_assessment": {
                "ollama_prompt_eval_count": {
                    "kind": "exact_post_dispatch_reference",
                    "pre_dispatch_viable": False,
                    "reason": (
                        "Available only after Ollama has accepted and evaluated "
                        "the complete chat request."
                    ),
                },
                "compatible_sentencepiece_material": {
                    "kind": "lightweight_compatible_tokenizer",
                    "measured": compatible_counter is not None,
                    "reason": (
                        "Counts canonical message/tool material but not Ollama's "
                        "private rendered chat template."
                    ),
                },
                "conservative_utf8": {
                    "kind": "fixed_overhead_estimator",
                    "formula": {
                        "utf8_bytes_per_token": BYTES_PER_ESTIMATED_TOKEN,
                        "base_tokens": BASE_TOKEN_OVERHEAD,
                        "tokens_per_message": MESSAGE_TOKEN_OVERHEAD,
                        "tokens_per_tool": TOOL_TOKEN_OVERHEAD,
                    },
                },
            },
            "cases": case_reports,
            "candidate_summaries": [
                asdict(summarize_candidate(all_measurements, name))
                for name in candidate_names
            ],
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote machine-readable results to {output_path.resolve()}")
    for summary in report["candidate_summaries"]:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))

    inconsistent = [
        case["key"]
        for case in case_reports
        if not case["identical_payload_count_consistent"]
    ]
    if inconsistent:
        names = ", ".join(str(key) for key in inconsistent)
        raise RuntimeError(f"prompt_eval_count changed for identical payloads: {names}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--sentencepiece-model-path",
        "--tokenizer-model",
        dest="tokenizer_model",
        type=sentencepiece_model_path,
        help=(
            "Optional filesystem path to an existing local SentencePiece model "
            "file. This is not an Ollama model name; the script never downloads "
            "tokenizer assets."
        ),
    )
    args = parser.parse_args()
    asyncio.run(run(args.output, args.tokenizer_model))


if __name__ == "__main__":
    main()
