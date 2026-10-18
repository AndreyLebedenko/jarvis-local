#!/usr/bin/env python3
"""Harness of tasks/spike-v2.1.0-2-transcription-prompt.md.

Compares the current transcription instruction (A) with the owner's reworded
one (B) on the recordings of spike v2.1.0-1. Talks to the live local Ollama
endpoint. Subcommands:

  python -m manual.manual_check_transcription_prompt --out DIR run --wavs WAVS
  python -m manual.manual_check_transcription_prompt --out DIR score --wavs WAVS

`--out` goes before the subcommand. Both variants send the production request
shape: one user message, the WAV in `images`, no system message, no `format`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from jarvis.core.config import GenerationOptions
from jarvis.journal.transcription import build_transcription_messages
from manual.manual_check_personal_proxy_spike import (
    DEFAULT_CONFIG,
    OllamaModelCaller,
    audio_lookup,
    fetch_placement,
    fetch_provenance,
    make_environment,
)
from manual.personal_proxy.audio import WavDirectory, WavDirectoryError
from manual.personal_proxy.corpus import (
    CONTROLS,
    CORPUS,
    SEEDS,
    corpus_fingerprint,
    utterance_by_id,
)
from manual.personal_proxy.records import Arm, CallStage, load_generations
from manual.personal_proxy.runner import (
    CACHE_RESET_NUM_PREDICT,
    CACHE_RESET_SYSTEM,
    CACHE_RESET_USER,
    NUM_PREDICT,
    WARMUP_INSTRUCTION,
    PlannedRequest,
    ensure_run_meta,
)
from manual.personal_proxy.transcription_ab import (
    KNOWN_RECORDING_DEVIATIONS,
    VARIANT_B_INSTRUCTION,
    TranscriptScore,
    Variant,
    render_report,
    score_transcript,
)

DEFAULT_OUT = Path("manual_check_transcription_prompt_out")
DEFAULT_MAIN_RUN_CALLS = Path("manual_check_personal_proxy_spike_out") / "calls"
META_NAME = "run_meta.json"
REPORT_NAME = "report.md"
VARIANTS = (Variant.A, Variant.B)


def call_path(calls_dir: Path, variant: Variant, subject_id: str, seed: int) -> Path:
    return calls_dir / f"{variant.value}-{subject_id}-s{seed}.json"


def plan_jobs(subject_ids: list[str]) -> list[tuple[Variant, str, int]]:
    """Seed by seed, subject by subject, alternating which variant goes first
    so a slow drift in the machine does not always fall on the same variant."""
    jobs: list[tuple[Variant, str, int]] = []
    for seed in SEEDS:
        for index, subject_id in enumerate(subject_ids):
            order = VARIANTS if index % 2 == 0 else VARIANTS[::-1]
            jobs.extend((variant, subject_id, seed) for variant in order)
    return jobs


def transcription_request(
    instruction: str,
    audio: bytes | None,
    options: GenerationOptions,
    seed: int,
) -> PlannedRequest:
    return PlannedRequest(
        CallStage.TRANSCRIBE,
        tuple(
            {"role": m.role, "content": m.content}
            for m in build_transcription_messages(instruction)
        ),
        audio,
        replace(options, seed=seed, num_predict=NUM_PREDICT),
    )


def write_call(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


async def command_run(args: argparse.Namespace) -> int:
    wavs = WavDirectory(args.wavs)
    settings, client, backend, options, instruction_a = make_environment(args)
    provenance = await fetch_provenance(client, settings.backend.model)
    meta = {
        "model": settings.backend.model,
        "endpoint": settings.backend.endpoint,
        "ollama_version": provenance["ollama_version"],
        "model_digest": provenance["model_digest"],
        "effective_options": options.as_request_options(),
        "num_predict_cap": NUM_PREDICT,
        "instruction_a": instruction_a,
        "instruction_b": VARIANT_B_INSTRUCTION,
        "recording_deviations": {
            k: list(v) for k, v in KNOWN_RECORDING_DEVIATIONS.items()
        },
        "corpus_fingerprint": corpus_fingerprint(),
        "wav_set_hash": wavs.set_hash(),
    }
    ensure_run_meta(args.out / META_NAME, meta)
    instructions = {Variant.A: instruction_a, Variant.B: VARIANT_B_INSTRUCTION}
    caller = OllamaModelCaller(backend, client)
    lookup = audio_lookup(wavs)
    subject_ids = [u.utterance_id for u in CORPUS] + [c.control_id for c in CONTROLS]
    calls_dir = args.out / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    jobs = plan_jobs(subject_ids)
    print(
        f"{len(jobs)} generations planned; model {settings.backend.model}", flush=True
    )

    await caller(
        PlannedRequest(
            CallStage.TRANSCRIBE,
            ({"role": "user", "content": WARMUP_INSTRUCTION},),
            lookup(CORPUS[0].utterance_id),
            replace(options, num_predict=32),
        )
    )
    started = time.perf_counter()
    ran = skipped = 0
    for variant, subject_id, seed in jobs:
        path = call_path(calls_dir, variant, subject_id, seed)
        if path.exists():
            skipped += 1
            continue
        await caller(
            PlannedRequest(
                CallStage.COMBINED,
                (
                    {"role": "system", "content": CACHE_RESET_SYSTEM},
                    {"role": "user", "content": CACHE_RESET_USER},
                ),
                None,
                GenerationOptions(num_predict=CACHE_RESET_NUM_PREDICT),
            )
        )
        record = await caller(
            transcription_request(
                instructions[variant], lookup(subject_id), options, seed
            )
        )
        write_call(
            path,
            {
                "variant": variant.value,
                "subject_id": subject_id,
                "seed": seed,
                "call": asdict(record),
            },
        )
        ran += 1
        print(
            f"{variant.value}-{subject_id}-s{seed}: {record.total_seconds:.1f}s "
            f"done={record.done_reason} | {record.response_text[:70]!r}",
            flush=True,
        )
    placement = await fetch_placement(client, settings.backend.model)
    (args.out / "placement.json").write_text(json.dumps(placement), encoding="utf-8")
    print(
        f"Done in {(time.perf_counter() - started) / 60:.1f} min: ran {ran}, "
        f"skipped {skipped}. GPU share of the model: {placement['vram_share']}",
        flush=True,
    )
    await client.aclose()
    return 0


def load_transcripts(calls_dir: Path) -> dict[tuple[Variant, str, int], str]:
    found: dict[tuple[Variant, str, int], str] = {}
    for path in sorted(calls_dir.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        key = (
            Variant(document["variant"]),
            document["subject_id"],
            document["seed"],
        )
        found[key] = document["call"]["response_text"]
    return found


def main_run_baseline_transcripts(calls_dir: Path) -> dict[tuple[str, int], str]:
    if not calls_dir.exists():
        return {}
    return {
        (record.subject_id, record.seed): record.calls[0].response_text
        for record in load_generations(calls_dir)
        if record.arm is Arm.T_PLUS_S and record.calls
    }


def command_score(args: argparse.Namespace) -> int:
    meta_path = args.out / META_NAME
    if not meta_path.exists():
        print("No run_meta.json: nothing to score.", file=sys.stderr)
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if WavDirectory(args.wavs).set_hash() != meta["wav_set_hash"]:
        print("The recordings differ from the ones the run used.", file=sys.stderr)
        return 2
    transcripts = load_transcripts(args.out / "calls")
    scores: list[TranscriptScore] = []
    controls: dict[Variant, dict[str, list[str]]] = {v: {} for v in VARIANTS}
    corpus_ids = {u.utterance_id for u in CORPUS}
    for (variant, subject_id, seed), transcript in sorted(
        transcripts.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
    ):
        if subject_id in corpus_ids:
            scores.append(
                score_transcript(variant, utterance_by_id(subject_id), seed, transcript)
            )
        else:
            controls[variant].setdefault(subject_id, []).append(transcript)
    baseline = main_run_baseline_transcripts(args.main_run_calls)
    pairs = [
        (baseline[(s.subject_id, s.seed)], s.transcript)
        for s in scores
        if s.variant is Variant.A and (s.subject_id, s.seed) in baseline
    ]
    identical = (
        (sum(1 for old, new in pairs if old == new), len(pairs)) if pairs else None
    )
    placement_path = args.out / "placement.json"
    if placement_path.exists():
        meta["placement_after_run"] = json.loads(placement_path.read_text("utf-8"))
    report = render_report(
        meta=meta, scores=scores, controls=controls, identical_to_main_run=identical
    )
    (args.out / REPORT_NAME).write_text(report, encoding="utf-8")
    print(report)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--wavs", type=Path, required=True)
        if name == "score":
            sub.add_argument(
                "--main-run-calls", type=Path, default=DEFAULT_MAIN_RUN_CALLS
            )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "score":
            return command_score(args)
        return asyncio.run(command_run(args))
    except WavDirectoryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
