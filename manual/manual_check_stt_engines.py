#!/usr/bin/env python3
"""Harness of tasks/spike-v2.1.0-5-stt-engines.md.

Compares dedicated speech-to-text engines on the recordings of spike
v2.1.0-1. `run` and `coexist` need an engine package and therefore run in the
engine's own virtual environment; `score` is pure and runs anywhere.

  PY -m manual.manual_check_stt_engines --out DIR run --engine E --wavs WAVS
  PY -m manual.manual_check_stt_engines --out DIR coexist --engine E --wavs WAVS
  python -m manual.manual_check_stt_engines --out DIR score --wavs WAVS

PY is the engine's own virtual-environment interpreter.

`--out` goes before the subcommand. Engines: whisper_ru, whisper_auto, gigaam,
whisper_ru_cpu, gigaam_cpu.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from manual.personal_proxy.audio import WavDirectory, WavDirectoryError, control_audio
from manual.personal_proxy.corpus import (
    CONTROLS,
    CORPUS,
    corpus_fingerprint,
    utterance_by_id,
)
from manual.personal_proxy.scoring import looks_like_audio_failure
from manual.personal_proxy.stt_scoring import (
    Adequacy,
    Coexistence,
    Engine,
    EngineMetrics,
    EngineScore,
    adequacy,
    aggregate,
    choose,
    control_is_clean,
    cpu_resource_ok,
    fidelity_by_group,
    overall_fidelity,
    render_report,
    resource_ok,
    score_transcript,
)
from manual.personal_proxy.text import word_error_rate
from manual.personal_proxy.transcription_ab import (
    KNOWN_RECORDING_DEVIATIONS,
    reference_text,
)

DEFAULT_OUT = Path("manual_check_stt_engines_out")
DEFAULT_BASELINE_CALLS = Path("manual_check_transcription_prompt_out") / "calls"
DEFAULT_REFERENCE_REQUEST = DEFAULT_BASELINE_CALLS / "a_current-id_email-s19210.json"
PASSES = (1, 2)
COEXIST_IDS = (
    "id_short_call",
    "id_email",
    "id_card",
    "id_address",
    "id_employer_boss",
    "q_judge",
    "m_github",
    "id_delivery_long",
    "n_cpu_cache",
    "id_letter_long",
)
GEMMA_PROBE = "Say one short sentence."
REPORT_NAME = "report.md"


def decode(audio: bytes) -> tuple[np.ndarray, float]:
    samples, rate = sf.read(io.BytesIO(audio), dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if rate != 16000:
        raise ValueError(f"expected 16 kHz audio, got {rate}")
    return samples.astype(np.float32), len(samples) / rate


def subjects(wavs: WavDirectory) -> list[tuple[str, bytes]]:
    found = [(u.utterance_id, wavs.audio_for(u.utterance_id)) for u in CORPUS]
    for control in CONTROLS:
        audio = control_audio(control)
        if audio is not None:
            found.append((control.control_id, audio))
    return found


def call_path(calls_dir: Path, engine: Engine, subject_id: str, pass_no: int) -> Path:
    return calls_dir / f"{engine.value}-{subject_id}-p{pass_no}.json"


def write_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def command_run(args: argparse.Namespace) -> int:
    from manual.personal_proxy.stt_engines import (
        PeakGpuMemory,
        gpu_memory_used_mib,
        make_engine,
        package_versions,
    )

    engine = Engine(args.engine)
    wavs = WavDirectory(args.wavs)
    items = subjects(wavs)
    calls_dir = args.out / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    runner = make_engine(engine)
    before = gpu_memory_used_mib()
    started = time.perf_counter()
    runner.load()
    load_seconds = time.perf_counter() - started
    after_load = gpu_memory_used_mib()
    print(f"{engine.value}: loaded in {load_seconds:.1f}s", flush=True)
    warm_samples, _ = decode(items[0][1])
    runner.transcribe(warm_samples)
    ran = skipped = 0
    with PeakGpuMemory() as peak:
        for pass_no in PASSES:
            for subject_id, audio in items:
                path = call_path(calls_dir, engine, subject_id, pass_no)
                if path.exists():
                    skipped += 1
                    continue
                samples, audio_seconds = decode(audio)
                begin = time.perf_counter()
                transcript = runner.transcribe(samples)
                seconds = time.perf_counter() - begin
                write_json(
                    path,
                    {
                        "engine": engine.value,
                        "subject_id": subject_id,
                        "pass_no": pass_no,
                        "transcript": transcript,
                        "seconds": seconds,
                        "audio_seconds": audio_seconds,
                    },
                )
                ran += 1
                print(
                    f"{engine.value}-{subject_id}-p{pass_no}: {seconds:.2f}s "
                    f"| {transcript[:70]!r}",
                    flush=True,
                )
    write_json(
        args.out / f"memory-{engine.value}.json",
        {
            "gpu_used_before_mib": before,
            "gpu_used_after_load_mib": after_load,
            "gpu_used_peak_mib": peak.peak,
            "load_seconds": round(load_seconds, 2),
            "packages": package_versions(),
            "wav_set_hash": wavs.set_hash(),
            "corpus_fingerprint": corpus_fingerprint(),
            "recording_deviations": {
                k: list(v) for k, v in KNOWN_RECORDING_DEVIATIONS.items()
            },
        },
    )
    print(f"Done: ran {ran}, skipped {skipped}", flush=True)
    return 0


def _ollama_post(client: Any, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=body, timeout=600.0)
    response.raise_for_status()
    return response.json()


def _gpu_share(client: Any, model: str) -> float | None:
    running = client.get("/api/ps", timeout=30.0).json().get("models", [])
    entry = next((m for m in running if model in (m.get("name"), m.get("model"))), None)
    if entry is None or not entry.get("size"):
        return None
    return round(entry.get("size_vram", 0) / entry["size"], 3)


def _gemma_seconds(client: Any, payload: dict[str, Any]) -> float:
    begin = time.perf_counter()
    _ollama_post(client, "/api/chat", payload)
    return time.perf_counter() - begin


def command_coexist(args: argparse.Namespace) -> int:
    import httpx

    from manual.personal_proxy.stt_engines import gpu_memory_used_mib, make_engine

    engine = Engine(args.engine)
    reference = json.loads(args.reference_request.read_text(encoding="utf-8"))
    request = reference["call"]["request"]
    model = request["model"]
    options = {**request["options"], "seed": 1, "num_predict": 32}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": GEMMA_PROBE}],
        "stream": False,
        "think": False,
        "options": options,
    }
    wavs = WavDirectory(args.wavs)
    audio = {uid: wavs.audio_for(uid) for uid in COEXIST_IDS}
    endpoint = args.endpoint
    result: dict[str, Any] = {"engine": engine.value, "model": model}
    with httpx.Client(base_url=endpoint) as client:
        _gemma_seconds(client, payload)
        result["gemma_seconds_before"] = round(_gemma_seconds(client, payload), 3)
        result["gpu_share_before"] = _gpu_share(client, model)
        result["gpu_used_with_gemma_mib"] = gpu_memory_used_mib()
        runner = make_engine(engine)
        try:
            runner.load()
            samples, _ = decode(audio[COEXIST_IDS[0]])
            runner.transcribe(samples)
            seconds = []
            for uid in COEXIST_IDS:
                samples, _ = decode(audio[uid])
                begin = time.perf_counter()
                runner.transcribe(samples)
                seconds.append(time.perf_counter() - begin)
            result["engine_median_seconds"] = round(statistics.median(seconds), 3)
            result["engine_error"] = None
        except Exception as error:
            result["engine_median_seconds"] = None
            result["engine_error"] = repr(error)
        result["gpu_used_with_both_mib"] = gpu_memory_used_mib()
        result["gpu_share_after"] = _gpu_share(client, model)
        result["gemma_seconds_after"] = round(_gemma_seconds(client, payload), 3)
        _ollama_post(
            client, "/api/generate", {"model": model, "prompt": "", "keep_alive": 0}
        )
    write_json(args.out / f"coexist-{engine.value}.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return 0


def read_calls(calls_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(calls_dir.glob("*.json"))
    ]


def read_baseline(
    calls_dir: Path,
) -> tuple[dict[str, tuple[int, int]], int, float | None]:
    corpus_ids = {u.utterance_id for u in CORPUS}
    pairs = []
    for path in sorted(calls_dir.glob("a_current-*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["subject_id"] in corpus_ids:
            pairs.append(
                (
                    utterance_by_id(document["subject_id"]),
                    document["call"]["response_text"],
                )
            )
    failures = sum(
        looks_like_audio_failure(text, reference_text(u)) for u, text in pairs
    )
    wers = [word_error_rate(reference_text(u), text) for u, text in pairs]
    return (
        fidelity_by_group(pairs),
        failures,
        (statistics.median(wers) if wers else None),
    )


def load_coexistence(
    out: Path, metrics: dict[Engine, EngineMetrics]
) -> dict[Engine, Coexistence]:
    found: dict[Engine, Coexistence] = {}
    for path in sorted(out.glob("coexist-*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        engine = Engine(d["engine"])
        isolated = metrics[engine].median_seconds if engine in metrics else None
        found[engine] = Coexistence(
            engine,
            d.get("gpu_share_before"),
            d.get("gpu_share_after"),
            d.get("engine_median_seconds"),
            isolated,
            d.get("gemma_seconds_before"),
            d.get("gemma_seconds_after"),
        )
    return found


def effective(
    gpu: Engine,
    cpu: Engine,
    metrics: dict[Engine, EngineMetrics],
    coexistence: dict[Engine, Coexistence],
    baseline_fidelity: float | None,
) -> tuple[EngineMetrics | None, Adequacy | None]:
    if gpu not in metrics:
        return None, None
    on_gpu = adequacy(
        metrics[gpu], baseline_fidelity, resource_ok(coexistence.get(gpu))
    )
    fails_only_resources = on_gpu.accuracy and on_gpu.fidelity and not on_gpu.resources
    if fails_only_resources and cpu in metrics:
        return metrics[cpu], adequacy(
            metrics[cpu], baseline_fidelity, cpu_resource_ok(metrics[cpu])
        )
    return metrics[gpu], on_gpu


def command_score(args: argparse.Namespace) -> int:
    calls = read_calls(args.out / "calls")
    if not calls:
        print("No calls to score.", file=sys.stderr)
        return 2
    corpus_ids = {u.utterance_id for u in CORPUS}
    scores: list[EngineScore] = []
    controls: dict[Engine, list[tuple[str, bool]]] = {}
    for call in calls:
        engine = Engine(call["engine"])
        if call["subject_id"] in corpus_ids:
            scores.append(
                score_transcript(
                    engine,
                    utterance_by_id(call["subject_id"]),
                    call["pass_no"],
                    call["transcript"],
                    call["seconds"],
                    call["audio_seconds"],
                )
            )
        else:
            controls.setdefault(engine, []).append(
                (call["transcript"], control_is_clean(call["transcript"]))
            )
    metrics = {e: aggregate(e, scores) for e in {s.engine for s in scores}}
    baseline, baseline_failures, baseline_wer = read_baseline(args.baseline_calls)
    baseline_fidelity = overall_fidelity(baseline)
    coexistence = load_coexistence(args.out, metrics)
    whisper, whisper_a = effective(
        Engine.WHISPER_RU,
        Engine.WHISPER_RU_CPU,
        metrics,
        coexistence,
        baseline_fidelity,
    )
    gigaam, gigaam_a = effective(
        Engine.GIGAAM, Engine.GIGAAM_CPU, metrics, coexistence, baseline_fidelity
    )
    outcome = choose(
        whisper,
        gigaam,
        bool(whisper_a and whisper_a.adequate),
        bool(gigaam_a and gigaam_a.adequate),
    )
    adequacies = {
        m.engine: a
        for m, a in ((whisper, whisper_a), (gigaam, gigaam_a))
        if m is not None and a is not None
    }
    memory = {
        e: json.loads(p.read_text(encoding="utf-8"))
        for e in metrics
        if (p := args.out / f"memory-{e.value}.json").exists()
    }
    report = render_report(
        meta={
            "baseline_calls": str(args.baseline_calls),
            "engines": sorted(e.value for e in metrics),
        },
        metrics=[metrics[e] for e in sorted(metrics, key=lambda e: e.value)],
        scores=scores,
        controls=controls,
        baseline=baseline,
        baseline_failures=baseline_failures,
        baseline_wer=baseline_wer,
        adequacies=adequacies,
        outcome=outcome,
        memory=memory,
        coexistence=list(coexistence.values()),
    )
    (args.out / REPORT_NAME).write_text(report, encoding="utf-8")
    print(report)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "coexist", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--wavs", type=Path, required=True)
        if name in ("run", "coexist"):
            sub.add_argument(
                "--engine", choices=[e.value for e in Engine], required=True
            )
        if name == "coexist":
            sub.add_argument("--endpoint", default="http://localhost:11434")
            sub.add_argument(
                "--reference-request", type=Path, default=DEFAULT_REFERENCE_REQUEST
            )
        if name == "score":
            sub.add_argument(
                "--baseline-calls", type=Path, default=DEFAULT_BASELINE_CALLS
            )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "run":
            return command_run(args)
        if args.command == "coexist":
            return command_coexist(args)
        return command_score(args)
    except WavDirectoryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
