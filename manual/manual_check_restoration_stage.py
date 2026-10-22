#!/usr/bin/env python3
"""Human-run check of the restoration stage (task v2.1.0-7).

Handoff with every step: manual/restoration-stage-handoff.md.

  python -m manual.manual_check_restoration_stage --out DIR run
  python -m manual.manual_check_restoration_stage --out DIR score

`run` sends the 30 items of block R through the stage's own function
(`restore_answer`) against the live local Ollama endpoint, twice per item (the
two seeds of the spike), prints the result per generation, measures the
automatic part of the card's rule, and writes the blind review sheet of the
spike. `score` applies the whole rule once the answers file is filled in.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import httpx

from jarvis.core.config import GenerationOptions, PersonalProxySettings, load_settings
from jarvis.personal_proxy.check_backend import (
    BackendReplyError,
    ChatRequest,
    CheckBackend,
)
from jarvis.personal_proxy.ollama_check_backend import OllamaCheckBackend
from jarvis.personal_proxy.placeholders import known_entries
from jarvis.personal_proxy.restoration import restore_answer
from jarvis.personal_proxy.restoration_result import RestorationMethod
from jarvis.personal_proxy.restoration_validation import (
    RestorationRule,
    failed_rules,
)
from manual.manual_check_transcript_check import ollama_preflight
from manual.personal_proxy.restoration import (
    ITEMS,
    MAX_ALTERATION_RATE,
    MIN_FALLBACK_BEATEN_SHARE,
    MIN_VALIDATION_PASS_RATE,
    SEEDS,
    CaseResult,
    RestorationItem,
    RestorationMetrics,
    build_review_pairs,
    load_answers,
    render_answer_template,
    render_review_sheet,
    restoration_decision,
)

DEFAULT_OUT = Path("manual_check_restoration_stage_out")
RESULTS_NAME = "results.json"
SHEET_NAME = "review-sheet.md"
ANSWERS_NAME = "review-answers.toml"
REPORT_NAME = "report.md"
REVIEW_SEED = SEEDS[0]
PLANNED_GENERATIONS = len(SEEDS) * len(ITEMS)
NO_REPLY_TEXT = "(no usable model reply)"
NO_USABLE_REPLY = "no_usable_reply"
CONNECT_TIMEOUT_SECONDS = 10.0
PREFLIGHT_TIMEOUT_SECONDS = 5.0
SPIKE_FLASH_ATTENTION = True
SPIKE_KV_CACHE_TYPE = "q8_0"
BLANK_LINE = "\n\n"
MAX_UNUSABLE_SHARE = 0.10
INVALID_EXIT_CODE = 3
FOUR_BIT_LEVELS = ("Q4", "INT4")
REVIEW_INSTRUCTIONS = (
    "For each item mark X and Y in the answers file with one of three marks "
    "(owner scale of 2026-10-22; the spike used only ok and bad):\n"
    "- ok: fully right, the case and form of the inserted values are right.\n"
    "- mid (or an empty string): the meaning comes through, but it is worse "
    "than ok; not critical.\n"
    "- bad: the case is critically wrong.\n"
    "If both X and Y of an item are middle, write mid explicitly: both empty "
    "is treated as unfilled.\n"
    "Also mark a sentence bad if, compared with the plain sentence, it has a "
    "changed digit, a duplicated or missing inserted value, or added markdown "
    "or quote marks."
)
ANSWERS_HEADER = (
    "# Fill x and y with ok, mid or bad. An empty string means mid; if both "
    "x and y of an item are mid, write mid explicitly."
)
SPIKE_ANSWERS_HEADER = "# Fill x and y with ok or bad."
MARK_RANK = {"bad": 0, "mid": 1, "ok": 2}


class SeededBackend:
    """Adds the spike seed to every request and remembers the model's reply."""

    def __init__(self, inner: CheckBackend, seed: int) -> None:
        self._inner = inner
        self._seed = seed
        self.reply: object = None

    async def complete(self, request: ChatRequest) -> str:
        seeded = replace(request, options=replace(request.options, seed=self._seed))
        self.reply = None
        reply = await self._inner.complete(seeded)
        self.reply = reply
        return reply


@dataclass(frozen=True)
class Generation:
    item_id: str
    seed: int
    stage_text: str
    method: str
    unresolved: bool
    seconds: float
    raw_reply: str | None
    failed_rules: list[str]
    fallback_reason: str | None


async def _one_delta(text: str) -> AsyncIterator[str]:
    yield text


def _usable_reply(reply: object) -> str | None:
    if isinstance(reply, str) and reply.strip():
        return reply.strip()
    return None


async def run_generation(
    item: RestorationItem,
    seed: int,
    backend: CheckBackend,
    proxy: PersonalProxySettings,
) -> Generation:
    seeded = SeededBackend(backend, seed)
    started = time.perf_counter()
    sentences = [
        sentence
        async for sentence in restore_answer(
            _one_delta(item.sentence), item.mapping, seeded, proxy
        )
    ]
    seconds = time.perf_counter() - started
    if len(sentences) != 1:
        raise SystemExit(
            f"{item.item_id}: the stage returned {len(sentences)} sentences, expected 1"
        )
    sentence = sentences[0]
    reply = _usable_reply(seeded.reply)
    rules = (
        [
            rule.value
            for rule in failed_rules(
                item.sentence, known_entries(item.sentence, item.mapping), reply
            )
        ]
        if reply is not None
        else []
    )
    return Generation(
        item_id=item.item_id,
        seed=seed,
        stage_text=sentence.text,
        method=sentence.method.value,
        unresolved=sentence.unresolved_placeholders,
        seconds=seconds,
        raw_reply=reply,
        failed_rules=rules,
        fallback_reason=_fallback_reason(sentence.method, reply, rules),
    )


def _fallback_reason(
    method: RestorationMethod, reply: str | None, rules: list[str]
) -> str | None:
    if method is RestorationMethod.MODEL:
        return None
    if reply is None:
        return NO_USABLE_REPLY
    return "+".join(rules)


def automatic_metrics(generations: Sequence[Generation]) -> RestorationMetrics:
    """The pass rate is the share of generations the stage kept from the model;
    the alteration rate is the share of usable replies that changed a word
    outside the restored values."""
    if not generations:
        return RestorationMetrics(0, 0.0, 0.0)
    kept = sum(1 for g in generations if g.method == RestorationMethod.MODEL.value)
    replied = [g for g in generations if g.raw_reply is not None]
    altered = sum(
        1 for g in replied if RestorationRule.LITERAL_CHANGED.value in g.failed_rules
    )
    return RestorationMetrics(
        len(generations),
        kept / len(generations),
        altered / len(replied) if replied else 0.0,
    )


def fallback_breakdown(generations: Sequence[Generation]) -> dict[str, int]:
    return dict(Counter(g.fallback_reason for g in generations if g.fallback_reason))


def review_model_outputs(generations: Sequence[Generation]) -> dict[str, str]:
    return {
        g.item_id: g.raw_reply if g.raw_reply is not None else NO_REPLY_TEXT
        for g in generations
        if g.seed == REVIEW_SEED
    }


def review_model_validity(generations: Sequence[Generation]) -> dict[str, bool]:
    return {
        g.item_id: g.method == RestorationMethod.MODEL.value
        for g in generations
        if g.seed == REVIEW_SEED
    }


def save_generations(path: Path, generations: Sequence[Generation]) -> None:
    document = [asdict(g) for g in generations]
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_generations(path: Path) -> list[Generation]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return [Generation(**entry) for entry in document]


def _mark(value: str) -> str | None:
    mark = value.strip().lower() or "mid"
    return mark if mark in MARK_RANK else None


def answers_problem(answers: dict[str, dict[str, str]]) -> str | None:
    """What is wrong with the answers file, or None. An empty mark is mid, but
    two empty marks cannot be told from an unfilled item."""
    for pair in build_review_pairs():
        sides = answers.get(pair.item_id)
        if sides is None or "x" not in sides or "y" not in sides:
            return f"{pair.item_id}: x and y are missing from the answers file."
        if not sides["x"].strip() and not sides["y"].strip():
            return (
                f"{pair.item_id}: both x and y are empty; fill every item "
                "(write mid explicitly if both are middle)."
            )
        for side in ("x", "y"):
            if _mark(sides[side]) is None:
                return (
                    f"{pair.item_id}: {side} = {sides[side]!r} is not ok, mid or bad."
                )
    return None


def _marks(pair, answers: dict[str, dict[str, str]]) -> tuple[str, str]:
    sides = answers[pair.item_id]
    model_side, substitution_side = ("x", "y") if pair.x_is_model else ("y", "x")
    return _mark(sides[model_side]), _mark(sides[substitution_side])


def case_result(
    pairs, answers: dict[str, dict[str, str]], model_valid: dict[str, bool]
) -> CaseResult:
    """Items whose substitution is not ok, and how many of them the model
    answers with an ok output that the stage also validated."""
    wrong = right = 0
    for pair in pairs:
        model, substitution = _marks(pair, answers)
        if substitution == "ok":
            continue
        wrong += 1
        if model == "ok" and model_valid.get(pair.item_id):
            right += 1
    return CaseResult(wrong, right)


@dataclass(frozen=True)
class ScaleSummary:
    items: int
    model_counts: dict[str, int]
    substitution_counts: dict[str, int]
    strictly_better: int
    model_worse: list[str]


def _counts(marks: Sequence[str]) -> dict[str, int]:
    counted = Counter(marks)
    return {mark: counted.get(mark, 0) for mark in ("ok", "mid", "bad")}


def scale_summary(pairs, answers: dict[str, dict[str, str]]) -> ScaleSummary:
    marks = {pair.item_id: _marks(pair, answers) for pair in pairs}
    return ScaleSummary(
        items=len(marks),
        model_counts=_counts([model for model, _ in marks.values()]),
        substitution_counts=_counts([sub for _, sub in marks.values()]),
        strictly_better=sum(
            1 for model, sub in marks.values() if MARK_RANK[model] > MARK_RANK[sub]
        ),
        model_worse=[
            item_id
            for item_id, (model, sub) in marks.items()
            if MARK_RANK[model] < MARK_RANK[sub]
        ],
    )


def final_decision(
    generations: Sequence[Generation], answers: dict[str, dict[str, str]]
) -> tuple[bool, list[str]]:
    case = case_result(
        build_review_pairs(), answers, review_model_validity(generations)
    )
    return restoration_decision(automatic_metrics(generations), case)


def load_option_warnings(
    flash_attention: bool | None, kv_cache_type: str | None
) -> list[str]:
    warnings = []
    if flash_attention is None:
        warnings.append(
            "[backend].flash_attention is unset; the spikes ran with "
            f"{str(SPIKE_FLASH_ATTENTION).lower()}"
        )
    if kv_cache_type is None:
        warnings.append(
            "[backend].kv_cache_type is unset; the spikes ran with "
            f'"{SPIKE_KV_CACHE_TYPE}"'
        )
    return warnings


def describe_model(document: dict) -> str:
    details = document.get("details", {})
    size = details.get("parameter_size", "unknown")
    level = details.get("quantization_level", "unknown")
    return f"parameter_size={size}; quantization_level={level}"


def looks_four_bit(document: dict) -> bool:
    level = str(document.get("details", {}).get("quantization_level", ""))
    return level.upper().startswith(FOUR_BIT_LEVELS)


def fetch_model_details(client: httpx.Client, model: str) -> dict | None:
    try:
        response = client.post("/api/show", json={"model": model})
        response.raise_for_status()
        document = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return document if isinstance(document, dict) else None


async def warm_up(backend: CheckBackend) -> None:
    """Loads the model at the check's context before anything is timed, so the
    stage's own time limit is not spent on the load (a cold load can take about
    a minute; the backend read timeout allows 120 s). The request is cut at one
    token, which the backend reports as BackendReplyError: the model did answer,
    so that is a loaded model. Any other failure propagates."""
    try:
        await backend.complete(
            ChatRequest(
                prompt="ok",
                audio_base64="",
                options=GenerationOptions(num_predict=1),
            )
        )
    except BackendReplyError:
        return


def too_many_unusable(generations: Sequence[Generation], planned: int) -> bool:
    unusable = sum(1 for g in generations if g.fallback_reason == NO_USABLE_REPLY)
    return unusable > MAX_UNUSABLE_SHARE * planned


def invalid_message(unusable: int, planned: int) -> str:
    return (
        f"INVALID RUN: {unusable} of {planned} generations had no usable model "
        f"reply (more than {MAX_UNUSABLE_SHARE:.0%}); that is an Ollama problem, "
        "not a result about the model branch. No verdict was produced. Fix "
        "Ollama, delete the output directory, and run again."
    )


def render_generation(item: RestorationItem, generation: Generation) -> str:
    reason = generation.fallback_reason or "-"
    return "\n".join(
        [
            f"== {generation.item_id} seed {generation.seed}",
            f"sentence: {item.sentence}",
            f"stage output: {generation.stage_text}",
            f"method: {generation.method}; unresolved: {generation.unresolved}; "
            f"fallback reason: {reason}; seconds: {generation.seconds:.2f}",
        ]
    )


def render_automatic_report(generations: Sequence[Generation]) -> str:
    metrics = automatic_metrics(generations)
    breakdown = fallback_breakdown(generations)
    lines = [
        "# Restoration stage, automatic part",
        "",
        f"- generations: {metrics.generations}",
        f"- validation pass rate (method model): {metrics.validation_pass_rate:.3f}"
        f" (rule: at least {MIN_VALIDATION_PASS_RATE})",
        f"- alteration rate: {metrics.alteration_rate:.3f}"
        f" (rule: at most {MAX_ALTERATION_RATE})",
        "- fallbacks by reason: "
        + (", ".join(f"{k}={v}" for k, v in sorted(breakdown.items())) or "none"),
        "- case correctness (at least "
        f"{MIN_FALLBACK_BEATEN_SHARE} of the fallback's failures): needs the "
        "blind review, then `score`",
    ]
    return "\n".join(lines) + "\n"


def _print_effective_settings(settings) -> None:
    proxy = settings.personal_proxy
    backend = settings.backend
    print(
        f"[backend].endpoint = {backend.endpoint}; "
        f"[backend].flash_attention = {backend.flash_attention}; "
        f"[backend].kv_cache_type = {backend.kv_cache_type}; "
        f"[backend].read_timeout_seconds = {backend.read_timeout_seconds}\n"
        f"check_model = {proxy.check_model}; check_num_ctx = {proxy.check_num_ctx}; "
        f"check_temperature = {proxy.check_temperature}; "
        f"check_top_p = {proxy.check_top_p}; check_top_k = {proxy.check_top_k}; "
        f"check_min_p = {proxy.check_min_p}; "
        f"check_repeat_penalty = {proxy.check_repeat_penalty}; seeds = {SEEDS}"
    )
    for warning in load_option_warnings(backend.flash_attention, backend.kv_cache_type):
        print(f"WARNING: {warning}")


async def command_run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    proxy = settings.personal_proxy
    results = args.out / RESULTS_NAME
    if results.exists():
        print(f"{results} exists; delete it or choose another --out. Nothing was run.")
        return 2
    _print_effective_settings(settings)
    with httpx.Client(
        base_url=settings.backend.endpoint, timeout=PREFLIGHT_TIMEOUT_SECONDS
    ) as probe:
        problem = ollama_preflight(probe, settings.backend.endpoint, proxy.check_model)
        details = None if problem else fetch_model_details(probe, proxy.check_model)
    if problem:
        print(problem)
        return 2
    _print_model_details(proxy.check_model, details)
    timeout = httpx.Timeout(
        CONNECT_TIMEOUT_SECONDS, read=settings.backend.read_timeout_seconds
    )
    generations: list[Generation] = []
    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint, timeout=timeout
    ) as client:
        backend = OllamaCheckBackend(settings.backend, proxy, client)
        try:
            await warm_up(backend)
        except Exception:
            print("The warm-up request failed; Ollama is not usable. Nothing was run.")
            return 2
        for seed in SEEDS:
            for item in ITEMS:
                generation = await run_generation(item, seed, backend, proxy)
                generations.append(generation)
                save_generations(results, generations)
                print(render_generation(item, generation), flush=True)
                if too_many_unusable(generations, PLANNED_GENERATIONS):
                    print(_outage_message(generations))
                    return INVALID_EXIT_CODE
    _write_review_files(args.out, generations)
    report = render_automatic_report(generations)
    (args.out / REPORT_NAME).write_text(report, encoding="utf-8")
    print("\n" + report)
    print(
        f"Next: fill {args.out / ANSWERS_NAME} using {args.out / SHEET_NAME}, "
        "then run `score`."
    )
    return 0


def _print_model_details(model: str, details: dict | None) -> None:
    if details is None:
        print(f"WARNING: POST /api/show for {model} failed; quantization unknown")
        return
    print(f"model {model}: {describe_model(details)}")
    if not looks_four_bit(details):
        print(
            "WARNING: quantization_level does not look 4-bit; this may not be "
            "the INT4 production configuration"
        )


def _outage_message(generations: Sequence[Generation]) -> str:
    unusable = sum(1 for g in generations if g.fallback_reason == NO_USABLE_REPLY)
    return invalid_message(unusable, PLANNED_GENERATIONS)


def render_sheet(pairs, model_outputs: dict[str, str]) -> str:
    sheet = render_review_sheet(pairs, model_outputs)
    title, _spike_instructions, rest = sheet.split(BLANK_LINE, 2)
    return f"{title}{BLANK_LINE}{REVIEW_INSTRUCTIONS}{BLANK_LINE}{rest}"


def render_answers_template(pairs) -> str:
    return render_answer_template(pairs).replace(
        SPIKE_ANSWERS_HEADER, ANSWERS_HEADER, 1
    )


def _write_review_files(out: Path, generations: Sequence[Generation]) -> None:
    pairs = build_review_pairs()
    sheet = render_sheet(pairs, review_model_outputs(generations))
    (out / SHEET_NAME).write_text(sheet, encoding="utf-8")
    answers = out / ANSWERS_NAME
    if not answers.exists():
        answers.write_text(render_answers_template(pairs), encoding="utf-8")


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{mark}={count}" for mark, count in counts.items())


def command_score(args: argparse.Namespace) -> int:
    generations = load_generations(args.out / RESULTS_NAME)
    if len(generations) != PLANNED_GENERATIONS or too_many_unusable(
        generations, PLANNED_GENERATIONS
    ):
        print(
            _outage_message(generations)
            if len(generations) == PLANNED_GENERATIONS
            else f"INVALID RUN: {len(generations)} of {PLANNED_GENERATIONS} "
            "generations are in results.json. No verdict was produced."
        )
        return INVALID_EXIT_CODE
    answers = load_answers(args.out / ANSWERS_NAME)
    problem = answers_problem(answers)
    if problem:
        print(problem)
        return 2
    keep, reasons = final_decision(generations, answers)
    pairs = build_review_pairs()
    case = case_result(pairs, answers, review_model_validity(generations))
    scale = scale_summary(pairs, answers)
    lines = [
        render_automatic_report(generations).rstrip(),
        f"- substitution not ok on {case.fallback_wrong} items; the model output "
        f"is ok and was validated on {case.model_right_where_fallback_wrong} of them",
        f"- model output marks: {_format_counts(scale.model_counts)}",
        f"- substitution marks: {_format_counts(scale.substitution_counts)}",
        "- model strictly better than substitution (ok > mid > bad) on "
        f"{scale.strictly_better} of {scale.items} items",
        "- items where the model is worse: " + (", ".join(scale.model_worse) or "none"),
        "- decision: "
        + (
            "KEEP the model branch"
            if keep
            else "NOT SUPPORTED: remove the model branch, keep substitution"
        ),
    ]
    lines += [f"  - {reason}" for reason in reasons]
    report = "\n".join(lines) + "\n"
    (args.out / REPORT_NAME).write_text(report, encoding="utf-8")
    print(report)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    commands.add_parser("score")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "run":
        return asyncio.run(command_run(args))
    return command_score(args)


if __name__ == "__main__":
    sys.exit(main())
