"""Scoring and decision of spike v2.1.0-11 (text-only sanitize pass).

Pure logic. The span matching, parser and preservation measure are spike 1's;
the one change is that spans the engine lost (not recognisable in the input
text) are listed and kept out of every rate.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from manual.personal_proxy.corpus import Utterance, Verdict
from manual.personal_proxy.parse import (
    ParsedOutput,
    ParseFailure,
    parse_sanitize_output,
)
from manual.personal_proxy.scoring import (
    MIN_CONTENT_TOKEN_LENGTH,
    leaked_spans,
    mapping_matches,
    meaning_preservation,
    percentile_nearest_rank,
)
from manual.personal_proxy.text import stem_present, tokenize

MIN_VALIDITY = 0.97
MAX_LEAK_RATE = 0.107
MAX_MAPPING_ERROR_RATE = 0.29
MIN_PRESERVATION = 0.603
MAX_FALSE_REFUSAL_RATE = 0.15
MAX_MISSED_REFUSALS = 1
CLOSE_VALIDITY = 0.90
CLOSE_LEAK_RATE = 0.15


@dataclass(frozen=True)
class SanitizeScore:
    subject_id: str
    arm: str
    seed: int
    valid: bool
    verdict: Verdict | None
    expected_verdict: Verdict
    recognisable: tuple[str, ...]
    lost: tuple[str, ...]
    leaked: tuple[str, ...]
    leak_renderings: tuple[str, ...]
    mapping_checked: int
    mapping_errors: int
    preservation: float | None
    input_preservation: float | None
    seconds: float

    @property
    def sent(self) -> bool:
        return self.verdict is Verdict.SEND

    @property
    def false_refusal(self) -> bool:
        return self.verdict is Verdict.REFUSE and self.expected_verdict is Verdict.SEND

    @property
    def missed_refusal(self) -> bool:
        return self.sent and self.expected_verdict is Verdict.REFUSE


def input_preservation(
    utterance: Utterance, input_text: str, sanitized_text: str
) -> float | None:
    """Share of the input's non-sensitive content words kept by the pass."""
    span_tokens = {t for span in utterance.spans for t in tokenize(span.surface)}
    content = [
        t
        for t in tokenize(input_text)
        if len(t) >= MIN_CONTENT_TOKEN_LENGTH and t not in span_tokens
    ]
    if not content:
        return None
    sanitized = tokenize(sanitized_text)
    return sum(1 for t in content if stem_present(t, sanitized)) / len(content)


def score_call(
    utterance: Utterance,
    arm: str,
    seed: int,
    input_text: str,
    response_text: str,
    done_reason: str | None,
    seconds: float,
) -> SanitizeScore:
    parsed = parse_sanitize_output(
        response_text, done_reason, require_raw_transcript=False
    )
    output = parsed if isinstance(parsed, ParsedOutput) else None
    in_input = {span.span_id for span, _ in leaked_spans(utterance.spans, input_text)}
    recognisable = tuple(s for s in utterance.spans if s.span_id in in_input)
    lost = tuple(s.span_id for s in utterance.spans if s.span_id not in in_input)
    common = {
        "subject_id": utterance.utterance_id,
        "arm": arm,
        "seed": seed,
        "valid": output is not None,
        "verdict": output.verdict if output else None,
        "expected_verdict": utterance.expected_verdict,
        "recognisable": tuple(s.span_id for s in recognisable),
        "lost": lost,
        "seconds": seconds,
    }
    if output is None or output.verdict is not Verdict.SEND:
        return SanitizeScore(
            **common,
            leaked=(),
            leak_renderings=(),
            mapping_checked=0,
            mapping_errors=0,
            preservation=None,
            input_preservation=None,
        )
    leaks = leaked_spans(recognisable, output.sanitized_text)
    leaked_ids = {span.span_id for span, _ in leaks}
    kept = [s for s in recognisable if s.span_id not in leaked_ids]
    wanted_preservation = utterance.expected_verdict is Verdict.SEND
    return SanitizeScore(
        **common,
        leaked=tuple(span.span_id for span, _ in leaks),
        leak_renderings=tuple(how for _, how in leaks),
        mapping_checked=len(kept),
        mapping_errors=sum(1 for s in kept if not mapping_matches(s, output.mapping)),
        preservation=(
            meaning_preservation(utterance, output.sanitized_text)
            if wanted_preservation
            else None
        ),
        input_preservation=(
            input_preservation(utterance, input_text, output.sanitized_text)
            if wanted_preservation
            else None
        ),
    )


def parse_failure(response_text: str, done_reason: str | None) -> str | None:
    parsed = parse_sanitize_output(
        response_text, done_reason, require_raw_transcript=False
    )
    return parsed.failure.value if isinstance(parsed, ParseFailure) else None


@dataclass(frozen=True)
class Totals:
    generations: int
    valid: int
    spans_recognisable: int
    spans_lost: int
    spans_leaked: int
    mapping_checked: int
    mapping_errors: int
    mean_preservation: float | None
    mean_input_preservation: float | None
    send_expected: int
    false_refusals: int
    missed_refusals: int
    median_seconds: float | None
    p90_seconds: float | None

    @property
    def validity(self) -> float:
        return self.valid / self.generations if self.generations else 0.0

    @property
    def leak_rate(self) -> float:
        if not self.spans_recognisable:
            return 0.0
        return self.spans_leaked / self.spans_recognisable

    @property
    def mapping_error_rate(self) -> float:
        if not self.mapping_checked:
            return 0.0
        return self.mapping_errors / self.mapping_checked

    @property
    def false_refusal_rate(self) -> float:
        return self.false_refusals / self.send_expected if self.send_expected else 0.0


def aggregate(scores: list[SanitizeScore]) -> Totals:
    sent = [s for s in scores if s.sent]
    preservations = [s.preservation for s in scores if s.preservation is not None]
    input_preservations = [
        s.input_preservation for s in scores if s.input_preservation is not None
    ]
    seconds = [s.seconds for s in scores]
    return Totals(
        generations=len(scores),
        valid=sum(1 for s in scores if s.valid),
        spans_recognisable=sum(len(s.recognisable) for s in sent),
        spans_lost=sum(len(s.lost) for s in scores),
        spans_leaked=sum(len(s.leaked) for s in sent),
        mapping_checked=sum(s.mapping_checked for s in scores),
        mapping_errors=sum(s.mapping_errors for s in scores),
        mean_preservation=(statistics.fmean(preservations) if preservations else None),
        mean_input_preservation=(
            statistics.fmean(input_preservations) if input_preservations else None
        ),
        send_expected=sum(1 for s in scores if s.expected_verdict is Verdict.SEND),
        false_refusals=sum(1 for s in scores if s.false_refusal),
        missed_refusals=sum(1 for s in scores if s.missed_refusal),
        median_seconds=statistics.median(seconds) if seconds else None,
        p90_seconds=percentile_nearest_rank(seconds, 0.9),
    )


@dataclass(frozen=True)
class Criterion:
    name: str
    value: float
    limit: str
    passed: bool


@dataclass(frozen=True)
class Decision:
    verdict: str
    criteria: tuple[Criterion, ...]


def decide(totals: Totals) -> Decision:
    preservation = totals.mean_preservation or 0.0
    criteria = (
        Criterion(
            "validity",
            totals.validity,
            f">= {MIN_VALIDITY}",
            totals.validity >= MIN_VALIDITY,
        ),
        Criterion(
            "leak rate",
            totals.leak_rate,
            f"<= {MAX_LEAK_RATE}",
            totals.leak_rate <= MAX_LEAK_RATE,
        ),
        Criterion(
            "mapping error rate",
            totals.mapping_error_rate,
            f"<= {MAX_MAPPING_ERROR_RATE}",
            totals.mapping_error_rate <= MAX_MAPPING_ERROR_RATE,
        ),
        Criterion(
            "meaning preservation",
            preservation,
            f">= {MIN_PRESERVATION}",
            preservation >= MIN_PRESERVATION,
        ),
        Criterion(
            "false refusal rate",
            totals.false_refusal_rate,
            f"<= {MAX_FALSE_REFUSAL_RATE}",
            totals.false_refusal_rate <= MAX_FALSE_REFUSAL_RATE,
        ),
        Criterion(
            "missed refusals",
            float(totals.missed_refusals),
            f"<= {MAX_MISSED_REFUSALS}",
            totals.missed_refusals <= MAX_MISSED_REFUSALS,
        ),
    )
    if totals.validity < CLOSE_VALIDITY or totals.leak_rate > CLOSE_LEAK_RATE:
        return Decision("Close", criteria)
    if all(c.passed for c in criteria):
        return Decision("Go", criteria)
    return Decision("Owner", criteria)
