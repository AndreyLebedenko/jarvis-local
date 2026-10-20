#!/usr/bin/env python3
"""Human-run harness of tasks/done/spike-v2.1.0-1-combined-transcribe-sanitize.md.

Talks to the live local Ollama endpoint, so it is run by the human under the
repository testing protocol; the agent only prepares it. Subcommands:

  python -m manual.manual_check_personal_proxy_spike --out DIR stage0 --wavs WAVS
  python -m manual.manual_check_personal_proxy_spike --out DIR run --wavs WAVS
  python -m manual.manual_check_personal_proxy_spike --out DIR score --wavs WAVS

`--out` goes before the subcommand. The exact steps, with expected output, are
in tasks/done/spike-v2.1.0-1-handoff.md.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from jarvis.core.bus import EventBus
from jarvis.core.config import TRANSCRIPTION_PROFILE, Settings, load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.journal.transcription import DEFAULT_TRANSCRIPTION_INSTRUCTION
from manual.personal_proxy.audio import (
    WavDirectory,
    WavDirectoryError,
    control_audio,
    sha256_hex,
)
from manual.personal_proxy.corpus import (
    CONTROLS,
    CORPUS,
    corpus_fingerprint,
    corpus_problems,
    topics_text,
    utterance_by_id,
)
from manual.personal_proxy.decision import decide
from manual.personal_proxy.prompts import prompts_fingerprint
from manual.personal_proxy.records import (
    Arm,
    CallRecord,
    GenerationRecord,
    load_generations,
)
from manual.personal_proxy.report import render_report
from manual.personal_proxy.runner import (
    ARMS,
    NUM_PREDICT,
    GenerationRunner,
    PlannedRequest,
    choose_use_format,
    ensure_run_meta,
    plan_jobs,
    run_jobs,
)
from manual.personal_proxy.scoring import aggregate, score_records

DEFAULT_OUT = Path("manual_check_personal_proxy_spike_out")
DEFAULT_CONFIG = Path("config.toml")
META_NAME = "run_meta.json"
STAGE0_DECISION_NAME = "stage0_decision.json"
REPORT_NAME = "report.md"
STAGE0_IDS = (
    "id_phone_words",
    "id_email",
    "id_card",
    "id_employer_boss",
    "id_short_call",
    "id_delivery_long",
    "q_judge",
    "m_github",
    "m_short_english",
    "t_diabetes",
    "n_cpu_cache",
    "n_short_tokyo",
)
STAGE0_SEEDS_COUNT = 2


class OllamaModelCaller:
    """The live ModelCaller: production payload shape, one streamed call."""

    def __init__(self, backend: OllamaBackend, client: httpx.AsyncClient) -> None:
        self._backend = backend
        self._client = client

    async def __call__(self, request: PlannedRequest) -> CallRecord:
        images = (
            [base64.b64encode(request.audio).decode("ascii")] if request.audio else None
        )
        payload = self._backend.build_payload(
            list(request.messages), images, ReasoningLevel.OFF, options=request.options
        )
        if request.response_format is not None:
            payload["format"] = request.response_format
        started = time.perf_counter()
        text, final = await self._stream(payload)
        return CallRecord(
            stage=request.stage,
            request=redact_audio(payload, request.audio),
            response_text=text,
            done_reason=final.get("done_reason"),
            eval_count=final.get("eval_count", 0),
            prompt_eval_count=final.get("prompt_eval_count", 0),
            load_seconds=final.get("load_duration", 0) / 1e9,
            total_seconds=time.perf_counter() - started,
        )

    async def _stream(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        parts: list[str] = []
        final: dict[str, Any] = {}
        async with self._client.stream("POST", "/api/chat", json=payload) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Ollama returned {response.status_code}: {body[:300]}"
                )
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise RuntimeError(f"Ollama error: {chunk['error']}")
                content = chunk.get("message", {}).get("content")
                if content:
                    parts.append(content)
                if chunk.get("done"):
                    final = chunk
        return "".join(parts), final


def redact_audio(payload: dict[str, Any], audio: bytes | None) -> dict[str, Any]:
    """The payload as recorded: base64 audio replaced by its SHA-256."""
    recorded = copy.deepcopy(payload)
    if audio is not None:
        marker = f"[audio wav sha256={sha256_hex(audio)} bytes={len(audio)}]"
        for message in recorded["messages"]:
            if "images" in message:
                message["images"] = [marker]
    return recorded


async def fetch_provenance(client: httpx.AsyncClient, model: str) -> dict[str, Any]:
    version = (await client.get("/api/version")).json().get("version")
    tags = (await client.get("/api/tags")).json().get("models", [])
    digest = next(
        (m.get("digest") for m in tags if model in (m.get("name"), m.get("model"))),
        None,
    )
    if digest is None:
        raise SystemExit(f"model {model!r} is not listed by Ollama; run 'ollama list'")
    return {"ollama_version": version, "model_digest": digest}


async def fetch_placement(client: httpx.AsyncClient, model: str) -> dict[str, Any]:
    running = (await client.get("/api/ps")).json().get("models", [])
    entry = next((m for m in running if model in (m.get("name"), m.get("model"))), None)
    if entry is None:
        return {"vram_share": None}
    size, vram = entry.get("size", 0), entry.get("size_vram", 0)
    return {"vram_share": round(vram / size, 3) if size else None}


def build_meta(
    settings: Settings,
    config_path: Path,
    provenance: dict[str, Any],
    *,
    use_format: bool,
    wav_set_hash: str,
    instruction: str,
) -> dict[str, Any]:
    profile = settings.generation.profile(TRANSCRIPTION_PROFILE)
    return {
        "model": settings.backend.model,
        "endpoint": settings.backend.endpoint,
        "ollama_version": provenance["ollama_version"],
        "model_digest": provenance["model_digest"],
        "effective_options": settings.generation.options_for(
            TRANSCRIPTION_PROFILE
        ).as_request_options(),
        "num_predict_cap": NUM_PREDICT,
        "transcription_profile_reasoning": profile.reasoning,
        "transcribe_instruction": instruction,
        "ui_config_override_present": config_path.with_name("config.ui.toml").exists(),
        "use_format": use_format,
        "corpus_fingerprint": corpus_fingerprint(),
        "prompts_fingerprint": prompts_fingerprint(),
        "wav_set_hash": wav_set_hash,
    }


def make_environment(args: argparse.Namespace):
    settings = load_settings(args.config)
    profile = settings.generation.profile(TRANSCRIPTION_PROFILE)
    client = httpx.AsyncClient(
        base_url=settings.backend.endpoint,
        timeout=httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds),
    )
    backend = OllamaBackend(EventBus(), settings.backend, client)
    options = settings.generation.options_for(TRANSCRIPTION_PROFILE)
    instruction = profile.prompt or DEFAULT_TRANSCRIPTION_INSTRUCTION
    return settings, client, backend, options, instruction


def make_runner(
    backend: OllamaBackend,
    client: httpx.AsyncClient,
    options,
    instruction: str,
    *,
    use_format: bool,
) -> GenerationRunner:
    return GenerationRunner(
        OllamaModelCaller(backend, client),
        options,
        transcribe_instruction=instruction,
        topics=topics_text(),
        use_format=use_format,
    )


def audio_lookup(wavs: WavDirectory):
    controls = {c.control_id: control_audio(c) for c in CONTROLS}

    def lookup(subject_id: str) -> bytes | None:
        if subject_id in controls:
            return controls[subject_id]
        return wavs.audio_for(subject_id)

    return lookup


def print_progress(record: GenerationRecord) -> None:
    status = "ERROR " + record.error if record.error else "ok"
    stages = " ".join(
        f"{c.stage.value}={c.total_seconds:.1f}s prompt_eval={c.prompt_eval_count} "
        f"eval={c.eval_count} done={c.done_reason}"
        for c in record.calls
    )
    print(f"{record.slug}: {status} | {stages}", flush=True)


async def command_stage0(args: argparse.Namespace) -> int:
    wavs = WavDirectory(args.wavs)
    settings, client, backend, options, instruction = make_environment(args)
    provenance = await fetch_provenance(client, settings.backend.model)
    ids = list(STAGE0_IDS)
    seeds = tuple(range(STAGE0_SEEDS_COUNT))
    lookup = audio_lookup(wavs)
    valid: dict[bool, int] = {}
    total: dict[bool, int] = {}
    for use_format in (False, True):
        runner = make_runner(
            backend, client, options, instruction, use_format=use_format
        )
        calls_dir = (
            args.out / "stage0" / ("format" if use_format else "plain") / "calls"
        )
        jobs = plan_jobs(ids, seeds=seeds, arms=(Arm.C_USER,))
        print(f"Stage 0, constrained format = {use_format}", flush=True)
        await run_jobs(
            runner,
            jobs,
            lookup,
            calls_dir,
            warm_audio=lookup(ids[0]),
            progress=print_progress,
        )
        scores = score_records(load_generations(calls_dir), CONTROLS)
        metrics = aggregate(Arm.C_USER, scores)
        valid[use_format], total[use_format] = metrics.valid, metrics.generations
        print(f"  valid {metrics.valid}/{metrics.generations}", flush=True)
    chosen = choose_use_format(valid[True], total[True], valid[False], total[False])
    decision = {
        "use_format": chosen,
        "constrained_valid": valid[True],
        "plain_valid": valid[False],
        "generations_each": total[True],
        "model_digest": provenance["model_digest"],
    }
    (args.out / STAGE0_DECISION_NAME).write_text(
        json.dumps(decision, indent=2), encoding="utf-8"
    )
    print(f"Stage 0 decision: {decision}", flush=True)
    await client.aclose()
    return 0


async def command_run(args: argparse.Namespace) -> int:
    decision_path = args.out / STAGE0_DECISION_NAME
    if not decision_path.exists():
        print("Run stage0 first: no stage0_decision.json.", file=sys.stderr)
        return 2
    use_format = json.loads(decision_path.read_text(encoding="utf-8"))["use_format"]
    wavs = WavDirectory(args.wavs)
    settings, client, backend, options, instruction = make_environment(args)
    provenance = await fetch_provenance(client, settings.backend.model)
    meta = build_meta(
        settings,
        args.config,
        provenance,
        use_format=use_format,
        wav_set_hash=wavs.set_hash(),
        instruction=instruction,
    )
    ensure_run_meta(args.out / META_NAME, meta)
    if meta["ui_config_override_present"]:
        print(
            "NOTE: config.ui.toml exists next to the config; the effective "
            f"model is {settings.backend.model}.",
            flush=True,
        )
    runner = make_runner(backend, client, options, instruction, use_format=use_format)
    lookup = audio_lookup(wavs)
    subject_ids = [u.utterance_id for u in CORPUS] + [c.control_id for c in CONTROLS]
    jobs = plan_jobs(subject_ids, arms=ARMS)
    print(
        f"{len(jobs)} generations planned; model {settings.backend.model}", flush=True
    )
    started = time.perf_counter()
    summary = await run_jobs(
        runner,
        jobs,
        lookup,
        args.out / "calls",
        warm_audio=lookup(CORPUS[0].utterance_id),
        progress=print_progress,
    )
    placement = await fetch_placement(client, settings.backend.model)
    meta = {**meta, "placement_after_run": placement}
    (args.out / "placement.json").write_text(json.dumps(placement), encoding="utf-8")
    print(
        f"Done in {(time.perf_counter() - started) / 60:.1f} min: ran {summary.ran}, "
        f"skipped {summary.skipped}, errored {summary.errored}. "
        f"GPU share of the model: {placement['vram_share']}",
        flush=True,
    )
    await client.aclose()
    return 0


def command_score(args: argparse.Namespace) -> int:
    meta_path = args.out / META_NAME
    if not meta_path.exists():
        print("No run_meta.json: nothing to score.", file=sys.stderr)
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if WavDirectory(args.wavs).set_hash() != meta["wav_set_hash"]:
        print("The recordings differ from the ones the run used.", file=sys.stderr)
        return 2
    scores = score_records(load_generations(args.out / "calls"), CONTROLS)
    metrics = [aggregate(arm, scores) for arm in ARMS]
    decision = decide(metrics[0], metrics[1:])
    placement_path = args.out / "placement.json"
    if placement_path.exists():
        meta["placement_after_run"] = json.loads(placement_path.read_text("utf-8"))
    report = render_report(
        meta=meta,
        decision=decision,
        metrics=metrics,
        scores=scores,
        duration_of=lambda uid: utterance_by_id(uid).estimated_seconds,
    )
    (args.out / REPORT_NAME).write_text(report, encoding="utf-8")
    print(report)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("stage0", "run", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--wavs", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    problems = corpus_problems()
    if problems:
        print("The frozen corpus is inconsistent:\n  " + "\n  ".join(problems))
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "score":
            return command_score(args)
        handler = command_stage0 if args.command == "stage0" else command_run
        return asyncio.run(handler(args))
    except WavDirectoryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
