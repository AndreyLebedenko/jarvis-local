"""Pure logic of spike v2.1.0-8: confidence signals for the speech-to-text step.

Marks, requests, projections, signals, labels, and the frozen classifier rule; no
Ollama and no engine here. The card is tasks/spike-v2.1.0-8-confidence-signals.md.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
from typing import Any

from manual.personal_proxy.address_labels import address_is_right
from manual.personal_proxy.corpus import Span, SpanType, Utterance
from manual.personal_proxy.scoring import leaked_spans
from manual.personal_proxy.verification import (
    ERROR_HINT,
    NUM_PREDICT,
    RULES,
    invented_address,
)

WEAK_WORD_PROBABILITY = 0.5
MIN_RECALL = 0.8
MAX_FALSE_REFUSALS = 0.2
MIN_DIGITS_IN_PROJECTION = 4
LONG_NUMBER_DIGITS = 7
VALID_NUMBER_LENGTHS = {10, 11, 12, 16, 20}
CYRILLIC_SHARE_DROP = 0.5
JUDGE_SEED = 1

_DIGIT_RUN = re.compile(r"\d[\d\s\-]*\d|\d")
_LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
_EMAIL_SHAPE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)*\.[A-Za-z]{2,}")
_LETTER = re.compile(r"[A-Za-zА-яЁё]")
_CYRILLIC = re.compile(r"[А-яЁё]")
_SENTENCE_END = (".", "!", "?")
_PUNCTUATION = " \t\n.,;:!?()[]{}\"'«»"

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "uncertain_fragments": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["uncertain_fragments", "confidence"],
}


def weak_word_marks(
    words: list[tuple[str, float]], threshold: float = WEAK_WORD_PROBABILITY
) -> str:
    parts = [w + "[?]" if p < threshold else w for w, p in words]
    return "".join(parts).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in text.split() if t]


def _is_sentence_initial(tokens: list[str], index: int) -> bool:
    return index == 0 or tokens[index - 1].endswith(_SENTENCE_END)


def _digit_runs(text: str) -> list[str]:
    return [re.sub(r"\D", "", m.group()) for m in _DIGIT_RUN.finditer(text)]


def _email_tokens(text: str) -> list[str]:
    return [t.strip(_PUNCTUATION).lower() for t in _tokens(text) if "@" in t]


def _address_markers(text: str) -> int:
    lowered = text.lower()
    return max(lowered.count("@"), lowered.count("собак") + lowered.count("sobak"))


def _capitalized_cyrillic(token: str) -> bool:
    word = token.strip(_PUNCTUATION)
    return (bool(word) and "А" <= word[0] <= "Я") or word[:1] == "Ё"


def projection(text: str, literal_emails: bool = False) -> frozenset[str]:
    found: set[str] = set()
    for run in _digit_runs(text):
        if len(run) >= MIN_DIGITS_IN_PROJECTION:
            found.add(f"digits:{run}")
    emails = _email_tokens(text)
    without_emails = " ".join(t for t in _tokens(text) if "@" not in t)
    found.update(f"latin:{w.lower()}" for w in _LATIN_WORD.findall(without_emails))
    markers = _address_markers(text)
    if markers:
        found.add(f"addr:{markers}")
    tokens = _tokens(text)
    for index, token in enumerate(tokens):
        if _capitalized_cyrillic(token) and not _is_sentence_initial(tokens, index):
            found.add("name:" + token.strip(_PUNCTUATION).lower()[:4])
    if literal_emails:
        found.update(f"email:{e}" for e in emails)
    return frozenset(found)


def symmetric_difference(a: frozenset[str], b: frozenset[str]) -> int:
    return len(a ^ b)


def mean_pairwise_difference(projections: list[frozenset[str]]) -> float:
    pairs = list(combinations(projections, 2))
    if not pairs:
        return 0.0
    return sum(symmetric_difference(a, b) for a, b in pairs) / len(pairs)


def min_sensitive_probability(words: list[tuple[str, float]]) -> float:
    lowest = 1.0
    tokens = [w.strip() for w, _ in words]
    for index, (_, probability) in enumerate(words):
        token = tokens[index]
        sensitive = (
            any(c.isdigit() for c in token)
            or bool(_LATIN_WORD.search(token))
            or (
                _capitalized_cyrillic(token) and not _is_sentence_initial(tokens, index)
            )
        )
        if sensitive:
            lowest = min(lowest, probability)
    return lowest


def invalid_items(text: str) -> int:
    broken_addresses = sum(
        1 for t in _email_tokens(text) if not _EMAIL_SHAPE.fullmatch(t)
    )
    broken_numbers = sum(
        1
        for run in _digit_runs(text)
        if len(run) >= LONG_NUMBER_DIGITS and len(run) not in VALID_NUMBER_LENGTHS
    )
    return broken_addresses + broken_numbers


def _cyrillic_share(text: str) -> float:
    letters = _LETTER.findall(text)
    if not letters:
        return 0.0
    return len(_CYRILLIC.findall(text)) / len(letters)


def _without_addresses(text: str) -> str:
    return " ".join(t for t in text.split() if "@" not in t)


class LabelRule(StrEnum):
    FROZEN = "frozen"
    ADDRESSES_ARE_LATIN = "addresses_are_latin"
    NAMES_IN_ANY_ALPHABET = "names_in_any_alphabet"
    ADDRESSES_ASSEMBLED = "addresses_assembled"


def _scored_spans(utterance: Utterance, rule: LabelRule) -> tuple[Span, ...]:
    if rule in (LabelRule.FROZEN, LabelRule.ADDRESSES_ARE_LATIN):
        return utterance.spans
    return tuple(
        s
        for s in utterance.spans
        if not (s.type is SpanType.PERSON and _is_latin_only(s))
    )


def _is_latin_only(span: Span) -> bool:
    return bool(span.forms) and not _CYRILLIC.search("".join(span.forms))


def is_bad(
    utterance: Utterance,
    whisper_text: str,
    output: str,
    rule: LabelRule = LabelRule.FROZEN,
) -> bool:
    spans = _scored_spans(utterance, rule)
    lost = len(leaked_spans(spans, output)) < len(spans)
    if rule is LabelRule.FROZEN:
        output_share, whisper_share = (
            _cyrillic_share(output),
            _cyrillic_share(whisper_text),
        )
    else:
        output_share = _cyrillic_share(_without_addresses(output))
        whisper_share = _cyrillic_share(_without_addresses(whisper_text))
    switched = output_share < CYRILLIC_SHARE_DROP * whisper_share
    return lost or switched or _address_is_bad(utterance, whisper_text, output, rule)


def _address_is_bad(
    utterance: Utterance, whisper_text: str, output: str, rule: LabelRule
) -> bool:
    if rule is LabelRule.ADDRESSES_ASSEMBLED:
        verdict = address_is_right(utterance.utterance_id, output)
        if verdict is not None:
            return not verdict
    return invented_address(whisper_text, output)


@dataclass(frozen=True)
class OperatingPoint:
    threshold: float
    recall: float
    false_refusals: float


def operating_points(scores: list[float], bad: list[bool]) -> list[OperatingPoint]:
    bad_total = sum(bad)
    good_total = len(bad) - bad_total
    points = []
    for threshold in sorted(set(scores)):
        flagged = [s >= threshold for s in scores]
        caught = sum(f and b for f, b in zip(flagged, bad, strict=True))
        wrong = sum(f and not b for f, b in zip(flagged, bad, strict=True))
        points.append(
            OperatingPoint(
                threshold,
                caught / bad_total if bad_total else 0.0,
                wrong / good_total if good_total else 0.0,
            )
        )
    return points


def discriminates(
    points: list[OperatingPoint],
    trivial_false_refusals: float,
    control_scores: list[float] | None = None,
) -> bool:
    return any(
        p.recall >= MIN_RECALL
        and p.false_refusals <= MAX_FALSE_REFUSALS
        and p.false_refusals < trivial_false_refusals
        and (not control_scores or min(control_scores) >= p.threshold)
        for p in points
    )


@dataclass(frozen=True)
class JudgeResult:
    confidence: float
    fragments: list[str]


def parse_judge(text: str) -> JudgeResult | None:
    try:
        document = json.loads(text)
        confidence = document["confidence"]
        fragments = document["uncertain_fragments"]
    except (ValueError, KeyError, TypeError):
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return None
    if not 0.0 <= confidence <= 1.0:
        return None
    if not isinstance(fragments, list) or not all(
        isinstance(f, str) for f in fragments
    ):
        return None
    return JudgeResult(float(confidence), fragments)


def _audio_message(content: str, audio: bytes) -> dict[str, Any]:
    return {
        "role": "user",
        "content": content,
        "images": [base64.b64encode(audio).decode("ascii")],
    }


def build_sample_payload(
    marked_transcript: str,
    audio: bytes,
    options: dict[str, Any],
    seed: int,
    model: str,
) -> dict[str, Any]:
    content = (
        "A speech-to-text engine produced the transcript below from the attached "
        "recording. Words followed by [?] were low-confidence for the engine: "
        "check them especially, but do not assume they are wrong. Listen to the "
        "recording and check the transcript against it. Do not output the [?] "
        f"marks.\n\n{ERROR_HINT}\n\n{RULES}\n\nTranscript:\n{marked_transcript}"
    )
    return {
        "model": model,
        "messages": [_audio_message(content, audio)],
        "stream": False,
        "think": False,
        "options": {**options, "seed": seed, "num_predict": NUM_PREDICT},
    }


def build_judge_payload(
    engine_text: str,
    candidate_text: str,
    audio: bytes,
    options: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    content = (
        "Listen to the attached recording. Transcript A comes from a "
        "speech-to-text engine; transcript B is a corrected version of it. "
        "List the fragments of B (quote them exactly) that you are not sure "
        "match what was said, especially numbers, addresses, and names. Then "
        "give one overall confidence between 0.0 and 1.0 that B is a correct and "
        "complete transcript of the speech: 0.0 means a critical failure, 1.0 "
        "means full confidence. Answer as JSON with the fields "
        '"uncertain_fragments" and "confidence".'
        f"\n\nA:\n{engine_text}\n\nB:\n{candidate_text}"
    )
    return {
        "model": model,
        "messages": [_audio_message(content, audio)],
        "stream": False,
        "think": False,
        "format": JUDGE_SCHEMA,
        "options": {
            **options,
            "temperature": 0,
            "seed": JUDGE_SEED,
            "num_predict": NUM_PREDICT,
        },
    }
