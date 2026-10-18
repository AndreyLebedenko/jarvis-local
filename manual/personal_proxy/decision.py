"""The frozen decision rule of tasks/spike-v2.1.0-1-combined-transcribe-sanitize.md.

Thresholds are the owner's, frozen 2026-10-18; do not tune them after a run.
Each combined arm is compared with the two-step baseline arm.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from manual.personal_proxy.records import Arm
from manual.personal_proxy.scoring import ArmMetrics

EPSILON = 1e-9

MIN_VALIDITY = 0.95
MAX_VALIDITY_DROP = 0.03
MAX_EXTRA_AUDIO_FAILURES = 2
MAX_EXTRA_MEDIAN_WER = 0.02
MAX_EXTRA_LEAK_RATE = 0.02
MAX_EXTRA_MAPPING_ERROR_RATE = 0.03
MAX_PRESERVATION_DROP = 0.03
MIN_SPEED_GAIN_SECONDS = 1.0

CLOSE_VALIDITY_BELOW = 0.90
CLOSE_EXTRA_AUDIO_FAILURES = 5
CLOSE_EXTRA_LEAK_RATE = 0.05

BASELINE_STOP_AUDIO_FAILURE_RATE = 0.10


class Outcome(StrEnum):
    GO = "go"
    CLOSE = "close"
    OWNER = "owner"


@dataclass(frozen=True)
class Criterion:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ArmDecision:
    arm: Arm
    criteria: tuple[Criterion, ...]
    quality_closure: bool
    speed_closure: bool

    @property
    def all_pass(self) -> bool:
        return all(criterion.passed for criterion in self.criteria)

    @property
    def closed(self) -> bool:
        return self.quality_closure or self.speed_closure


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    chosen_arm: Arm | None
    arm_decisions: tuple[ArmDecision, ...]
    baseline_audio_failure_rate: float
    baseline_stop: bool


def _at_most(value: float | None, limit: float | None) -> bool:
    return value is not None and limit is not None and value <= limit + EPSILON


def _at_least(value: float | None, limit: float | None) -> bool:
    return value is not None and limit is not None and value >= limit - EPSILON


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def speed_gain(base: ArmMetrics, other: ArmMetrics) -> float | None:
    if base.median_seconds is None or other.median_seconds is None:
        return None
    return base.median_seconds - other.median_seconds


def evaluate_arm(base: ArmMetrics, arm: ArmMetrics) -> ArmDecision:
    gain = speed_gain(base, arm)
    wer_limit = (
        None if base.median_wer is None else base.median_wer + MAX_EXTRA_MEDIAN_WER
    )
    pres_limit = (
        None
        if base.mean_preservation is None
        else base.mean_preservation - MAX_PRESERVATION_DROP
    )
    criteria = (
        Criterion(
            "1 validity",
            _at_least(arm.validity, MIN_VALIDITY)
            and _at_least(arm.validity, base.validity - MAX_VALIDITY_DROP),
            f"{_fmt(arm.validity)} vs baseline {_fmt(base.validity)}",
        ),
        Criterion(
            "2 audio failures",
            arm.audio_failures <= base.audio_failures + MAX_EXTRA_AUDIO_FAILURES,
            f"{arm.audio_failures} vs baseline {base.audio_failures}",
        ),
        Criterion(
            "3 median WER",
            _at_most(arm.median_wer, wer_limit),
            f"{_fmt(arm.median_wer)} vs baseline {_fmt(base.median_wer)}",
        ),
        Criterion(
            "4 span leak rate",
            arm.leak_rate <= base.leak_rate + MAX_EXTRA_LEAK_RATE + EPSILON,
            f"{_fmt(arm.leak_rate)} vs baseline {_fmt(base.leak_rate)}",
        ),
        Criterion(
            "5 mapping error rate",
            arm.mapping_error_rate
            <= base.mapping_error_rate + MAX_EXTRA_MAPPING_ERROR_RATE + EPSILON,
            f"{_fmt(arm.mapping_error_rate)} vs baseline "
            f"{_fmt(base.mapping_error_rate)}",
        ),
        Criterion(
            "6 meaning preservation",
            _at_least(arm.mean_preservation, pres_limit),
            f"{_fmt(arm.mean_preservation)} vs baseline {_fmt(base.mean_preservation)}",
        ),
        Criterion(
            "7 control fabrications",
            arm.fabrications <= base.fabrications,
            f"{arm.fabrications} vs baseline {base.fabrications}",
        ),
        Criterion(
            "8 speed gain",
            _at_least(gain, MIN_SPEED_GAIN_SECONDS),
            f"{_fmt(gain)} s median gain (need {MIN_SPEED_GAIN_SECONDS} s)",
        ),
    )
    return ArmDecision(
        arm=arm.arm,
        criteria=criteria,
        quality_closure=(
            arm.validity < CLOSE_VALIDITY_BELOW
            or arm.audio_failures > base.audio_failures + CLOSE_EXTRA_AUDIO_FAILURES
            or arm.leak_rate > base.leak_rate + CLOSE_EXTRA_LEAK_RATE + EPSILON
        ),
        speed_closure=gain is not None and gain < MIN_SPEED_GAIN_SECONDS - EPSILON,
    )


def decide(base: ArmMetrics, combined: list[ArmMetrics]) -> Decision:
    decisions = tuple(evaluate_arm(base, arm) for arm in combined)
    passing = [d for d in decisions if d.all_pass]
    chosen = _choose(passing, {m.arm: m for m in combined})
    if chosen is not None:
        outcome = Outcome.GO
    elif decisions and all(d.closed for d in decisions):
        outcome = Outcome.CLOSE
    else:
        outcome = Outcome.OWNER
    return Decision(
        outcome=outcome,
        chosen_arm=chosen,
        arm_decisions=decisions,
        baseline_audio_failure_rate=base.audio_failure_rate,
        baseline_stop=base.audio_failure_rate > BASELINE_STOP_AUDIO_FAILURE_RATE,
    )


def _choose(passing: list[ArmDecision], metrics: dict[Arm, ArmMetrics]) -> Arm | None:
    if not passing:
        return None
    return min(
        (d.arm for d in passing),
        key=lambda arm: (round(metrics[arm].leak_rate, 9), arm is not Arm.C_USER),
    )
