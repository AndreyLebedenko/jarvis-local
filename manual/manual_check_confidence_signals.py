#!/usr/bin/env python3
"""Harness of tasks/spike-v2.1.0-8-confidence-signals.md.

  .venv-stt-whisper\\Scripts\\python.exe -m manual.manual_check_confidence_signals
      --out DIR words --wavs WAVS
  python -m manual.manual_check_confidence_signals --out DIR run --wavs WAVS
  python -m manual.manual_check_confidence_signals --out DIR score --wavs WAVS

`--out` goes before the subcommand. `words` needs the Whisper environment; `run`
talks to the live local Ollama endpoint; `score` is offline.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from manual.manual_check_stt_engines import (
    DEFAULT_REFERENCE_REQUEST,
    _ollama_post,
    decode,
    write_json,
)
from manual.manual_check_stt_verification import (
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    DEFAULT_WHISPER_CALLS,
    WARMUP_PROMPT,
    run_options,
    subject_audio,
    whisper_transcript,
)
from manual.personal_proxy.audio import WavDirectory, WavDirectoryError
from manual.personal_proxy.confidence import (
    WEAK_WORD_PROBABILITY,
    JudgeResult,
    LabelRule,
    build_judge_payload,
    build_sample_payload,
    parse_judge,
    weak_word_marks,
)
from manual.personal_proxy.confidence_report import (
    BASE_KEY,
    SAMPLE_KEYS,
    Signals,
    compute_signals,
    evaluate,
    render_report,
)
from manual.personal_proxy.corpus import (
    CORPUS,
    SEEDS,
    corpus_fingerprint,
    utterance_by_id,
)
from manual.personal_proxy.verification import (
    ERROR_HINT,
    paired_spans,
    score_transcripts,
)

DEFAULT_OUT = Path("manual_check_confidence_out")
REPORT_NAME = "report.md"
CORPUS_IDS = {u.utterance_id for u in CORPUS}


def words_path(out: Path, subject_id: str) -> Path:
    return out / "words" / f"{subject_id}.json"


def sample_name(subject_id: str, key: tuple[float, int]) -> str:
    return f"{subject_id}-t{key[0]}-s{key[1]}.json"


def read_words(out: Path, subject_id: str) -> dict[str, Any]:
    return json.loads(words_path(out, subject_id).read_text(encoding="utf-8"))


def word_pairs(document: dict[str, Any]) -> list[tuple[str, float]]:
    return [(w["word"], w["probability"]) for w in document["words"]]


def same_text(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def command_words(args: argparse.Namespace) -> int:
    from manual.personal_proxy.stt_engines import (
        WhisperEngine,
        transcribe_with_confidence,
    )

    wavs = WavDirectory(args.wavs)
    audio = subject_audio(wavs)
    engine = WhisperEngine("ru", "cuda", "float16")
    engine.load()
    (args.out / "words").mkdir(parents=True, exist_ok=True)
    mismatches = []
    for subject_id, data in audio.items():
        samples, _ = decode(data)
        detailed = transcribe_with_confidence(engine, samples)
        expected = whisper_transcript(args.whisper_calls, subject_id, SEEDS[0])
        if not same_text(detailed["text"], expected):
            mismatches.append((subject_id, expected, detailed["text"]))
        write_json(words_path(args.out, subject_id), detailed)
    for subject_id, expected, got in mismatches:
        print(f"MISMATCH {subject_id}: spike 5 {expected!r} now {got!r}")
    print(f"{len(audio)} recordings; text mismatches: {len(mismatches)}")
    return 2 if mismatches else 0


def _call(client: Any, payload: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
    begin = time.perf_counter()
    response = _ollama_post(client, "/api/chat", payload)
    seconds = time.perf_counter() - begin
    return response.get("message", {}).get("content", ""), seconds, response


def command_run(args: argparse.Namespace) -> int:
    import httpx

    reference = json.loads(args.reference_request.read_text(encoding="utf-8"))
    base_options = reference["call"]["request"]["options"]
    wavs = WavDirectory(args.wavs)
    audio = subject_audio(wavs)
    for name in ("samples", "judge"):
        (args.out / name).mkdir(parents=True, exist_ok=True)
    write_json(
        args.out / "run_meta.json",
        {
            "model": args.model,
            "base_options": run_options(base_options, args.num_ctx, None),
            "weak_word_probability": WEAK_WORD_PROBABILITY,
            "hint": ERROR_HINT,
            "corpus_fingerprint": corpus_fingerprint(),
            "wav_set_hash": wavs.set_hash(),
        },
    )
    ran = 0
    with httpx.Client(base_url=args.endpoint) as client:
        warmup = {
            "model": args.model,
            "messages": [{"role": "user", "content": WARMUP_PROMPT}],
            "stream": False,
            "think": False,
            "options": {
                **run_options(base_options, args.num_ctx, None),
                "num_predict": 32,
            },
        }
        _ollama_post(client, "/api/chat", warmup)
        for subject_id, data in audio.items():
            document = read_words(args.out, subject_id)
            marked = weak_word_marks(word_pairs(document))
            source = whisper_transcript(args.whisper_calls, subject_id, SEEDS[0])
            for key in SAMPLE_KEYS:
                temperature, seed = key
                options = run_options(base_options, args.num_ctx, temperature)
                sample_file = args.out / "samples" / sample_name(subject_id, key)
                judge_file = args.out / "judge" / sample_name(subject_id, key)
                if sample_file.exists() and judge_file.exists():
                    continue
                payload = build_sample_payload(marked, data, options, seed, args.model)
                text, seconds, response = _call(client, payload)
                write_json(
                    sample_file,
                    {
                        "subject_id": subject_id,
                        "temperature": temperature,
                        "seed": seed,
                        "marked_input": marked,
                        "response_text": text,
                        "seconds": seconds,
                        "prompt_eval_count": response.get("prompt_eval_count"),
                        "done_reason": response.get("done_reason"),
                    },
                )
                judge = build_judge_payload(source, text, data, options, args.model)
                answer, seconds, response = _call(client, judge)
                write_json(
                    judge_file,
                    {
                        "subject_id": subject_id,
                        "temperature": temperature,
                        "seed": seed,
                        "response_text": answer,
                        "seconds": seconds,
                        "prompt_eval_count": response.get("prompt_eval_count"),
                    },
                )
                ran += 1
                print(
                    f"{subject_id} t{temperature} s{seed}: "
                    f"{text[:50]!r} | {answer[:60]!r}",
                    flush=True,
                )
        _ollama_post(
            client,
            "/api/generate",
            {"model": args.model, "prompt": "", "keep_alive": 0},
        )
    print(f"Done: ran {ran}.", flush=True)
    return 0


def _load_samples(out: Path, subject_id: str) -> dict[tuple[float, int], str]:
    found = {}
    for key in SAMPLE_KEYS:
        path = out / "samples" / sample_name(subject_id, key)
        found[key] = json.loads(path.read_text(encoding="utf-8"))["response_text"]
    return found


def _load_judges(
    out: Path, subject_id: str
) -> dict[tuple[float, int], JudgeResult | None]:
    found = {}
    for key in SAMPLE_KEYS:
        path = out / "judge" / sample_name(subject_id, key)
        found[key] = parse_judge(
            json.loads(path.read_text(encoding="utf-8"))["response_text"]
        )
    return found


def _signals_for(subject_id: str, args: argparse.Namespace) -> tuple[Signals, int]:
    document = read_words(args.out, subject_id)
    judges = _load_judges(args.out, subject_id)
    utterance = utterance_by_id(subject_id) if subject_id in CORPUS_IDS else None
    signals = compute_signals(
        subject_id,
        utterance,
        whisper_transcript(args.whisper_calls, subject_id, SEEDS[0]),
        word_pairs(document),
        document["segments"],
        _load_samples(args.out, subject_id),
        judges,
        LabelRule(args.label_rule),
    )
    return signals, sum(1 for j in judges.values() if j is None)


def _marks_effect(args: argparse.Namespace) -> list[str]:
    triples = []
    for subject_id in sorted(CORPUS_IDS):
        source = whisper_transcript(args.whisper_calls, subject_id, SEEDS[0])
        samples = _load_samples(args.out, subject_id)
        for seed in SEEDS:
            triples.append(
                (utterance_by_id(subject_id), source, samples[(BASE_KEY[0], seed)])
            )
    metrics = score_transcripts([(u, o) for u, _, o in triples])
    fixed, broken = paired_spans(triples)
    return [
        f"audio failures {metrics.audio_failures} of {metrics.generations} "
        "(spike 7 X at 0.618: 5 of 88; Whisper alone: 4 of 88)",
        f"span fidelity {metrics.overall_fidelity:.3f} "
        "(spike 7 X: 0.896; Whisper alone: 0.854)",
        f"spans fixed {fixed}, broken {broken} (spike 7 X: 4 fixed, 0 broken)",
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
    recordings, controls, unparsed = [], [], 0
    for subject_id in sorted(read_ids(args.out)):
        signals, missing = _signals_for(subject_id, args)
        unparsed += missing
        (recordings if subject_id in CORPUS_IDS else controls).append(signals)
    report = render_report(
        recordings,
        controls,
        evaluate(recordings, controls),
        unparsed,
        _marks_effect(args),
    )
    name = (
        REPORT_NAME if args.label_rule == "frozen" else f"report-{args.label_rule}.md"
    )
    (args.out / name).write_text(report, encoding="utf-8")
    print(report)
    return 0


def read_ids(out: Path) -> list[str]:
    return [p.stem for p in (out / "words").glob("*.json")]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("words", "run", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--wavs", type=Path, required=True)
        sub.add_argument("--whisper-calls", type=Path, default=DEFAULT_WHISPER_CALLS)
        if name == "score":
            sub.add_argument(
                "--label-rule", choices=[r.value for r in LabelRule], default="frozen"
            )
        if name == "run":
            sub.add_argument("--endpoint", default="http://localhost:11434")
            sub.add_argument("--model", default=DEFAULT_MODEL)
            sub.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX)
            sub.add_argument(
                "--reference-request", type=Path, default=DEFAULT_REFERENCE_REQUEST
            )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    handlers = {"words": command_words, "run": command_run, "score": command_score}
    try:
        return handlers[args.command](args)
    except WavDirectoryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
