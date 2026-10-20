"""Pure logic of the transcription A/B spikes v2.1.0-2 and v2.1.0-3.

Scoring, the frozen decision rule, and the report; no Ollama here. The cards
are tasks/done/spike-v2.1.0-2-transcription-prompt.md (A against a reworded
instruction B) and tasks/done/spike-v2.1.0-3-json-transcription.md (A against a
constrained-JSON request C).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import Any

from manual.personal_proxy.corpus import Utterance
from manual.personal_proxy.scoring import (
    looks_like_audio_failure,
    matches_audio_refusal,
)
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

SPEECH_PRESENT_FIELD = "speech_present"
JSON_SPEECH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        SPEECH_PRESENT_FIELD: {"type": "boolean"},
        JSON_TRANSCRIPT_FIELD: {"type": "string"},
    },
    "required": [SPEECH_PRESENT_FIELD, JSON_TRANSCRIPT_FIELD],
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
    D = "d_json_speech_present"


VARIANT_LABEL = {
    Variant.A: "A (current)",
    Variant.B: "B (attached audio)",
    Variant.C: "C (constrained JSON)",
    Variant.D: "D (JSON speech_present + raw_transcript)",
}


class Overall(StrEnum):
    ADVANCE = "advance"
    DO_NOT_ADVANCE = "do_not_advance"
    OWNER = "owner"


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


@dataclass(frozen=True)
class ParsedResponse:
    transcript: str
    speech_present: bool | None = None


def parse_response(variant: Variant, response_text: str) -> ParsedResponse | None:
    """The transcript (and the speech flag for D) in a response, or None when
    a constrained-JSON response is not exactly the object of its schema."""
    if variant not in (Variant.C, Variant.D):
        return ParsedResponse(response_text)
    try:
        document = json.loads(response_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict):
        return None
    if variant is Variant.C:
        if set(document) == {JSON_TRANSCRIPT_FIELD} and isinstance(
            document[JSON_TRANSCRIPT_FIELD], str
        ):
            return ParsedResponse(document[JSON_TRANSCRIPT_FIELD])
        return None
    if set(document) == {SPEECH_PRESENT_FIELD, JSON_TRANSCRIPT_FIELD} and (
        isinstance(document[SPEECH_PRESENT_FIELD], bool)
        and isinstance(document[JSON_TRANSCRIPT_FIELD], str)
    ):
        return ParsedResponse(
            document[JSON_TRANSCRIPT_FIELD], document[SPEECH_PRESENT_FIELD]
        )
    return None


def extract_transcript(variant: Variant, response_text: str) -> str | None:
    parsed = parse_response(variant, response_text)
    return None if parsed is None else parsed.transcript


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
    speech_present: bool | None = None


def score_transcript(
    variant: Variant,
    utterance: Utterance,
    seed: int,
    response_text: str,
    seconds: float = 0.0,
) -> TranscriptScore:
    reference = reference_text(utterance)
    parsed = parse_response(variant, response_text)
    if parsed is None:
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
    claims_no_speech = parsed.speech_present is False
    return TranscriptScore(
        variant,
        utterance.utterance_id,
        seed,
        parsed.transcript,
        reference,
        word_error_rate(reference, parsed.transcript),
        claims_no_speech or looks_like_audio_failure(parsed.transcript, reference),
        seconds=seconds,
        speech_present=parsed.speech_present,
    )


@dataclass(frozen=True)
class ControlScore:
    variant: Variant
    control_id: str
    seed: int
    output: str
    clean: bool
    valid: bool = True


def score_control(
    variant: Variant, control_id: str, seed: int, response_text: str
) -> ControlScore:
    """A control must not yield speech: D reports no speech with an empty
    transcript, the plain variants return nothing or say they cannot hear."""
    parsed = parse_response(variant, response_text)
    if parsed is None:
        return ControlScore(variant, control_id, seed, response_text, False, False)
    empty = not parsed.transcript.strip()
    if variant is Variant.D:
        clean = parsed.speech_present is False and empty
    else:
        clean = empty or matches_audio_refusal(parsed.transcript)
    return ControlScore(variant, control_id, seed, parsed.transcript, clean)


def control_criterion_passes(variant: Variant, controls: list[ControlScore]) -> bool:
    own = [c for c in controls if c.variant is variant]
    return bool(own) and all(c.clean for c in own)


def overall(utterance_verdict: Verdict, controls_pass: bool) -> Overall:
    if utterance_verdict is Verdict.CANDIDATE_WORSE or not controls_pass:
        return Overall.DO_NOT_ADVANCE
    if utterance_verdict is Verdict.CANDIDATE_BETTER:
        return Overall.ADVANCE
    return Overall.OWNER


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
    controls: list[ControlScore],
    identical_to_main_run: tuple[int, int] | None,
    candidate: Variant = Variant.B,
) -> str:
    variants = (Variant.A, candidate)
    a = aggregate(Variant.A, scores)
    c = aggregate(candidate, scores)
    verdict = decide(a, c)
    controls_pass = control_criterion_passes(candidate, controls)
    paired = paired_counts(scores, Variant.A, candidate)
    lines = ["# Transcription A/B (spikes v2.1.0-2 to -4): report", ""]
    lines += ["## Run", ""]
    lines += [f"- {key}: {meta[key]}" for key in sorted(meta)]
    lines += ["", "## Decision (frozen rule)", ""]
    lines.append(f"Utterance verdict: **{verdict.value.upper()}**")
    clean = {
        v: (
            sum(1 for k in controls if k.variant is v and k.clean),
            sum(1 for k in controls if k.variant is v),
        )
        for v in variants
    }
    lines.append(
        f"Control criterion (candidate, all clean required): "
        f"**{'PASS' if controls_pass else 'FAIL'}** "
        f"({clean[candidate][0]}/{clean[candidate][1]} clean; "
        f"A {clean[Variant.A][0]}/{clean[Variant.A][1]})"
    )
    lines.append(f"Overall: **{overall(verdict, controls_pass).value.upper()}**")
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
    lines += [
        "",
        "## Controls (silence, noise, no media): speech must not be reported",
        "",
    ]
    for variant in variants:
        for k in sorted(
            (k for k in controls if k.variant is variant),
            key=lambda k: (k.control_id, k.seed),
        ):
            mark = "clean" if k.clean else "SPEECH REPORTED"
            lines.append(
                f"- {variant.value} {k.control_id}/s{k.seed}: {mark}"
                f"{'' if k.valid else ' (invalid output)'}: {_clip(k.output, 80)!r}"
            )
    lines += [
        "",
        "Reported only, never part of the rule: paired table, invalid output, "
        "seconds, 10% level, determinism check, the text of every control "
        "output.",
        "",
    ]
    return "\n".join(lines)
