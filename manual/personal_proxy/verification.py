"""Pure logic of spike v2.1.0-7: Gemma checks a Whisper transcript against audio.

Prompt, request, scoring, and the frozen decision rule; no Ollama here. The
card is tasks/done/spike-v2.1.0-7-stt-audio-check.md.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import Any

from manual.personal_proxy.corpus import Utterance
from manual.personal_proxy.scoring import leaked_spans, looks_like_audio_failure
from manual.personal_proxy.stt_scoring import fidelity_by_group, overall_fidelity
from manual.personal_proxy.text import word_error_rate
from manual.personal_proxy.transcription_ab import reference_text

NUM_PREDICT = 2048
MAX_FAILURE_INCREASE = 2
WORSE_FAILURE_INCREASE = 4
MIN_FIDELITY_GAIN = 0.03
WORSE_FIDELITY_DROP = 0.02
TEXT_ONLY_TIE_MARGIN = 0.02
_EPSILON = 1e-9

ERROR_HINT = (
    "The engine is reliable on ordinary words but tends to make these mistakes: "
    "e-mail addresses, logins, and web addresses spoken letter by letter come out "
    "glued into one word or mangled; digits in phone, card, account, and passport "
    "numbers are dropped, merged, or changed; names of people and organizations, "
    "especially foreign ones, are respelled or changed, including Latin names "
    "written in Cyrillic; on silence or noise it may invent a phrase."
)
RULES = (
    "Fix only what is evidently wrong. Do not add, remove, paraphrase, translate, "
    "or interpret anything. Output only the corrected transcript, nothing else. "
    "If there is no speech, output nothing."
)


class Variant(StrEnum):
    AUDIO = "x_audio"
    TEXT = "z_text"


class Verdict(StrEnum):
    BETTER = "better"
    BETTER_WITHOUT_AUDIO = "better_without_audio"
    WORSE = "worse"
    NO_DIFFERENCE = "no_difference"


def build_prompt(variant: Variant, transcript: str) -> str:
    if variant is Variant.AUDIO:
        head = (
            "A speech-to-text engine produced the transcript below from the "
            "attached recording. Listen to the recording and check the transcript "
            "against it."
        )
    else:
        head = (
            "A speech-to-text engine produced the transcript below from a "
            "recording you cannot hear. Check the transcript."
        )
    return f"{head}\n\n{ERROR_HINT}\n\n{RULES}\n\nTranscript:\n{transcript}"


def build_payload(
    variant: Variant,
    transcript: str,
    audio: bytes | None,
    options: dict[str, Any],
    seed: int,
    model: str,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "user",
        "content": build_prompt(variant, transcript),
    }
    if variant is Variant.AUDIO and audio is not None:
        message["images"] = [base64.b64encode(audio).decode("ascii")]
    return {
        "model": model,
        "messages": [message],
        "stream": False,
        "think": False,
        "options": {**options, "seed": seed, "num_predict": NUM_PREDICT},
    }


@dataclass(frozen=True)
class Metrics:
    generations: int
    audio_failures: int
    median_wer: float | None
    fidelity: dict[str, tuple[int, int]]

    @property
    def overall_fidelity(self) -> float | None:
        return overall_fidelity(self.fidelity)


def score_transcripts(pairs: list[tuple[Utterance, str]]) -> Metrics:
    wers = []
    failures = 0
    for utterance, transcript in pairs:
        reference = reference_text(utterance)
        wers.append(word_error_rate(reference, transcript))
        failures += looks_like_audio_failure(transcript, reference)
    return Metrics(
        len(pairs),
        failures,
        median(wers) if wers else None,
        fidelity_by_group(pairs),
    )


def _found(utterance: Utterance, transcript: str) -> set[int]:
    return {id(s) for s, _ in leaked_spans(utterance.spans, transcript)}


def paired_spans(triples: list[tuple[Utterance, str, str]]) -> tuple[int, int]:
    """(fixed, broken): spans newly found in `after`, and spans lost from `before`."""
    fixed = broken = 0
    for utterance, before, after in triples:
        was, now = _found(utterance, before), _found(utterance, after)
        fixed += len(now - was)
        broken += len(was - now)
    return fixed, broken


def decide(whisper: Metrics, audio: Metrics, text: Metrics) -> Verdict:
    base = whisper.overall_fidelity or 0.0
    with_audio = audio.overall_fidelity or 0.0
    without = text.overall_fidelity or 0.0
    if (
        with_audio <= base - WORSE_FIDELITY_DROP + _EPSILON
        or audio.audio_failures >= whisper.audio_failures + WORSE_FAILURE_INCREASE
    ):
        return Verdict.WORSE
    gained = with_audio >= base + MIN_FIDELITY_GAIN - _EPSILON
    few_failures = audio.audio_failures <= whisper.audio_failures + MAX_FAILURE_INCREASE
    if not (gained and few_failures):
        return Verdict.NO_DIFFERENCE
    if without >= with_audio - TEXT_ONLY_TIE_MARGIN + _EPSILON:
        return Verdict.BETTER_WITHOUT_AUDIO
    return Verdict.BETTER


ADDRESS_MARKERS = ("собак", "sobak", "@")


def invented_address(source: str, output: str) -> bool:
    """More addresses in the output than the source has markers for."""
    markers = sum(source.lower().count(m) for m in ADDRESS_MARKERS)
    return output.count("@") > markers


def rewrite_distance(source: str, output: str) -> float:
    return word_error_rate(source, output)
