"""Per-generation scoring and per-arm aggregation for the personal-proxy spike.

Pure logic over GenerationRecord files and the frozen corpus. The measures and
their definitions are those of tasks/spike-v2.1.0-1-combined-transcribe-sanitize.md,
"Measurements".
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass

from manual.personal_proxy.corpus import (
    Control,
    Span,
    Utterance,
    Verdict,
    utterance_by_id,
)
from manual.personal_proxy.parse import (
    FailureClass,
    ParsedOutput,
    ParseFailure,
    parse_sanitize_output,
)
from manual.personal_proxy.records import Arm, CallStage, GenerationRecord
from manual.personal_proxy.text import (
    digit_runs,
    stem_present,
    tokenize,
    word_error_rate,
)

AUDIO_FAILURE_WER = 0.5
MIN_CONTENT_TOKEN_LENGTH = 4

# The "nothing in this audio" refusals documented in the closed audio
# request-shape study, plus the English forms the verbatim instruction draws.
_REFUSAL_PATTERNS = re.compile(
    r"не могу прослушать|не могу (?:обрабатывать|воспринимать)|аудиофайл|"
    r"предостав\w+ (?:мне )?(?:аудио|запись)|не было распознано|"
    r"provide the audio|no audio|cannot (?:listen|process)|can'?t (?:listen|hear)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GenerationScore:
    subject_id: str
    arm: Arm
    seed: int
    is_control: bool
    errored: bool
    valid: bool
    failure: FailureClass | None
    verdict: Verdict | None
    raw_transcript: str | None
    wer: float | None
    audio_failure: bool | None
    spans_total: int
    leaked_span_ids: tuple[str, ...]
    leak_renderings: tuple[str, ...]
    mapping_checked: int
    mapping_errors: int
    preservation: float | None
    false_refusal: bool
    missed_refusal: bool
    fabrication: bool
    total_seconds: float
    cold: bool


def looks_like_audio_failure(raw_transcript: str, reference: str) -> bool:
    if _REFUSAL_PATTERNS.search(raw_transcript):
        return True
    return word_error_rate(reference, raw_transcript) > AUDIO_FAILURE_WER


def leaked_spans(
    spans: tuple[Span, ...], sanitized_text: str
) -> list[tuple[Span, str]]:
    """Spans still recognizable in the sanitized text, with how they leaked."""
    tokens = tokenize(sanitized_text)
    runs = digit_runs(sanitized_text)
    has_literal_digits = any(token.isdigit() for token in tokens)
    leaked: list[tuple[Span, str]] = []
    for span in spans:
        if any(stem_present(form, tokens) for form in span.leak_forms()):
            leaked.append((span, "text"))
        elif any(key in run for key in span.all_digit_keys() for run in runs):
            leaked.append((span, "digits" if has_literal_digits else "words"))
    return leaked


def mapping_matches(span: Span, mapping: dict[str, str]) -> bool:
    for original in mapping.values():
        if any(stem_present(f, tokenize(original)) for f in span.leak_forms()):
            return True
        if any(
            key in run for key in span.all_digit_keys() for run in digit_runs(original)
        ):
            return True
    return False


def meaning_preservation(utterance: Utterance, sanitized_text: str) -> float | None:
    """Share of the non-sensitive content words that survive sanitization."""
    span_tokens = {
        token for span in utterance.spans for token in tokenize(span.surface)
    }
    content = [
        token
        for token in tokenize(utterance.text)
        if len(token) >= MIN_CONTENT_TOKEN_LENGTH and token not in span_tokens
    ]
    if not content:
        return None
    sanitized_tokens = tokenize(sanitized_text)
    kept = sum(1 for token in content if stem_present(token, sanitized_tokens))
    return kept / len(content)


@dataclass(frozen=True)
class _Extracted:
    parsed: ParsedOutput | ParseFailure | None
    raw_transcript: str | None


def _extract(record: GenerationRecord) -> _Extracted:
    if record.arm is Arm.T_PLUS_S:
        transcribe = record.call_for(CallStage.TRANSCRIBE)
        sanitize = record.call_for(CallStage.SANITIZE_TEXT)
        raw = transcribe.response_text.strip() if transcribe else None
        if sanitize is None:
            return _Extracted(None, raw)
        parsed = parse_sanitize_output(
            sanitize.response_text, sanitize.done_reason, require_raw_transcript=False
        )
        return _Extracted(parsed, raw)
    combined = record.call_for(CallStage.COMBINED)
    if combined is None:
        return _Extracted(None, None)
    parsed = parse_sanitize_output(
        combined.response_text, combined.done_reason, require_raw_transcript=True
    )
    raw = parsed.raw_transcript if isinstance(parsed, ParsedOutput) else None
    return _Extracted(parsed, raw)


def score_generation(
    record: GenerationRecord, subject: Utterance | Control
) -> GenerationScore:
    extracted = _extract(record)
    parsed = extracted.parsed
    errored = record.error is not None or parsed is None
    output = parsed if isinstance(parsed, ParsedOutput) else None
    failure = parsed.failure if isinstance(parsed, ParseFailure) else None
    common = {
        "subject_id": record.subject_id,
        "arm": record.arm,
        "seed": record.seed,
        "errored": errored,
        "valid": output is not None and record.error is None,
        "failure": failure,
        "verdict": output.verdict if output else None,
        "total_seconds": record.total_seconds,
        "cold": record.is_cold,
    }
    if isinstance(subject, Control):
        fabricated = (
            output is not None
            and output.verdict is Verdict.SEND
            and bool(output.sanitized_text.strip())
        )
        return _score(common, is_control=True, fabrication=fabricated)
    return _score_utterance(common, subject, extracted, output)


def _score(common: dict, *, is_control: bool, fabrication: bool) -> GenerationScore:
    return GenerationScore(
        **common,
        is_control=is_control,
        raw_transcript=None,
        wer=None,
        audio_failure=None,
        spans_total=0,
        leaked_span_ids=(),
        leak_renderings=(),
        mapping_checked=0,
        mapping_errors=0,
        preservation=None,
        false_refusal=False,
        missed_refusal=False,
        fabrication=fabrication,
    )


def _score_utterance(
    common: dict,
    utterance: Utterance,
    extracted: _Extracted,
    output: ParsedOutput | None,
) -> GenerationScore:
    raw = extracted.raw_transcript
    wer = word_error_rate(utterance.text, raw) if raw is not None else None
    audio_failure = (
        looks_like_audio_failure(raw, utterance.text) if raw is not None else None
    )
    sent = output is not None and output.verdict is Verdict.SEND
    spans_total = 0
    leaked: list[tuple[Span, str]] = []
    mapping_checked = mapping_errors = 0
    preservation = None
    if output is not None and sent:
        spans_total = len(utterance.spans)
        leaked = leaked_spans(utterance.spans, output.sanitized_text)
        leaked_ids = {span.span_id for span, _ in leaked}
        for span in utterance.spans:
            if span.span_id in leaked_ids:
                continue
            mapping_checked += 1
            if not mapping_matches(span, output.mapping):
                mapping_errors += 1
        if utterance.expected_verdict is Verdict.SEND:
            preservation = meaning_preservation(utterance, output.sanitized_text)
    expected = utterance.expected_verdict
    return GenerationScore(
        **common,
        is_control=False,
        raw_transcript=raw,
        wer=wer,
        audio_failure=audio_failure,
        spans_total=spans_total,
        leaked_span_ids=tuple(span.span_id for span, _ in leaked),
        leak_renderings=tuple(how for _, how in leaked),
        mapping_checked=mapping_checked,
        mapping_errors=mapping_errors,
        preservation=preservation,
        false_refusal=(
            output is not None
            and expected is Verdict.SEND
            and output.verdict is Verdict.REFUSE
        ),
        missed_refusal=(output is not None and expected is Verdict.REFUSE and sent),
        fabrication=False,
    )


def score_records(
    records: list[GenerationRecord], controls: tuple[Control, ...]
) -> list[GenerationScore]:
    control_by_id = {control.control_id: control for control in controls}
    scores = []
    for record in records:
        subject = control_by_id.get(record.subject_id)
        scores.append(
            score_generation(record, subject or utterance_by_id(record.subject_id))
        )
    return scores


@dataclass(frozen=True)
class ArmMetrics:
    arm: Arm
    generations: int
    valid: int
    failure_counts: dict[str, int]
    audio_failures: int
    median_wer: float | None
    spans_total: int
    spans_leaked: int
    sent_generations_with_spans: int
    sent_generations_with_leak: int
    leak_renderings: dict[str, int]
    mapping_checked: int
    mapping_errors: int
    mean_preservation: float | None
    false_refusals: int
    missed_refusals: int
    control_generations: int
    fabrications: int
    warm_generations: int
    cold_generations: int
    median_seconds: float | None
    p90_seconds: float | None

    @property
    def validity(self) -> float:
        return self.valid / self.generations if self.generations else 0.0

    @property
    def audio_failure_rate(self) -> float:
        return self.audio_failures / self.generations if self.generations else 0.0

    @property
    def leak_rate(self) -> float:
        return self.spans_leaked / self.spans_total if self.spans_total else 0.0

    @property
    def mapping_error_rate(self) -> float:
        if not self.mapping_checked:
            return 0.0
        return self.mapping_errors / self.mapping_checked


def percentile_nearest_rank(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def aggregate(arm: Arm, scores: list[GenerationScore]) -> ArmMetrics:
    mine = [score for score in scores if score.arm is arm]
    utterance_scores = [score for score in mine if not score.is_control]
    control_scores = [score for score in mine if score.is_control]
    wers = [s.wer for s in utterance_scores if s.wer is not None]
    preservations = [
        s.preservation for s in utterance_scores if s.preservation is not None
    ]
    warm = [s.total_seconds for s in utterance_scores if not s.cold]
    with_spans = [s for s in utterance_scores if s.spans_total]
    renderings = Counter(r for s in utterance_scores for r in s.leak_renderings)
    return ArmMetrics(
        arm=arm,
        generations=len(utterance_scores),
        valid=sum(1 for s in utterance_scores if s.valid),
        failure_counts=dict(
            Counter(s.failure.value for s in utterance_scores if s.failure)
        ),
        audio_failures=sum(1 for s in utterance_scores if s.audio_failure),
        median_wer=statistics.median(wers) if wers else None,
        spans_total=sum(s.spans_total for s in utterance_scores),
        spans_leaked=sum(len(s.leaked_span_ids) for s in utterance_scores),
        sent_generations_with_spans=len(with_spans),
        sent_generations_with_leak=sum(1 for s in with_spans if s.leaked_span_ids),
        leak_renderings=dict(renderings),
        mapping_checked=sum(s.mapping_checked for s in utterance_scores),
        mapping_errors=sum(s.mapping_errors for s in utterance_scores),
        mean_preservation=statistics.fmean(preservations) if preservations else None,
        false_refusals=sum(1 for s in utterance_scores if s.false_refusal),
        missed_refusals=sum(1 for s in utterance_scores if s.missed_refusal),
        control_generations=len(control_scores),
        fabrications=sum(1 for s in control_scores if s.fabrication),
        warm_generations=len(warm),
        cold_generations=len(utterance_scores) - len(warm),
        median_seconds=statistics.median(warm) if warm else None,
        p90_seconds=percentile_nearest_rank(warm, 0.9),
    )


def leak_breakdown(
    arm: Arm, scores: list[GenerationScore]
) -> dict[str, tuple[int, int]]:
    """(leaked, total) per "type/class" over the spans of sent generations."""
    totals: Counter[str] = Counter()
    leaks: Counter[str] = Counter()
    for score in scores:
        if score.arm is not arm or score.is_control or not score.spans_total:
            continue
        for span in utterance_by_id(score.subject_id).spans:
            label = f"{span.type.value}/{span.cls.value}"
            totals[label] += 1
            if span.span_id in score.leaked_span_ids:
                leaks[label] += 1
    return {label: (leaks[label], totals[label]) for label in sorted(totals)}
