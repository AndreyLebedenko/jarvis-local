#!/usr/bin/env python3
"""Harness of tasks/spike-v2.1.0-8-confidence-signals.md.

  .venv-stt-whisper\\Scripts\\python.exe -m manual.manual_check_confidence_signals
      --out DIR words --wavs WAVS
  python -m manual.manual_check_confidence_signals --out DIR run --wavs WAVS
  python -m manual.manual_check_confidence_signals --out DIR score --wavs WAVS

`--corpus v2` (spike v2.1.0-9) selects the second corpus
(tasks/spike-v2.1.0-9-confidence-fresh-corpus.md). `--corpus` and `--out` go
before the subcommand. `words` needs the Whisper environment; `run`
talks to the live local Ollama endpoint; `score` is offline.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
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
    render_hypothesis,
    render_report,
)
from manual.personal_proxy.corpus import (
    CORPUS,
    SEEDS,
    Utterance,
    corpus_fingerprint,
)
from manual.personal_proxy.corpus_v2 import (
    CORPUS_V2,
    corpus_v2_fingerprint,
    voice_of,
)
from manual.personal_proxy.verification import (
    ERROR_HINT,
    paired_spans,
    score_transcripts,
)

DEFAULT_OUT = Path("manual_check_confidence_out")
REPORT_NAME = "report.md"


@dataclass(frozen=True)
class CorpusSetup:
    utterances: tuple[Utterance, ...]
    fingerprint: str | None
    first: bool

    def ids(self) -> set[str]:
        return {u.utterance_id for u in self.utterances}

    def lookup(self, subject_id: str) -> Utterance | None:
        for u in self.utterances:
            if u.utterance_id == subject_id:
                return u
        return None

    def directory(self, wavs: Path) -> WavDirectory:
        return WavDirectory(wavs, self.utterances, self.fingerprint)

    def audio(self, wavs: Path) -> dict[str, bytes]:
        directory = self.directory(wavs)
        if self.first:
            return subject_audio(directory)
        return {
            u.utterance_id: directory.audio_for(u.utterance_id) for u in self.utterances
        }


def setup_for(args: argparse.Namespace) -> CorpusSetup:
    if args.corpus == "v2":
        return CorpusSetup(CORPUS_V2, corpus_v2_fingerprint(), False)
    return CorpusSetup(CORPUS, None, True)


def engine_text(out: Path, subject_id: str) -> str:
    return read_words(out, subject_id)["text"]


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

    setup = setup_for(args)
    audio = setup.audio(args.wavs)
    engine = WhisperEngine("ru", "cuda", "float16")
    engine.load()
    (args.out / "words").mkdir(parents=True, exist_ok=True)
    mismatches = []
    for subject_id, data in audio.items():
        samples, _ = decode(data)
        detailed = transcribe_with_confidence(engine, samples)
        expected = (
            whisper_transcript(args.whisper_calls, subject_id, SEEDS[0])
            if setup.first
            else detailed["text"]
        )
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
    setup = setup_for(args)
    audio = setup.audio(args.wavs)
    for name in ("samples", "judge"):
        (args.out / name).mkdir(parents=True, exist_ok=True)
    write_json(
        args.out / "run_meta.json",
        {
            "model": args.model,
            "base_options": run_options(base_options, args.num_ctx, None),
            "weak_word_probability": WEAK_WORD_PROBABILITY,
            "hint": ERROR_HINT,
            "corpus_fingerprint": setup.fingerprint or corpus_fingerprint(),
            "wav_set_hash": setup.directory(args.wavs).set_hash(),
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
            source = document["text"]
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


def _signals_for(
    subject_id: str, args: argparse.Namespace, setup: CorpusSetup
) -> tuple[Signals, int]:
    document = read_words(args.out, subject_id)
    judges = _load_judges(args.out, subject_id)
    signals = compute_signals(
        subject_id,
        setup.lookup(subject_id),
        document["text"],
        word_pairs(document),
        document["segments"],
        _load_samples(args.out, subject_id),
        judges,
        LabelRule(args.label_rule),
    )
    return signals, sum(1 for j in judges.values() if j is None)


def _marks_effect(args: argparse.Namespace, setup: CorpusSetup) -> list[str]:
    triples = []
    for utterance in setup.utterances:
        source = engine_text(args.out, utterance.utterance_id)
        samples = _load_samples(args.out, utterance.utterance_id)
        for seed in SEEDS:
            triples.append((utterance, source, samples[(BASE_KEY[0], seed)]))
    metrics = score_transcripts([(u, o) for u, _, o in triples])
    fixed, broken = paired_spans(triples)
    whisper_alone = score_transcripts([(u, s) for u, s, _ in triples])
    return [
        f"audio failures {metrics.audio_failures} of {metrics.generations} "
        f"(Whisper alone: {whisper_alone.audio_failures})",
        f"span fidelity {metrics.overall_fidelity:.3f} "
        f"(Whisper alone: {whisper_alone.overall_fidelity:.3f})",
        f"spans fixed {fixed}, broken {broken}",
    ]


def _voice_groups(recordings: list[Signals]) -> dict[str, list[Signals]]:
    groups: dict[str, list[Signals]] = {}
    for r in recordings:
        groups.setdefault(f"voice {voice_of(r.subject_id)}", []).append(r)
    return groups


def command_score(args: argparse.Namespace) -> int:
    meta_path = args.out / "run_meta.json"
    if not meta_path.exists():
        print("No run_meta.json: nothing to score.", file=sys.stderr)
        return 2
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    setup = setup_for(args)
    if setup.directory(args.wavs).set_hash() != meta["wav_set_hash"]:
        print("The recordings differ from the ones the run used.", file=sys.stderr)
        return 2
    corpus_ids = setup.ids()
    recordings, controls, unparsed = [], [], 0
    for subject_id in sorted(read_ids(args.out)):
        signals, missing = _signals_for(subject_id, args, setup)
        unparsed += missing
        (recordings if subject_id in corpus_ids else controls).append(signals)
    groups = None if setup.first else _voice_groups(recordings)
    report = render_report(
        recordings,
        controls,
        evaluate(recordings, controls),
        unparsed,
        _marks_effect(args, setup),
    )
    report += "\n" + "\n".join(render_hypothesis(recordings, groups)) + "\n"
    name = (
        REPORT_NAME if args.label_rule == "frozen" else f"report-{args.label_rule}.md"
    )
    (args.out / name).write_text(report, encoding="utf-8")
    print(report)
    return 0


def command_pooled(args: argparse.Namespace) -> int:
    recordings: list[Signals] = []
    by_corpus: dict[str, list[Signals]] = {"corpus v1": [], "corpus v2": []}
    for corpus, out in (("v1", args.v1_out), ("v2", args.v2_out)):
        scoped = argparse.Namespace(corpus=corpus, out=out, label_rule=args.label_rule)
        setup = setup_for(scoped)
        for subject_id in sorted(setup.ids()):
            signals, _ = _signals_for(subject_id, scoped, setup)
            recordings.append(signals)
            by_corpus[f"corpus {corpus}"].append(signals)
    report = render_report(recordings, [], evaluate(recordings, []), 0, [])
    report += "\n" + "\n".join(render_hypothesis(recordings, by_corpus)) + "\n"
    target = args.out / f"pooled-{args.label_rule}.md"
    target.write_text(report, encoding="utf-8")
    print(report)
    return 0


def read_ids(out: Path) -> list[str]:
    return [p.stem for p in (out / "words").glob("*.json")]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=("v1", "v2"), default="v1")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    commands = parser.add_subparsers(dest="command", required=True)
    pooled = commands.add_parser("pooled")
    pooled.add_argument("--v1-out", type=Path, default=DEFAULT_OUT)
    pooled.add_argument("--v2-out", type=Path, required=True)
    pooled.add_argument(
        "--label-rule", choices=[r.value for r in LabelRule], default="frozen"
    )
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
    handlers = {
        "words": command_words,
        "run": command_run,
        "score": command_score,
        "pooled": command_pooled,
    }
    try:
        return handlers[args.command](args)
    except WavDirectoryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
