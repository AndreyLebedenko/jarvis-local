#!/usr/bin/env python3
"""Human-run block R of tasks/spike-v2.1.0-1-combined-transcribe-sanitize.md.

Text-only restoration of original values into an external answer by the local
model. Needs the live Ollama endpoint, so the human runs it. Subcommands:

  python -m manual.manual_check_personal_proxy_restoration --out DIR run
  python -m manual.manual_check_personal_proxy_restoration --out DIR review
  python -m manual.manual_check_personal_proxy_restoration --out DIR score

`run` calls the model, `review` writes the blind sheet you fill in, `score`
applies the card's rule. The exact steps are in
tasks/spike-v2.1.0-1-handoff.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from jarvis.core.config import GenerationOptions
from manual.manual_check_personal_proxy_spike import (
    DEFAULT_CONFIG,
    OllamaModelCaller,
    fetch_provenance,
    make_environment,
)
from manual.personal_proxy.records import CallRecord, CallStage
from manual.personal_proxy.restoration import (
    ITEMS,
    SEEDS,
    aggregate_restoration,
    build_review_pairs,
    load_answers,
    render_answer_template,
    render_review_sheet,
    restoration_decision,
    restoration_messages,
    score_case_review,
    score_output,
)
from manual.personal_proxy.runner import NUM_PREDICT, PlannedRequest

DEFAULT_OUT = Path("manual_check_personal_proxy_restoration_out")
CALLS_DIR = "calls"
SHEET_NAME = "review-sheet.md"
ANSWERS_NAME = "review-answers.toml"
REPORT_NAME = "report.md"
REVIEW_SEED = SEEDS[0]


def call_path(out: Path, item_id: str, seed: int) -> Path:
    return out / CALLS_DIR / f"{item_id}-s{seed}.json"


def load_call(path: Path) -> CallRecord:
    document = json.loads(path.read_text(encoding="utf-8"))
    return CallRecord(**{**document, "stage": CallStage(document["stage"])})


async def command_run(args: argparse.Namespace) -> int:
    settings, client, backend, options, _ = make_environment(args)
    provenance = await fetch_provenance(client, settings.backend.model)
    (args.out / CALLS_DIR).mkdir(parents=True, exist_ok=True)
    (args.out / "run_meta.json").write_text(
        json.dumps({"model": settings.backend.model, **provenance}, indent=2),
        encoding="utf-8",
    )
    caller = OllamaModelCaller(backend, client)
    for seed in SEEDS:
        for item in ITEMS:
            path = call_path(args.out, item.item_id, seed)
            if path.exists():
                continue
            request = PlannedRequest(
                CallStage.COMBINED,
                tuple(restoration_messages(item)),
                None,
                GenerationOptions(
                    **{**options.__dict__, "seed": seed, "num_predict": NUM_PREDICT}
                ),
            )
            record = await caller(request)
            path.write_text(
                json.dumps(
                    {**asdict(record), "stage": record.stage.value},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"{item.item_id} s{seed}: {record.response_text.strip()}", flush=True)
    await client.aclose()
    return 0


def _model_outputs(out: Path, seed: int) -> dict[str, str]:
    return {
        item.item_id: load_call(
            call_path(out, item.item_id, seed)
        ).response_text.strip()
        for item in ITEMS
    }


def command_review(args: argparse.Namespace) -> int:
    pairs = build_review_pairs()
    sheet = render_review_sheet(pairs, _model_outputs(args.out, REVIEW_SEED))
    (args.out / SHEET_NAME).write_text(sheet, encoding="utf-8")
    answers = args.out / ANSWERS_NAME
    if not answers.exists():
        answers.write_text(render_answer_template(pairs), encoding="utf-8")
    print(f"Fill in {answers} using {args.out / SHEET_NAME}, then run score.")
    return 0


def command_score(args: argparse.Namespace) -> int:
    scores = [
        score_output(
            item,
            seed,
            load_call(call_path(args.out, item.item_id, seed)).response_text,
        )
        for seed in SEEDS
        for item in ITEMS
    ]
    metrics = aggregate_restoration(scores)
    review_scores = {s.item_id: s.valid for s in scores if s.seed == REVIEW_SEED}
    answers = load_answers(args.out / ANSWERS_NAME)
    if any(not v for sides in answers.values() for v in sides.values()):
        print("The answers file still has empty marks; fill every x and y.")
        return 2
    case = score_case_review(build_review_pairs(), answers, review_scores)
    keep, reasons = restoration_decision(metrics, case)
    lines = [
        "# Block R: restoration through the local model",
        "",
        f"- generations: {metrics.generations}",
        f"- validation pass rate: {metrics.validation_pass_rate:.3f}",
        f"- alteration rate: {metrics.alteration_rate:.3f}",
        f"- fallback wrong on {case.fallback_wrong} items; model right on "
        f"{case.model_right_where_fallback_wrong} of them",
        "- decision: "
        + ("KEEP restoration through the model" if keep else "NOT SUPPORTED"),
    ]
    lines += [f"  - {reason}" for reason in reasons]
    report = "\n".join(lines) + "\n"
    (args.out / REPORT_NAME).write_text(report, encoding="utf-8")
    print(report)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "review", "score"):
        commands.add_parser(name)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "run":
        return asyncio.run(command_run(args))
    if args.command == "review":
        return command_review(args)
    return command_score(args)


if __name__ == "__main__":
    sys.exit(main())
