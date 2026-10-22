"""Short spoken answers through the real speech path (handoff A of task
v2.1.0-8): what Whisper hears for one-word answers, what the classifier makes of
it, and whether the speech guard keeps the clip. Pure; the harness supplies the
clips, the engine and the voice-activity probabilities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean

import numpy as np

from jarvis.personal_proxy.confirmation_vocabulary import AnswerKind, classify_answer
from jarvis.personal_proxy.guarded_transcription import (
    ProbabilitySource,
    transcribe_guarded,
)
from jarvis.personal_proxy.speech_guard import NoSpeech, speech_seconds
from jarvis.personal_proxy.stt_engine import SpeechEngine

REPETITIONS = 10


@dataclass(frozen=True)
class Phrase:
    text: str
    expected: AnswerKind


PHRASES: tuple[Phrase, ...] = (
    Phrase("да", AnswerKind.YES),
    Phrase("нет", AnswerKind.NO),
    Phrase("отправляй", AnswerKind.YES),
    Phrase("стоп", AnswerKind.NO),
    Phrase("yes", AnswerKind.YES),
    Phrase("no", AnswerKind.NO),
    Phrase("да, но исправь", AnswerKind.UNCLEAR),
    Phrase("сегодня хорошая погода", AnswerKind.UNCLEAR),
)


@dataclass(frozen=True)
class Trial:
    phrase: str
    expected: AnswerKind
    speech_seconds: float
    rejected: bool
    text: str
    kind: AnswerKind


def measure(
    phrase: Phrase,
    clip: np.ndarray,
    engine: SpeechEngine,
    probabilities: ProbabilitySource,
    *,
    vad_threshold: float,
    minimum_speech_seconds: float,
) -> Trial:
    heard = speech_seconds(probabilities(clip), vad_threshold)
    result = transcribe_guarded(
        clip,
        engine,
        probabilities,
        vad_threshold=vad_threshold,
        minimum_speech_seconds=minimum_speech_seconds,
    )
    if isinstance(result, NoSpeech):
        return Trial(phrase.text, phrase.expected, heard, True, "", AnswerKind.UNCLEAR)
    return Trial(
        phrase.text,
        phrase.expected,
        heard,
        False,
        result.text,
        classify_answer(result.text),
    )


def render_trial(number: int, trial: Trial) -> str:
    guard = "REJECTED" if trial.rejected else "ok"
    return (
        f"{number:>3}. said {trial.phrase!r}: whisper {trial.text!r} -> "
        f"{trial.kind.value} (expected {trial.expected.value}); "
        f"speech {trial.speech_seconds:.2f} s; guard: {guard}"
    )


@dataclass(frozen=True)
class PhraseSummary:
    phrase: str
    expected: AnswerKind
    trials: int
    rejected: int
    yes: int
    no: int
    unclear: int
    as_expected: int
    false_yes: int
    least_speech_seconds: float
    mean_speech_seconds: float


def _summary_of(phrase: str, trials: Sequence[Trial]) -> PhraseSummary:
    expected = trials[0].expected
    seconds = [trial.speech_seconds for trial in trials]
    return PhraseSummary(
        phrase=phrase,
        expected=expected,
        trials=len(trials),
        rejected=sum(trial.rejected for trial in trials),
        yes=sum(trial.kind is AnswerKind.YES for trial in trials),
        no=sum(trial.kind is AnswerKind.NO for trial in trials),
        unclear=sum(trial.kind is AnswerKind.UNCLEAR for trial in trials),
        as_expected=sum(trial.kind is expected for trial in trials),
        false_yes=(
            0
            if expected is AnswerKind.YES
            else sum(trial.kind is AnswerKind.YES for trial in trials)
        ),
        least_speech_seconds=min(seconds),
        mean_speech_seconds=mean(seconds),
    )


def summarize(trials: Sequence[Trial]) -> list[PhraseSummary]:
    by_phrase: dict[str, list[Trial]] = {}
    for trial in trials:
        by_phrase.setdefault(trial.phrase, []).append(trial)
    return [_summary_of(phrase, group) for phrase, group in by_phrase.items()]


def render(summaries: Sequence[PhraseSummary]) -> str:
    lines = [
        "phrase | expected | trials | as expected | yes/no/unclear | "
        "guard rejected | false yes | speech s (least / mean)",
        "---|---|---|---|---|---|---|---",
    ]
    for s in summaries:
        lines.append(
            f"{s.phrase} | {s.expected.value} | {s.trials} | {s.as_expected} | "
            f"{s.yes}/{s.no}/{s.unclear} | {s.rejected} | {s.false_yes} | "
            f"{s.least_speech_seconds:.2f} / {s.mean_speech_seconds:.2f}"
        )
    total_false_yes = sum(s.false_yes for s in summaries)
    lines.append(
        f"false yes in total (a yes heard for a non-yes phrase): {total_false_yes}"
    )
    return "\n".join(lines)
