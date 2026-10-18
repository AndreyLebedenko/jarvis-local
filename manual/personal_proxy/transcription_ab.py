"""Pure logic of the transcription A/B spikes v2.1.0-2 and v2.1.0-3.

Scoring, the frozen decision rule, and the report; no Ollama here. The cards
are tasks/spike-v2.1.0-2-transcription-prompt.md (A against a reworded
instruction B) and tasks/spike-v2.1.0-3-json-transcription.md (A against a
constrained-JSON request C).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import Any

from manual.personal_proxy.corpus import Utterance
from manual.personal_proxy.scoring import looks_like_audio_failure
from manual.personal_proxy.text import word_error_rate

VARIANT_B_INSTRUCTION = (
    "I have attached an audio recording to this message. Your only task is to "
    "transcribe it verbatim, word for word. Do not correct, complete, "
    "translate, or interpret anything. Output only the spoken text, exactly "
    "as spoken."
)

JSON_TRANSCRIPT_FIELD = "raw_transcript"
JSON_TRANSCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {JSON_TRANSCRIPT_FIELD: {"type": "string"}},
    "required": [JSON_TRANSCRIPT_FIELD],
}

KNOWN_RECORDING_DEVIATIONS = {
    "id_birth_date": (
        "двадцать третьего марта тысяча девятьсот восемьдесят пятого года",
        "24 марта 1985 года",
    ),
}

MIN_FAILURE_DIFFERENCE = 4
MAX_WER_REGRESSION = 0.02
TARGET_FAILURES = 8


class Variant(StrEnum):
    A = "a_current"
    B = "b_attached_audio"
    C = "c_json_raw_transcript"


VARIANT_LABEL = {
    Variant.A: "A (current)",
    Variant.B: "B (attached audio)",
    Variant.C: "C (constrained JSON)",
}


class Verdict(StrEnum):
    CANDIDATE_BETTER = "candidate_better"
    CANDIDATE_WORSE = "candidate_worse"
    OWNER = "owner"
    NO_DIFFERENCE = "no_difference"


def reference_text(utterance: Utterance) -> str:
    text = utterance.text
    deviation = KNOWN_RECORDING_DEVIATIONS.get(utterance.utterance_id)
    if deviation is not None:
        scripted, spoken = deviation
        text = text.replace(scripted, spoken)
    return text


def extract_transcript(variant: Variant, response_text: str) -> str | None:
    """The transcript in a response, or None when a constrained-JSON response
    is not exactly one object with one string field."""
    if variant is not Variant.C:
        return response_text
    try:
        document = json.loads(response_text)
    except json.JSONDecodeError:
        return None
    if (
        isinstance(document, dict)
        and set(document) == {JSON_TRANSCRIPT_FIELD}
        and isinstance(document[JSON_TRANSCRIPT_FIELD], str)
    ):
        return document[JSON_TRANSCRIPT_FIELD]
    return None


@dataclass(frozen=True)
class TranscriptScore:
    variant: Variant
    subject_id: str
    seed: int
    transcript: str
    reference: str
    wer: float
    audio_failure: bool
    valid: bool = True
    seconds: float = 0.0


def score_transcript(
    variant: Variant,
    utterance: Utterance,
    seed: int,
    response_text: str,
    seconds: float = 0.0,
) -> TranscriptScore:
    reference = reference_text(utterance)
    transcript = extract_transcript(variant, response_text)
    if transcript is None:
        return TranscriptScore(
            variant,
            utterance.utterance_id,
            seed,
            response_text,
            reference,
            1.0,
            True,
            valid=False,
            seconds=seconds,
        )
    return TranscriptScore(
        variant,
        utterance.utterance_id,
        seed,
        transcript,
        reference,
        word_error_rate(reference, transcript),
        looks_like_audio_failure(transcript, reference),
        seconds=seconds,
    )


@dataclass(frozen=True)
class VariantMetrics:
    variant: Variant
    generations: int
    audio_failures: int
    median_wer: float | None
    invalid: int = 0
    median_seconds: float | None = None


def aggregate(variant: Variant, scores: list[TranscriptScore]) -> VariantMetrics:
    own = [s for s in scores if s.variant is variant]
    return VariantMetrics(
        variant,
        len(own),
        sum(1 for s in own if s.audio_failure),
        median(s.wer for s in own) if own else None,
        sum(1 for s in own if not s.valid),
        median(s.seconds for s in own) if own else None,
    )


def decide(baseline: VariantMetrics, candidate: VariantMetrics) -> Verdict:
    if candidate.audio_failures >= baseline.audio_failures + MIN_FAILURE_DIFFERENCE:
        return Verdict.CANDIDATE_WORSE
    if candidate.audio_failures > baseline.audio_failures - MIN_FAILURE_DIFFERENCE:
        return Verdict.NO_DIFFERENCE
    if (
        baseline.median_wer is not None
        and candidate.median_wer is not None
        and candidate.median_wer > baseline.median_wer + MAX_WER_REGRESSION
    ):
        return Verdict.OWNER
    return Verdict.CANDIDATE_BETTER


@dataclass(frozen=True)
class PairedCounts:
    baseline_only: int
    candidate_only: int
    both: int


def paired_counts(
    scores: list[TranscriptScore],
    baseline: Variant = Variant.A,
    candidate: Variant = Variant.B,
) -> PairedCounts:
    failed: dict[Variant, set[tuple[str, int]]] = {baseline: set(), candidate: set()}
    for score in scores:
        if score.audio_failure and score.variant in failed:
            failed[score.variant].add((score.subject_id, score.seed))
    a, b = failed[baseline], failed[candidate]
    return PairedCounts(len(a - b), len(b - a), len(a & b))


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _clip(text: str, limit: int = 110) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "..."


def render_report(
    *,
    meta: dict[str, object],
    scores: list[TranscriptScore],
    controls: dict[Variant, dict[str, list[str]]],
    identical_to_main_run: tuple[int, int] | None,
    candidate: Variant = Variant.B,
) -> str:
    variants = (Variant.A, candidate)
    a = aggregate(Variant.A, scores)
    c = aggregate(candidate, scores)
    verdict = decide(a, c)
    paired = paired_counts(scores, Variant.A, candidate)
    lines = ["# Transcription A/B (spikes v2.1.0-2 and -3): report", ""]
    lines += ["## Run", ""]
    lines += [f"- {key}: {meta[key]}" for key in sorted(meta)]
    lines += ["", "## Decision (frozen rule)", ""]
    lines.append(f"Verdict: **{verdict.value.upper()}**")
    lines += [
        "",
        f"| metric | {VARIANT_LABEL[Variant.A]} | {VARIANT_LABEL[candidate]} |",
        "|---|---|---|",
        f"| generations | {a.generations} | {c.generations} |",
        f"| audio failures | {a.audio_failures} | {c.audio_failures} |",
        f"| median WER | {_fmt(a.median_wer)} | {_fmt(c.median_wer)} |",
        f"| invalid output | {a.invalid} | {c.invalid} |",
        "| median seconds | "
        f"{_fmt(a.median_seconds, 2)} | {_fmt(c.median_seconds, 2)} |",
    ]
    lines += [
        "",
        f"Paired: failed in A only {paired.baseline_only}, in the candidate "
        f"only {paired.candidate_only}, in both {paired.both}.",
        f"Reaches the 10% level (at most {TARGET_FAILURES} failures of 88): "
        f"A {a.audio_failures <= TARGET_FAILURES}, "
        f"candidate {c.audio_failures <= TARGET_FAILURES}.",
    ]
    if identical_to_main_run is not None:
        same, total = identical_to_main_run
        lines.append(
            f"Determinism check: {same}/{total} variant-A transcripts are "
            "identical to the main run's baseline transcripts."
        )
    for variant in variants:
        lines += ["", f"## Audio failures, {variant.value}", ""]
        failing = sorted(
            (s for s in scores if s.variant is variant and s.audio_failure),
            key=lambda s: (s.subject_id, s.seed),
        )
        for s in failing:
            lines.append(
                f"- {s.subject_id}/s{s.seed} WER={s.wer:.2f}"
                f"{'' if s.valid else ' (invalid output)'}\n"
                f"  expected: {_clip(s.reference)}\n"
                f"  actual:   {_clip(s.transcript)}"
            )
        if not failing:
            lines.append("none")
    lines += ["", "## Control outputs (silence, noise, no media)", ""]
    for variant in variants:
        for control_id, outputs in sorted(controls.get(variant, {}).items()):
            lines.append(
                f"- {variant.value} {control_id}: "
                + " | ".join(repr(_clip(o, 80)) for o in outputs)
            )
    lines += [
        "",
        "Reported only, never part of the rule: paired table, invalid output, "
        "seconds, 10% level, determinism check, control outputs.",
        "",
    ]
    return "\n".join(lines)
