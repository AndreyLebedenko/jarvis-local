"""File steps after the live run of tasks/done/spike-single-pass-tts-block.md:
the two blind-review sittings and the report. No model access."""

from __future__ import annotations

import hashlib
from pathlib import Path

from manual.single_pass_tts_corpus import REVIEW_SEED
from manual.single_pass_tts_grader import grade_generations
from manual.single_pass_tts_records import GenerationMetrics, load_records
from manual.single_pass_tts_review import (
    ReviewAnswers,
    ReviewKey,
    ReviewPlan,
    Sitting,
    build_review,
    load_key_json,
    parse_answers,
    render_answer_template,
    render_key_json,
    render_report_markdown,
    render_sheet_markdown,
    score,
)

CALLS_DIR_NAME = "calls"
KEY_FILE_NAME = "review-key.json"
RECORDS_FINGERPRINT_FILE_NAME = "review-records.sha256"
REPORT_FILE_NAME = "report.md"
REVIEW_RNG_SEED = 20260927


class ReviewStepError(RuntimeError):
    pass


def sheet_path(out_dir: Path, sitting: Sitting) -> Path:
    return out_dir / f"review-{sitting.value}-sheet.md"


def answers_path(out_dir: Path, sitting: Sitting) -> Path:
    return out_dir / f"review-{sitting.value}-answers.toml"


def write_production_review(out_dir: Path) -> list[Path]:
    fingerprint_path = out_dir / RECORDS_FINGERPRINT_FILE_NAME
    if fingerprint_path.exists():
        _require_unchanged_records(out_dir)
    plan = _plan(_metrics(out_dir))
    (out_dir / KEY_FILE_NAME).write_text(render_key_json(plan), encoding="utf-8")
    fingerprint_path.write_text(_records_fingerprint(out_dir), encoding="utf-8")
    return _write_sitting(out_dir, plan, Sitting.PRODUCTION)


def write_equalized_review(out_dir: Path) -> list[Path]:
    _production_answers(out_dir, _saved_key(out_dir))
    _require_unchanged_records(out_dir)
    return _write_sitting(out_dir, _plan(_metrics(out_dir)), Sitting.EQUALIZED)


def write_report(out_dir: Path) -> Path:
    key = _saved_key(out_dir)
    _require_unchanged_records(out_dir)
    production = _production_answers(out_dir, key)
    equalized_file = answers_path(out_dir, Sitting.EQUALIZED)
    equalized = (
        _parse(equalized_file, key, Sitting.EQUALIZED)
        if equalized_file.exists()
        else None
    )
    report = score(_metrics(out_dir), key, production, equalized)
    path = out_dir / REPORT_FILE_NAME
    path.write_text(render_report_markdown(report), encoding="utf-8")
    return path


def _records_fingerprint(out_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((out_dir / CALLS_DIR_NAME).glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _require_unchanged_records(out_dir: Path) -> None:
    recorded = (out_dir / RECORDS_FINGERPRINT_FILE_NAME).read_text(encoding="utf-8")
    if recorded != _records_fingerprint(out_dir):
        raise ReviewStepError(
            "records changed since the production sheet was made; answers given "
            "against the old sheet no longer match them"
        )


def _metrics(out_dir: Path) -> list[GenerationMetrics]:
    records = load_records(out_dir / CALLS_DIR_NAME)
    if not records:
        raise ReviewStepError(f"no records under {out_dir / CALLS_DIR_NAME}")
    return grade_generations(records)


def _plan(metrics: list[GenerationMetrics]) -> ReviewPlan:
    return build_review(metrics, review_seed=REVIEW_SEED, rng_seed=REVIEW_RNG_SEED)


def _write_sitting(out_dir: Path, plan: ReviewPlan, sitting: Sitting) -> list[Path]:
    sheet = sheet_path(out_dir, sitting)
    sheet.write_text(render_sheet_markdown(plan, sitting), encoding="utf-8")
    answers = answers_path(out_dir, sitting)
    if not answers.exists():
        answers.write_text(render_answer_template(plan, sitting), encoding="utf-8")
    return [sheet, answers]


def _saved_key(out_dir: Path) -> ReviewKey:
    path = out_dir / KEY_FILE_NAME
    if not path.exists():
        raise ReviewStepError(f"{path} is missing; run the review step first")
    return load_key_json(path.read_text(encoding="utf-8"))


def _production_answers(out_dir: Path, key: ReviewKey) -> ReviewAnswers:
    return _parse(answers_path(out_dir, Sitting.PRODUCTION), key, Sitting.PRODUCTION)


def _parse(path: Path, key: ReviewKey, sitting: Sitting) -> ReviewAnswers:
    try:
        return parse_answers(path.read_text(encoding="utf-8"), key, sitting)
    except (OSError, ValueError) as error:
        raise ReviewStepError(f"{path}: {error}") from error
