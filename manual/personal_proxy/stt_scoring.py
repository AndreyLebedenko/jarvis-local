"""Pure scoring, decision rule, and report of the STT engine spike v2.1.0-5.

No engine and no Ollama here; the card is
tasks/spike-v2.1.0-5-stt-engines.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from statistics import median

from manual.personal_proxy.corpus import Span, SpanType, Utterance
from manual.personal_proxy.scoring import (
    leaked_spans,
    looks_like_audio_failure,
    percentile_nearest_rank,
)
from manual.personal_proxy.text import word_error_rate
from manual.personal_proxy.transcription_ab import reference_text

MAX_FAILURES = 8
MAX_CPU_OR_COEXIST_SECONDS = 3.0
MAX_SLOWDOWN_FACTOR = 2.0
FAILURE_TIE_MARGIN = 3
FIDELITY_TIE_MARGIN = 0.02
SPEED_TIE_FACTOR = 1.5
GROUPS = ("numeric", "email", "person", "other")

_WORD_CHARACTER = re.compile(r"\w", re.UNICODE)


class Engine(StrEnum):
    WHISPER_RU = "whisper_ru"
    WHISPER_AUTO = "whisper_auto"
    GIGAAM = "gigaam"
    WHISPER_RU_CPU = "whisper_ru_cpu"
    GIGAAM_CPU = "gigaam_cpu"


class Outcome(StrEnum):
    NONE_ADEQUATE = "none_adequate"
    WHISPER = "whisper"
    GIGAAM = "gigaam"
    OWNER = "owner"


def span_group(span: Span) -> str:
    if span.type is SpanType.EMAIL:
        return "email"
    if span.all_digit_keys():
        return "numeric"
    if span.type is SpanType.PERSON:
        return "person"
    return "other"


@dataclass(frozen=True)
class EngineScore:
    engine: Engine
    subject_id: str
    pass_no: int
    transcript: str
    reference: str
    wer: float
    audio_failure: bool
    found_by_group: tuple[tuple[str, int, int], ...]
    seconds: float
    audio_seconds: float


def score_transcript(
    engine: Engine,
    utterance: Utterance,
    pass_no: int,
    transcript: str,
    seconds: float,
    audio_seconds: float,
) -> EngineScore:
    reference = reference_text(utterance)
    found = {id(s) for s, _ in leaked_spans(utterance.spans, transcript)}
    totals: dict[str, list[int]] = {g: [0, 0] for g in GROUPS}
    for span in utterance.spans:
        group = totals[span_group(span)]
        group[1] += 1
        group[0] += id(span) in found
    return EngineScore(
        engine,
        utterance.utterance_id,
        pass_no,
        transcript,
        reference,
        word_error_rate(reference, transcript),
        looks_like_audio_failure(transcript, reference),
        tuple((g, totals[g][0], totals[g][1]) for g in GROUPS),
        seconds,
        audio_seconds,
    )


def control_is_clean(transcript: str) -> bool:
    return _WORD_CHARACTER.search(transcript) is None


def fidelity_by_group(
    pairs: list[tuple[Utterance, str]],
) -> dict[str, tuple[int, int]]:
    """Found/total sensitive spans for (utterance, transcript) pairs; used for
    the Gemma baseline, whose transcripts come from an earlier spike."""
    totals: dict[str, list[int]] = {g: [0, 0] for g in GROUPS}
    for utterance, transcript in pairs:
        found = {id(s) for s, _ in leaked_spans(utterance.spans, transcript)}
        for span in utterance.spans:
            group = totals[span_group(span)]
            group[1] += 1
            group[0] += id(span) in found
    return {g: (v[0], v[1]) for g, v in totals.items()}


def overall_fidelity(groups: dict[str, tuple[int, int]]) -> float | None:
    found = sum(f for f, _ in groups.values())
    total = sum(t for _, t in groups.values())
    return None if total == 0 else found / total


@dataclass(frozen=True)
class EngineMetrics:
    engine: Engine
    generations: int
    audio_failures: int
    median_wer: float | None
    fidelity: dict[str, tuple[int, int]]
    median_seconds: float | None
    p90_seconds: float | None
    median_rtf: float | None

    @property
    def overall_fidelity(self) -> float | None:
        return overall_fidelity(self.fidelity)


def aggregate(engine: Engine, scores: list[EngineScore]) -> EngineMetrics:
    own = [s for s in scores if s.engine is engine]
    fidelity: dict[str, tuple[int, int]] = {}
    for group in GROUPS:
        found = total = 0
        for s in own:
            for name, f, t in s.found_by_group:
                if name == group:
                    found += f
                    total += t
        fidelity[group] = (found, total)
    warm = [s for s in own if s.pass_no == 2]
    seconds = [s.seconds for s in warm]
    return EngineMetrics(
        engine,
        len(own),
        sum(1 for s in own if s.audio_failure),
        median(s.wer for s in own) if own else None,
        fidelity,
        median(seconds) if seconds else None,
        percentile_nearest_rank(seconds, 0.9) if seconds else None,
        median(s.seconds / s.audio_seconds for s in warm) if warm else None,
    )


@dataclass(frozen=True)
class Coexistence:
    engine: Engine
    gpu_share_before: float | None
    gpu_share_after: float | None
    engine_median_seconds: float | None
    isolated_median_seconds: float | None
    gemma_seconds_before: float | None
    gemma_seconds_after: float | None


def resource_ok(co: Coexistence | None) -> bool:
    if co is None or co.engine_median_seconds is None:
        return False
    if co.gpu_share_after != 1.0:
        return False
    if co.engine_median_seconds > MAX_CPU_OR_COEXIST_SECONDS:
        return False
    isolated = co.isolated_median_seconds
    return (
        isolated is None or co.engine_median_seconds <= isolated * MAX_SLOWDOWN_FACTOR
    )


def cpu_resource_ok(metrics: EngineMetrics) -> bool:
    return (
        metrics.median_seconds is not None
        and metrics.median_seconds <= MAX_CPU_OR_COEXIST_SECONDS
    )


@dataclass(frozen=True)
class Adequacy:
    accuracy: bool
    fidelity: bool
    resources: bool

    @property
    def adequate(self) -> bool:
        return self.accuracy and self.fidelity and self.resources


def adequacy(
    metrics: EngineMetrics, baseline_fidelity: float | None, resources: bool
) -> Adequacy:
    fidelity = metrics.overall_fidelity
    return Adequacy(
        metrics.audio_failures <= MAX_FAILURES,
        fidelity is not None
        and (baseline_fidelity is None or fidelity >= baseline_fidelity),
        resources,
    )


def choose(
    whisper: EngineMetrics | None,
    gigaam: EngineMetrics | None,
    whisper_ok: bool,
    gigaam_ok: bool,
) -> Outcome:
    if not whisper_ok and not gigaam_ok:
        return Outcome.NONE_ADEQUATE
    if whisper_ok != gigaam_ok:
        return Outcome.WHISPER if whisper_ok else Outcome.GIGAAM
    assert whisper is not None and gigaam is not None
    gap = whisper.audio_failures - gigaam.audio_failures
    if abs(gap) >= FAILURE_TIE_MARGIN:
        return Outcome.GIGAAM if gap > 0 else Outcome.WHISPER
    w_fid, g_fid = whisper.overall_fidelity, gigaam.overall_fidelity
    if (
        w_fid is not None
        and g_fid is not None
        and abs(w_fid - g_fid) >= FIDELITY_TIE_MARGIN
    ):
        return Outcome.WHISPER if w_fid > g_fid else Outcome.GIGAAM
    w_sec, g_sec = whisper.median_seconds, gigaam.median_seconds
    if w_sec and g_sec:
        if g_sec * SPEED_TIE_FACTOR <= w_sec:
            return Outcome.GIGAAM
        if w_sec * SPEED_TIE_FACTOR <= g_sec:
            return Outcome.WHISPER
    return Outcome.OWNER


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _clip(text: str, limit: int = 110) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "..."


def _fidelity_cell(groups: dict[str, tuple[int, int]], group: str) -> str:
    found, total = groups[group]
    return f"{found}/{total}"


def _metrics_table(
    metrics: list[EngineMetrics],
    baseline: dict[str, tuple[int, int]],
    baseline_failures: int,
    baseline_wer: float | None,
) -> list[str]:
    header = ["metric", "gemma baseline A", *[m.engine.value for m in metrics]]
    rows = [
        (
            "audio failures of 88",
            [str(baseline_failures)] + [str(m.audio_failures) for m in metrics],
        ),
        ("median WER", [_fmt(baseline_wer)] + [_fmt(m.median_wer) for m in metrics]),
        (
            "span fidelity (overall)",
            [_fmt(overall_fidelity(baseline))]
            + [_fmt(m.overall_fidelity) for m in metrics],
        ),
    ]
    rows += [
        (
            f"  {group}",
            [_fidelity_cell(baseline, group)]
            + [_fidelity_cell(m.fidelity, group) for m in metrics],
        )
        for group in GROUPS
    ]
    rows += [
        (
            "median seconds (warm)",
            ["n/a"] + [_fmt(m.median_seconds, 2) for m in metrics],
        ),
        ("p90 seconds (warm)", ["n/a"] + [_fmt(m.p90_seconds, 2) for m in metrics]),
        ("median real-time factor", ["n/a"] + [_fmt(m.median_rtf, 3) for m in metrics]),
    ]
    table = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return table + ["| " + " | ".join([name, *cells]) + " |" for name, cells in rows]


def _coexistence_lines(coexistence: list[Coexistence]) -> list[str]:
    if not coexistence:
        return ["not run"]
    return [
        f"- {co.engine.value}: Ollama GPU share {co.gpu_share_before} -> "
        f"{co.gpu_share_after}; engine median "
        f"{_fmt(co.engine_median_seconds, 2)} s (isolated "
        f"{_fmt(co.isolated_median_seconds, 2)} s); Gemma text request "
        f"{_fmt(co.gemma_seconds_before, 2)} s -> "
        f"{_fmt(co.gemma_seconds_after, 2)} s"
        for co in coexistence
    ]


def _failure_lines(engine: Engine, scores: list[EngineScore]) -> list[str]:
    failing = sorted(
        (s for s in scores if s.engine is engine and s.audio_failure),
        key=lambda s: (s.subject_id, s.pass_no),
    )
    if not failing:
        return ["none"]
    return [
        f"- {s.subject_id}/p{s.pass_no} WER={s.wer:.2f}\n"
        f"  expected: {_clip(s.reference)}\n"
        f"  actual:   {_clip(s.transcript)}"
        for s in failing
    ]


def _decision_lines(
    metrics: list[EngineMetrics],
    adequacies: dict[Engine, Adequacy],
    outcome: Outcome,
) -> list[str]:
    lines = [f"Outcome: **{outcome.value.upper()}**"]
    for m in metrics:
        a = adequacies.get(m.engine)
        if a is not None:
            lines.append(
                f"- {m.engine.value}: accuracy {a.accuracy}, fidelity "
                f"{a.fidelity}, resources {a.resources} -> adequate {a.adequate}"
            )
    return lines


def render_report(
    *,
    meta: dict[str, object],
    metrics: list[EngineMetrics],
    scores: list[EngineScore],
    controls: dict[Engine, list[tuple[str, bool]]],
    baseline: dict[str, tuple[int, int]],
    baseline_failures: int,
    baseline_wer: float | None,
    adequacies: dict[Engine, Adequacy],
    outcome: Outcome,
    memory: dict[Engine, dict[str, object]],
    coexistence: list[Coexistence],
) -> str:
    lines = ["# STT engines (spike v2.1.0-5): report", "", "## Run", ""]
    lines += [f"- {key}: {meta[key]}" for key in sorted(meta)]
    lines += ["", "## Decision (frozen rule)", ""]
    lines += _decision_lines(metrics, adequacies, outcome)
    lines += ["", *_metrics_table(metrics, baseline, baseline_failures, baseline_wer)]
    lines += ["", "## Memory (machine GPU memory, Ollama model unloaded)", ""]
    lines += [f"- {engine.value}: {info}" for engine, info in memory.items()]
    lines += ["", "## Coexistence with Gemma (production options)", ""]
    lines += _coexistence_lines(coexistence)
    for m in metrics:
        lines += ["", f"## Audio failures, {m.engine.value}", ""]
        lines += _failure_lines(m.engine, scores)
    lines += ["", "## Controls (silence, noise): the transcript must be empty", ""]
    lines += [
        f"- {engine.value}: {'clean' if clean else 'TEXT'}: {_clip(text, 80)!r}"
        for engine, outputs in controls.items()
        for text, clean in outputs
    ]
    lines += [
        "",
        "Reported only, never part of the rule: controls, whisper_auto, group "
        "fidelity, p90 and real-time factor, memory.",
        "",
    ]
    return "\n".join(lines)
