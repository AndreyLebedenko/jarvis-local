#!/usr/bin/env python3
"""Harness of tasks/done/spike-v2.1.0-7-stt-audio-check.md.

Gemma gets a Whisper transcript (from spike v2.1.0-5) with the recording (X) or
without it (Z) and returns a corrected transcript. Talks to the live local
Ollama endpoint. Subcommands:

  python -m manual.manual_check_stt_verification --out DIR run --wavs WAVS
  python -m manual.manual_check_stt_verification --out DIR score --wavs WAVS

`--out` goes before the subcommand.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from manual.manual_check_stt_engines import (
    DEFAULT_REFERENCE_REQUEST,
    _ollama_post,
    write_json,
)
from manual.personal_proxy.audio import WavDirectory, WavDirectoryError, control_audio
from manual.personal_proxy.corpus import (
    CONTROLS,
    CORPUS,
    SEEDS,
    corpus_fingerprint,
    utterance_by_id,
)
from manual.personal_proxy.stt_scoring import control_is_clean
from manual.personal_proxy.verification import (
    ERROR_HINT,
    Metrics,
    Variant,
    build_payload,
    decide,
    invented_address,
    paired_spans,
    rewrite_distance,
    score_transcripts,
)

DEFAULT_OUT = Path("manual_check_stt_verification_out")
DEFAULT_WHISPER_CALLS = Path("manual_check_stt_engines_out") / "calls"
DEFAULT_MODEL = "gemma4:12b"
DEFAULT_NUM_CTX = 8192
WARMUP_PROMPT = "Say one short sentence."
REPORT_NAME = "report.md"
REWRITE_THRESHOLD = 0.3


def whisper_transcript(calls_dir: Path, subject_id: str, seed: int) -> str:
    pass_no = SEEDS.index(seed) + 1
    path = calls_dir / f"whisper_ru-{subject_id}-p{pass_no}.json"
    return json.loads(path.read_text(encoding="utf-8"))["transcript"]


def subject_audio(wavs: WavDirectory) -> dict[str, bytes]:
    found = {u.utterance_id: wavs.audio_for(u.utterance_id) for u in CORPUS}
    for control in CONTROLS:
        audio = control_audio(control)
        if audio is not None:
            found[control.control_id] = audio
    return found


def call_path(calls_dir: Path, variant: Variant, subject_id: str, seed: int) -> Path:
    return calls_dir / f"{variant.value}-{subject_id}-s{seed}.json"


def plan_jobs(subject_ids: list[str]) -> list[tuple[Variant, str, int]]:
    """Alternate which variant goes first so machine drift does not favor one."""
    variants = (Variant.AUDIO, Variant.TEXT)
    jobs: list[tuple[Variant, str, int]] = []
    for seed in SEEDS:
        for index, subject_id in enumerate(subject_ids):
            order = variants if index % 2 == 0 else variants[::-1]
            jobs.extend((variant, subject_id, seed) for variant in order)
    return jobs


def run_options(
    reference_options: dict[str, Any], num_ctx: int, temperature: float | None
) -> dict[str, Any]:
    options = {**reference_options, "num_ctx": num_ctx}
    if temperature is not None:
        options["temperature"] = temperature
    options.pop("seed", None)
    options.pop("num_predict", None)
    return options


def command_run(args: argparse.Namespace) -> int:
    import httpx

    reference = json.loads(args.reference_request.read_text(encoding="utf-8"))
    options = run_options(
        reference["call"]["request"]["options"], args.num_ctx, args.temperature
    )
    wavs = WavDirectory(args.wavs)
    audio = subject_audio(wavs)
    calls_dir = args.out / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        args.out / "run_meta.json",
        {
            "model": args.model,
            "options": options,
            "hint": ERROR_HINT,
            "corpus_fingerprint": corpus_fingerprint(),
            "wav_set_hash": wavs.set_hash(),
        },
    )
    jobs = plan_jobs(list(audio))
    print(f"{len(jobs)} generations planned; model {args.model}", flush=True)
    ran = 0
    with httpx.Client(base_url=args.endpoint) as client:
        warmup = {
            "model": args.model,
            "messages": [{"role": "user", "content": WARMUP_PROMPT}],
            "stream": False,
            "think": False,
            "options": {**options, "num_predict": 32},
        }
        _ollama_post(client, "/api/chat", warmup)
        for variant, subject_id, seed in jobs:
            path = call_path(calls_dir, variant, subject_id, seed)
            if path.exists():
                continue
            source = whisper_transcript(args.whisper_calls, subject_id, seed)
            payload = build_payload(
                variant, source, audio[subject_id], options, seed, args.model
            )
            begin = time.perf_counter()
            response = _ollama_post(client, "/api/chat", payload)
            seconds = time.perf_counter() - begin
            text = response.get("message", {}).get("content", "")
            write_json(
                path,
                {
                    "variant": variant.value,
                    "subject_id": subject_id,
                    "seed": seed,
                    "whisper_transcript": source,
                    "response_text": text,
                    "seconds": seconds,
                    "done_reason": response.get("done_reason"),
                    "prompt_eval_count": response.get("prompt_eval_count"),
                    "eval_count": response.get("eval_count"),
                },
            )
            ran += 1
            print(
                f"{variant.value}-{subject_id}-s{seed}: {seconds:.1f}s | {text[:70]!r}",
                flush=True,
            )
        running = client.get("/api/ps", timeout=30.0).json().get("models", [])
        write_json(args.out / "placement.json", {"models": running})
        _ollama_post(
            client,
            "/api/generate",
            {"model": args.model, "prompt": "", "keep_alive": 0},
        )
    print(f"Done: ran {ran}.", flush=True)
    return 0


def load_calls(calls_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(calls_dir.glob("*.json"))
    ]


def _metrics_row(name: str, m: Metrics) -> str:
    cells = " / ".join(f"{f}/{t}" for f, t in m.fidelity.values())
    return (
        f"| {name} | {m.audio_failures} of {m.generations} | "
        f"{m.median_wer:.3f} | {m.overall_fidelity:.3f} | {cells} |"
    )


ByVariant = dict[Variant, dict[tuple[str, int], dict[str, Any]]]
CORPUS_IDS = {u.utterance_id for u in CORPUS}
TABLE_HEAD = (
    "| | audio failures | median WER | span fidelity | "
    "numeric / email / person / other |"
)


def _by_variant(calls: list[dict[str, Any]]) -> ByVariant:
    found: ByVariant = {v: {} for v in Variant}
    for call in calls:
        found[Variant(call["variant"])][(call["subject_id"], call["seed"])] = call
    return found


def _call_stats_lines(by_variant: ByVariant, num_ctx: int) -> list[str]:
    lines = []
    for variant in Variant:
        calls = by_variant[variant].values()
        done = [c for c in calls if c["subject_id"] in CORPUS_IDS]
        seconds = statistics.median(c["seconds"] for c in done)
        prompt = max(c["prompt_eval_count"] or 0 for c in done)
        cut = sum(1 for c in done if c["done_reason"] != "stop")
        lines.append(
            f"- {variant.value}: median {seconds:.2f} s, max prompt tokens "
            f"{prompt} of {num_ctx}, not stopped normally {cut}."
        )
    return lines


def _control_lines(by_variant: ByVariant) -> list[str]:
    lines = []
    for variant in Variant:
        for (subject_id, seed), call in sorted(by_variant[variant].items()):
            if subject_id in CORPUS_IDS:
                continue
            clean = control_is_clean(call["response_text"])
            lines.append(
                f"- {variant.value} {subject_id} s{seed}: "
                f"whisper {call['whisper_transcript']!r} -> {call['response_text']!r} "
                f"({'clean' if clean else 'invented text'})"
            )
    return lines


def _changed_lines(by_variant: ByVariant) -> list[str]:
    return [
        f"- {subject_id} s{seed}: whisper {call['whisper_transcript']!r} "
        f"-> {call['response_text']!r}"
        for (subject_id, seed), call in sorted(by_variant[Variant.AUDIO].items())
        if subject_id in CORPUS_IDS
        and call["response_text"].strip() != call["whisper_transcript"].strip()
    ]


def command_score(args: argparse.Namespace) -> int:
    meta_path = args.out / "run_meta.json"
    if not meta_path.exists():
        print("No run_meta.json: nothing to score.", file=sys.stderr)
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if WavDirectory(args.wavs).set_hash() != meta["wav_set_hash"]:
        print("The recordings differ from the ones the run used.", file=sys.stderr)
        return 2
    by_variant = _by_variant(load_calls(args.out / "calls"))
    keys = sorted(
        key
        for key in by_variant[Variant.AUDIO]
        if key[0] in CORPUS_IDS and key in by_variant[Variant.TEXT]
    )
    whisper_texts = [whisper_transcript(args.whisper_calls, s, n) for s, n in keys]
    texts = {v: [by_variant[v][key]["response_text"] for key in keys] for v in Variant}
    utterances = [utterance_by_id(s) for s, _ in keys]

    def score(transcripts: list[str]) -> Metrics:
        return score_transcripts(list(zip(utterances, transcripts, strict=True)))

    whisper = score(whisper_texts)
    audio, text = score(texts[Variant.AUDIO]), score(texts[Variant.TEXT])
    verdict = decide(whisper, audio, text)
    lines = [
        "# Spike v2.1.0-7: Gemma checks a Whisper transcript",
        "",
        f"Model `{meta['model']}`, `num_ctx` {meta['options']['num_ctx']}.",
        "",
        TABLE_HEAD,
        "|---|---|---|---|---|",
        _metrics_row("Whisper alone (spike 5)", whisper),
        _metrics_row("X: Whisper text + audio", audio),
        _metrics_row("Z: Whisper text only", text),
        "",
        f"**Verdict by the frozen rule: {verdict.value}.**",
        "",
    ]
    for variant in Variant:
        triples = list(zip(utterances, whisper_texts, texts[variant], strict=True))
        fixed, broken = paired_spans(triples)
        lines.append(
            f"- {variant.value} against Whisper alone: "
            f"spans fixed {fixed}, broken {broken}."
        )
    lines += _call_stats_lines(by_variant, meta["options"]["num_ctx"])
    lines += ["", "## Controls (reported only)", "", *_control_lines(by_variant)]
    lines += ["", "## Changed generations of X", "", *_changed_lines(by_variant)]
    report = "\n".join(lines) + "\n"
    (args.out / REPORT_NAME).write_text(report, encoding="utf-8")
    print(report)
    return 0


def _variant_stats(
    by_variant: ByVariant, variant: Variant, whisper_calls: Path
) -> dict[str, Any]:
    calls = by_variant[variant]
    keys = sorted(k for k in calls if k[0] in CORPUS_IDS)
    utterances = [utterance_by_id(s) for s, _ in keys]
    sources = [whisper_transcript(whisper_calls, s, n) for s, n in keys]
    outputs = [calls[k]["response_text"] for k in keys]
    metrics = score_transcripts(list(zip(utterances, outputs, strict=True)))
    fixed, broken = paired_spans(list(zip(utterances, sources, outputs, strict=True)))
    controls = [c for k, c in calls.items() if k[0] not in CORPUS_IDS]
    pairs = list(zip(sources, outputs, strict=True))
    return {
        "failures": metrics.audio_failures,
        "fidelity": metrics.overall_fidelity,
        "fixed": fixed,
        "broken": broken,
        "invented": sum(invented_address(s, o) for s, o in pairs),
        "rewritten": sum(rewrite_distance(s, o) > REWRITE_THRESHOLD for s, o in pairs),
        "controls_clean": sum(control_is_clean(c["response_text"]) for c in controls),
        "controls": len(controls),
    }


def command_compare(args: argparse.Namespace) -> int:
    head = (
        "| temperature | variant | failures | fidelity | fixed | broken | "
        "invented address | rewritten >0.3 | clean controls |"
    )
    lines = [head, "|---|---|---|---|---|---|---|---|---|"]
    for item in args.runs:
        label, _, directory = item.partition("=")
        by_variant = _by_variant(load_calls(Path(directory) / "calls"))
        for variant in Variant:
            st = _variant_stats(by_variant, variant, args.whisper_calls)
            lines.append(
                f"| {label} | {variant.value} | {st['failures']} | "
                f"{st['fidelity']:.3f} | {st['fixed']} | {st['broken']} | "
                f"{st['invented']} | {st['rewritten']} | "
                f"{st['controls_clean']}/{st['controls']} |"
            )
    for line in lines:
        print(line)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    commands = parser.add_subparsers(dest="command", required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("runs", nargs="+", help="label=output_dir")
    compare.add_argument("--whisper-calls", type=Path, default=DEFAULT_WHISPER_CALLS)
    for name in ("run", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--wavs", type=Path, required=True)
        sub.add_argument("--whisper-calls", type=Path, default=DEFAULT_WHISPER_CALLS)
        if name == "run":
            sub.add_argument("--endpoint", default="http://localhost:11434")
            sub.add_argument("--model", default=DEFAULT_MODEL)
            sub.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX)
            sub.add_argument("--temperature", type=float, default=None)
            sub.add_argument(
                "--reference-request", type=Path, default=DEFAULT_REFERENCE_REQUEST
            )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "compare":
            return command_compare(args)
        if args.command == "score":
            return command_score(args)
        return command_run(args)
    except WavDirectoryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
