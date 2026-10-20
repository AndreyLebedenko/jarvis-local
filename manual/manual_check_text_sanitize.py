#!/usr/bin/env python3
"""Harness of tasks/done/spike-v2.1.0-11-text-sanitize.md.

  python -m manual.manual_check_text_sanitize run --v2-out DIR
  python -m manual.manual_check_text_sanitize score --v2-out DIR

Reads the recorded Whisper text and checked samples of both corpora (spikes
8-9), runs the text-only sanitize pass of spike 1 on them against the live local
Ollama endpoint (`run`), and scores the stored calls offline (`score`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manual.manual_check_confidence_signals import (
    DEFAULT_OUT,
    CorpusSetup,
    _load_samples,
    engine_text,
    setup_for,
)
from manual.manual_check_stt_engines import (
    DEFAULT_REFERENCE_REQUEST,
    _ollama_post,
    write_json,
)
from manual.manual_check_stt_verification import (
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    WARMUP_PROMPT,
    run_options,
)
from manual.personal_proxy.confidence_report import BASE_KEY
from manual.personal_proxy.corpus import SEEDS, Utterance, topics_text
from manual.personal_proxy.corpus_v2 import voice_of
from manual.personal_proxy.prompts import (
    TEXT_SCHEMA,
    prompts_fingerprint,
    sanitize_text_messages,
)
from manual.personal_proxy.runner import NUM_PREDICT
from manual.personal_proxy.sanitize_scoring import (
    SanitizeScore,
    Totals,
    aggregate,
    decide,
    parse_failure,
    score_call,
)

DEFAULT_SANITIZE_OUT = Path("manual_check_text_sanitize_out")
ARMS = ("W", "G")
PRIMARY_ARM = "G"
REPORT_NAME = "report.md"


@dataclass(frozen=True)
class Subject:
    utterance: Utterance
    corpus: str
    out: Path

    def input_text(self, arm: str) -> str:
        subject_id = self.utterance.utterance_id
        if arm == "W":
            return engine_text(self.out, subject_id).strip()
        return _load_samples(self.out, subject_id)[BASE_KEY].strip()


def subjects_of(outs: dict[str, Path]) -> list[Subject]:
    found = []
    for corpus, out in outs.items():
        setup: CorpusSetup = setup_for(argparse.Namespace(corpus=corpus))
        found += [Subject(u, corpus, out) for u in setup.utterances]
    return found


def call_path(out: Path, arm: str, subject_id: str, seed: int) -> Path:
    return out / "calls" / arm / f"{subject_id}-s{seed}.json"


def sanitize_payload(
    input_text: str, options: dict[str, Any], seed: int, model: str
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": sanitize_text_messages(input_text, topics_text()),
        "stream": False,
        "think": False,
        "format": TEXT_SCHEMA,
        "options": {**options, "seed": seed, "num_predict": NUM_PREDICT},
    }


def command_run(args: argparse.Namespace) -> int:
    import httpx

    reference = json.loads(args.reference_request.read_text(encoding="utf-8"))
    options = run_options(reference["call"]["request"]["options"], args.num_ctx, None)
    subjects = subjects_of({"v1": args.v1_out, "v2": args.v2_out})
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(
        args.out / "run_meta.json",
        {
            "model": args.model,
            "options": options,
            "num_predict": NUM_PREDICT,
            "seeds": list(SEEDS),
            "prompts_fingerprint": prompts_fingerprint(),
            "arms": list(ARMS),
        },
    )
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
        for seed in SEEDS:
            for subject in subjects:
                for arm in ARMS:
                    ran += _run_one(client, args, options, subject, arm, seed)
        _ollama_post(
            client,
            "/api/generate",
            {"model": args.model, "prompt": "", "keep_alive": 0},
        )
    print(f"Done: ran {ran}.", flush=True)
    return 0


def _run_one(
    client: Any,
    args: argparse.Namespace,
    options: dict[str, Any],
    subject: Subject,
    arm: str,
    seed: int,
) -> int:
    subject_id = subject.utterance.utterance_id
    path = call_path(args.out, arm, subject_id, seed)
    if path.exists():
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    reset = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": "0"},
            {"role": "user", "content": "0"},
        ],
        "stream": False,
        "think": False,
        "options": {"num_predict": 1},
    }
    _ollama_post(client, "/api/chat", reset)
    input_text = subject.input_text(arm)
    begin = time.perf_counter()
    response = _ollama_post(
        client, "/api/chat", sanitize_payload(input_text, options, seed, args.model)
    )
    seconds = time.perf_counter() - begin
    write_json(
        path,
        {
            "subject_id": subject_id,
            "corpus": subject.corpus,
            "arm": arm,
            "seed": seed,
            "input_text": input_text,
            "response_text": response.get("message", {}).get("content", ""),
            "done_reason": response.get("done_reason"),
            "seconds": seconds,
            "prompt_eval_count": response.get("prompt_eval_count"),
        },
    )
    print(f"{arm} {subject_id} s{seed}: {seconds:.1f}s", flush=True)
    return 1


def load_scores(
    out: Path, subjects: list[Subject]
) -> tuple[list[SanitizeScore], dict[str, int]]:
    scores = []
    failures: Counter[str] = Counter()
    for subject in subjects:
        subject_id = subject.utterance.utterance_id
        for arm in ARMS:
            for seed in SEEDS:
                document = json.loads(
                    call_path(out, arm, subject_id, seed).read_text(encoding="utf-8")
                )
                failure = parse_failure(
                    document["response_text"], document["done_reason"]
                )
                if failure:
                    failures[failure] += 1
                scores.append(
                    score_call(
                        subject.utterance,
                        arm,
                        seed,
                        document["input_text"],
                        document["response_text"],
                        document["done_reason"],
                        document["seconds"],
                    )
                )
    return scores, dict(failures)


def _row(label: str, t: Totals) -> str:
    preservation = f"{t.mean_preservation:.3f}" if t.mean_preservation else "-"
    return (
        f"| {label} | {t.generations} | {t.validity:.3f} | "
        f"{t.spans_leaked}/{t.spans_recognisable} = {t.leak_rate:.3f} | "
        f"{t.mapping_errors}/{t.mapping_checked} = {t.mapping_error_rate:.3f} | "
        f"{preservation} | {t.false_refusals}/{t.send_expected} | "
        f"{t.missed_refusals} | {t.spans_lost} |"
    )


HEADER = (
    "| group | generations | validity | leak | mapping error | preservation | "
    "false refusals | missed refusals | lost spans |\n"
    "|---|---|---|---|---|---|---|---|---|"
)


def _groups(
    scores: list[SanitizeScore], subjects: list[Subject]
) -> dict[str, list[SanitizeScore]]:
    corpus_of = {s.utterance.utterance_id: s.corpus for s in subjects}
    groups: dict[str, list[SanitizeScore]] = {}
    for arm in ARMS:
        mine = [s for s in scores if s.arm == arm]
        groups[f"{arm} all"] = mine
        for corpus in ("v1", "v2"):
            groups[f"{arm} {corpus}"] = [
                s for s in mine if corpus_of[s.subject_id] == corpus
            ]
        for voice in ("owner", "eugene", "baya"):
            groups[f"{arm} v2 {voice}"] = [
                s
                for s in mine
                if corpus_of[s.subject_id] == "v2" and voice_of(s.subject_id) == voice
            ]
    return groups


def render(
    scores: list[SanitizeScore],
    subjects: list[Subject],
    failures: dict[str, int],
) -> str:
    by_id = {s.utterance.utterance_id: s.utterance for s in subjects}
    lines = ["# Spike v2.1.0-11: text-only sanitize pass on INT4", ""]
    primary = aggregate([s for s in scores if s.arm == PRIMARY_ARM])
    decision = decide(primary)
    lines += [f"Decision on arm {PRIMARY_ARM}: **{decision.verdict}**", ""]
    lines += ["| criterion | value | limit | passed |", "|---|---|---|---|"]
    for c in decision.criteria:
        lines.append(f"| {c.name} | {c.value:.3f} | {c.limit} | {c.passed} |")
    lines += ["", HEADER]
    for label, group in _groups(scores, subjects).items():
        if group:
            lines.append(_row(label, aggregate(group)))
    lines += ["", f"Parse failures: {failures or 'none'}", ""]
    lines += _leak_details(scores, by_id)
    lines += _timing(scores)
    return "\n".join(lines) + "\n"


def _leak_details(
    scores: list[SanitizeScore], by_id: dict[str, Utterance]
) -> list[str]:
    lines = []
    for arm in ARMS:
        leaks = [s for s in scores if s.arm == arm and s.leaked]
        lines += [f"## Leaks, arm {arm}", ""]
        if not leaks:
            lines += ["none", ""]
        for s in leaks:
            surface = {sp.span_id: sp for sp in by_id[s.subject_id].spans}
            for span_id, how in zip(s.leaked, s.leak_renderings, strict=False):
                span = surface[span_id]
                lines.append(
                    f"- {s.subject_id} s{s.seed} {span_id} "
                    f"({span.type.value}/{span.cls.value}, {how}): {span.surface!r}"
                )
        lost = [s for s in scores if s.arm == arm and s.lost and s.seed == SEEDS[0]]
        lines += ["", f"Lost spans (not in the input), arm {arm}:"]
        lines += [f"- {s.subject_id}: {', '.join(s.lost)}" for s in lost] or ["none"]
        lines.append("")
    return lines


def _timing(scores: list[SanitizeScore]) -> list[str]:
    lines = ["## Time per call", ""]
    for arm in ARMS:
        totals = aggregate([s for s in scores if s.arm == arm])
        lines.append(
            f"- {arm}: median {totals.median_seconds:.1f} s, "
            f"p90 {totals.p90_seconds:.1f} s"
        )
    return [*lines, ""]


def command_score(args: argparse.Namespace) -> int:
    subjects = subjects_of({"v1": args.v1_out, "v2": args.v2_out})
    scores, failures = load_scores(args.out, subjects)
    report = render(scores, subjects, failures)
    (args.out / REPORT_NAME).write_text(report, encoding="utf-8")
    print(report)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--out", type=Path, default=DEFAULT_SANITIZE_OUT)
        sub.add_argument("--v1-out", type=Path, default=DEFAULT_OUT)
        sub.add_argument("--v2-out", type=Path, required=True)
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
    handlers = {"run": command_run, "score": command_score}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
