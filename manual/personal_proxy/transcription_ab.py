"""Pure logic of the transcription-instruction A/B spike v2.1.0-2.

Scoring, the frozen decision rule, and the report; no Ollama here. The card is
tasks/spike-v2.1.0-2-transcription-prompt.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from statistics import median

from manual.personal_proxy.corpus import Utterance
from manual.personal_proxy.scoring import looks_like_audio_failure
from manual.personal_proxy.text import word_error_rate

VARIANT_B_INSTRUCTION = (
    "I have attached an audio recording to this message. Your only task is to "
    "transcribe it verbatim, word for word. Do not correct, complete, "
    "translate, or interpret anything. Output only the spoken text, exactly "
    "as spoken."
)

KNOWN_RECORDING_DEVIATIONS = {
    "id_birth_date": (
        "двадцать третьего марта тысяча девятьсот восемьдесят пятого года",
        "24 марта 1985 года",
    ),
}

MIN_FAILURE_DIFFERENCE = 4
MAX_WER_REGRESSION = 0.02


class Variant(StrEnum):
    A = "a_current"
    B = "b_attached_audio"


class Verdict(StrEnum):
    B_BETTER = "b_better"
    B_WORSE = "b_worse"
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
class TranscriptScore:
    variant: Variant
    subject_id: str
    seed: int
    transcript: str
    reference: str
    wer: float
    audio_failure: bool


def score_transcript(
    variant: Variant, utterance: Utterance, seed: int, transcript: str
) -> TranscriptScore:
    reference = reference_text(utterance)
    return TranscriptScore(
        variant,
        utterance.utterance_id,
        seed,
        transcript,
        reference,
        word_error_rate(reference, transcript),
        looks_like_audio_failure(transcript, reference),
    )


@dataclass(frozen=True)
class VariantMetrics:
    variant: Variant
    generations: int
    audio_failures: int
    median_wer: float | None


def aggregate(variant: Variant, scores: list[TranscriptScore]) -> VariantMetrics:
    own = [s for s in scores if s.variant is variant]
    return VariantMetrics(
        variant,
        len(own),
        sum(1 for s in own if s.audio_failure),
        median(s.wer for s in own) if own else None,
    )


def decide(a: VariantMetrics, b: VariantMetrics) -> Verdict:
    if b.audio_failures >= a.audio_failures + MIN_FAILURE_DIFFERENCE:
        return Verdict.B_WORSE
    if b.audio_failures > a.audio_failures - MIN_FAILURE_DIFFERENCE:
        return Verdict.NO_DIFFERENCE
    if (
        a.median_wer is not None
        and b.median_wer is not None
        and b.median_wer > a.median_wer + MAX_WER_REGRESSION
    ):
        return Verdict.OWNER
    return Verdict.B_BETTER


@dataclass(frozen=True)
class PairedCounts:
    a_only: int
    b_only: int
    both: int


def paired_counts(scores: list[TranscriptScore]) -> PairedCounts:
    failed: dict[Variant, set[tuple[str, int]]] = {Variant.A: set(), Variant.B: set()}
    for score in scores:
        if score.audio_failure:
            failed[score.variant].add((score.subject_id, score.seed))
    a, b = failed[Variant.A], failed[Variant.B]
    return PairedCounts(len(a - b), len(b - a), len(a & b))


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _clip(text: str, limit: int = 110) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "..."


def render_report(
    *,
    meta: dict[str, object],
    scores: list[TranscriptScore],
    controls: dict[Variant, dict[str, list[str]]],
    identical_to_main_run: tuple[int, int] | None,
) -> str:
    a = aggregate(Variant.A, scores)
    b = aggregate(Variant.B, scores)
    verdict = decide(a, b)
    paired = paired_counts(scores)
    lines = ["# Transcription-instruction A/B (spike v2.1.0-2): report", ""]
    lines += ["## Run", ""]
    lines += [f"- {key}: {meta[key]}" for key in sorted(meta)]
    lines += ["", "## Decision (frozen rule)", ""]
    lines.append(f"Verdict: **{verdict.value.upper()}**")
    lines += ["", "| metric | A (current) | B (attached audio) |", "|---|---|---|"]
    lines.append(f"| generations | {a.generations} | {b.generations} |")
    lines.append(f"| audio failures | {a.audio_failures} | {b.audio_failures} |")
    lines.append(f"| median WER | {_fmt(a.median_wer)} | {_fmt(b.median_wer)} |")
    lines += [
        "",
        f"Paired: failed in A only {paired.a_only}, in B only {paired.b_only}, "
        f"in both {paired.both}.",
    ]
    if identical_to_main_run is not None:
        same, total = identical_to_main_run
        lines.append(
            f"Determinism check: {same}/{total} variant-A transcripts are "
            "identical to the main run's baseline transcripts."
        )
    for variant in (Variant.A, Variant.B):
        lines += ["", f"## Audio failures, {variant.value}", ""]
        failing = sorted(
            (s for s in scores if s.variant is variant and s.audio_failure),
            key=lambda s: (s.subject_id, s.seed),
        )
        for s in failing or []:
            lines.append(
                f"- {s.subject_id}/s{s.seed} WER={s.wer:.2f}\n"
                f"  expected: {_clip(s.reference)}\n"
                f"  actual:   {_clip(s.transcript)}"
            )
        if not failing:
            lines.append("none")
    lines += ["", "## Control outputs (silence, noise, no media)", ""]
    for variant in (Variant.A, Variant.B):
        for control_id, outputs in sorted(controls.get(variant, {}).items()):
            lines.append(
                f"- {variant.value} {control_id}: "
                + " | ".join(repr(_clip(o, 80)) for o in outputs)
            )
    lines += [
        "",
        "Reported only, never part of the rule: paired table, determinism "
        "check, control outputs.",
        "",
    ]
    return "\n".join(lines)
