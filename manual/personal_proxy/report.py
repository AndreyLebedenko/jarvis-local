"""Markdown report of the personal-proxy spike, from scored generations.

Pure rendering over ArmMetrics and the Decision; ASCII only, as the project's
documentation rule requires.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from manual.personal_proxy.decision import Decision
from manual.personal_proxy.records import Arm
from manual.personal_proxy.scoring import (
    ArmMetrics,
    GenerationScore,
    leak_breakdown,
)

SHORT_CLIP_SECONDS = 2.0
LONG_CLIP_SECONDS = 15.0

ARM_LABEL = {
    Arm.T_PLUS_S: "T+S (two-step baseline)",
    Arm.C_USER: "C-user (combined, rules in the user turn)",
    Arm.C_SYSTEM: "C-system (combined, rules in a system message)",
}


@dataclass(frozen=True)
class StratumRow:
    label: str
    generations: int
    audio_failures: int


def stratum_label(seconds: float) -> str:
    if seconds <= SHORT_CLIP_SECONDS:
        return f"short (<= {SHORT_CLIP_SECONDS:g} s)"
    if seconds >= LONG_CLIP_SECONDS:
        return f"long (>= {LONG_CLIP_SECONDS:g} s)"
    return "medium"


def stratum_rows(
    arm: Arm, scores: list[GenerationScore], duration_of: Callable[[str], float]
) -> list[StratumRow]:
    buckets: dict[str, list[GenerationScore]] = {}
    for score in scores:
        if score.arm is arm and not score.is_control:
            buckets.setdefault(stratum_label(duration_of(score.subject_id)), []).append(
                score
            )
    return [
        StratumRow(
            label,
            len(group),
            sum(1 for s in group if s.audio_failure),
        )
        for label, group in sorted(buckets.items())
    ]


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _metrics_table(metrics: list[ArmMetrics]) -> list[str]:
    header = ["metric", *[m.arm.value for m in metrics]]
    rows = [
        ("generations", [str(m.generations) for m in metrics]),
        ("valid output", [f"{m.valid} ({_fmt(m.validity)})" for m in metrics]),
        (
            "audio failures",
            [f"{m.audio_failures} ({_fmt(m.audio_failure_rate)})" for m in metrics],
        ),
        ("median WER", [_fmt(m.median_wer) for m in metrics]),
        (
            "span leak rate",
            [
                f"{m.spans_leaked}/{m.spans_total} ({_fmt(m.leak_rate)})"
                for m in metrics
            ],
        ),
        (
            "sent generations with a leak",
            [
                f"{m.sent_generations_with_leak}/{m.sent_generations_with_spans}"
                for m in metrics
            ],
        ),
        (
            "mapping error rate",
            [
                f"{m.mapping_errors}/{m.mapping_checked} ({_fmt(m.mapping_error_rate)})"
                for m in metrics
            ],
        ),
        ("meaning preservation", [_fmt(m.mean_preservation) for m in metrics]),
        ("false refusals", [str(m.false_refusals) for m in metrics]),
        ("missed refusals", [str(m.missed_refusals) for m in metrics]),
        (
            "control fabrications",
            [f"{m.fabrications}/{m.control_generations}" for m in metrics],
        ),
        ("median seconds (warm)", [_fmt(m.median_seconds, 2) for m in metrics]),
        ("p90 seconds (warm)", [_fmt(m.p90_seconds, 2) for m in metrics]),
        (
            "cold / warm generations",
            [f"{m.cold_generations} / {m.warm_generations}" for m in metrics],
        ),
    ]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join([name, *cells]) + " |" for name, cells in rows]
    return lines


def render_report(
    *,
    meta: dict[str, object],
    decision: Decision,
    metrics: list[ArmMetrics],
    scores: list[GenerationScore],
    duration_of: Callable[[str], float],
) -> str:
    lines = ["# Personal-proxy spike v2.1.0-1: report", ""]
    lines += ["## Run", ""]
    lines += [f"- {key}: {meta[key]}" for key in sorted(meta)]
    lines += ["", "## Decision (frozen rule)", ""]
    lines.append(f"Outcome: **{decision.outcome.value.upper()}**")
    if decision.chosen_arm is not None:
        lines.append(f"Chosen arm: {ARM_LABEL[decision.chosen_arm]}")
    lines.append(
        f"Baseline audio-failure rate: {_fmt(decision.baseline_audio_failure_rate)}"
    )
    if decision.baseline_stop:
        lines.append(
            "**STOP CONDITION: the baseline transcription step alone fails on "
            "more than 10% of generations. Report to the owner before any merge "
            "decision.**"
        )
    for arm_decision in decision.arm_decisions:
        lines += ["", f"### {ARM_LABEL[arm_decision.arm]}", ""]
        lines.append(
            f"quality closure: {arm_decision.quality_closure}; "
            f"speed closure: {arm_decision.speed_closure}"
        )
        lines.append("")
        for criterion in arm_decision.criteria:
            mark = "PASS" if criterion.passed else "FAIL"
            lines.append(f"- {mark} {criterion.name}: {criterion.detail}")
    lines += ["", "## Metrics", "", *_metrics_table(metrics)]
    lines += ["", "## Failure classes", ""]
    for m in metrics:
        lines.append(f"- {m.arm.value}: {m.failure_counts or 'none'}")
    lines += ["", "## Leaks by span type/class (leaked/total)", ""]
    for m in metrics:
        breakdown = leak_breakdown(m.arm, scores)
        cells = ", ".join(f"{k}: {a}/{b}" for k, (a, b) in breakdown.items())
        lines.append(f"- {m.arm.value}: {cells or 'none'}")
    lines += ["", "## How leaked numbers were rendered", ""]
    for m in metrics:
        lines.append(f"- {m.arm.value}: {m.leak_renderings or 'none'}")
    lines += ["", "## Audio failures by clip length", ""]
    for m in metrics:
        rows = stratum_rows(m.arm, scores, duration_of)
        cells = ", ".join(
            f"{r.label}: {r.audio_failures}/{r.generations}" for r in rows
        )
        lines.append(f"- {m.arm.value}: {cells or 'none'}")
    lines += [
        "",
        "Reported only, never part of the rule: baseline absolute leak rate "
        "and audio-failure rate, number rendering, quasi-identifier leaks "
        "(see the type/class lines), and block R.",
        "",
    ]
    return "\n".join(lines)
