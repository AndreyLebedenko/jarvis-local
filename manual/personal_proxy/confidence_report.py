"""Signals per recording, their evaluation by the frozen rule, and the report of
spike v2.1.0-8 (tasks/done/spike-v2.1.0-8-confidence-signals.md). Pure: it works on
the data the harness has read."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from manual.personal_proxy.confidence import (
    JudgeResult,
    LabelRule,
    OperatingPoint,
    discriminates,
    invalid_items,
    is_bad,
    mean_pairwise_difference,
    min_sensitive_probability,
    operating_points,
    projection,
    symmetric_difference,
)
from manual.personal_proxy.corpus import SEEDS, Utterance

TEMPERATURES = (0.418, 0.618, 0.818)
BASE_KEY = (0.618, SEEDS[0])
SAMPLE_KEYS = tuple((t, s) for t in TEMPERATURES for s in SEEDS)
ENGINE_SIGNALS = ("S1", "S2", "S3a", "S3b", "S3c", "S5", "J1", "J2", "J3")
CONTROL_SIGNALS = ("S3b", "S3c")
SampleKey = tuple[float, int]


@dataclass(frozen=True)
class Signals:
    subject_id: str
    bad: bool | None
    scores: dict[str, float]


def _confidence(judge: JudgeResult | None) -> float:
    return 0.0 if judge is None else judge.confidence


def compute_signals(
    subject_id: str,
    utterance: Utterance | None,
    whisper_text: str,
    words: list[tuple[str, float]],
    segments: list[dict[str, Any]],
    samples: dict[SampleKey, str],
    judges: dict[SampleKey, JudgeResult | None],
    label_rule: LabelRule = LabelRule.FROZEN,
) -> Signals:
    base = samples[BASE_KEY]
    sample_projections = [
        projection(samples[k], literal_emails=True) for k in SAMPLE_KEYS
    ]
    base_projection = projection(base)
    base_judge = judges[BASE_KEY]
    scores = {
        "S1": float(symmetric_difference(projection(whisper_text), base_projection)),
        "S2": mean_pairwise_difference(sample_projections),
        "S3a": 1.0 - min_sensitive_probability(words),
        "S3b": max((s["no_speech_prob"] for s in segments), default=0.0),
        "S3c": -min((s["avg_logprob"] for s in segments), default=0.0),
        "S5": float(invalid_items(base)),
        "J1": 1.0 - _confidence(base_judge),
        "J2": 1.0 - min(_confidence(judges[k]) for k in SAMPLE_KEYS),
        "J3": float(0 if base_judge is None else len(base_judge.fragments)),
        "T": 1.0 if base_projection else 0.0,
    }
    bad = (
        None if utterance is None else is_bad(utterance, whisper_text, base, label_rule)
    )
    return Signals(subject_id, bad, scores)


@dataclass(frozen=True)
class Evaluation:
    name: str
    points: list[OperatingPoint]
    best: OperatingPoint
    discriminating: bool


def trivial_point(recordings: list[Signals]) -> OperatingPoint:
    scores = [r.scores["T"] for r in recordings]
    return operating_points(scores, [r.bad is True for r in recordings])[-1]


def evaluate(recordings: list[Signals], controls: list[Signals]) -> list[Evaluation]:
    bad = [r.bad is True for r in recordings]
    trivial = trivial_point(recordings)
    found = []
    for name in ENGINE_SIGNALS:
        points = operating_points([r.scores[name] for r in recordings], bad)
        control_scores = (
            [c.scores[name] for c in controls] if name in CONTROL_SIGNALS else None
        )
        best = max(points, key=lambda p: p.recall - p.false_refusals)
        found.append(
            Evaluation(
                name,
                points,
                best,
                discriminates(points, trivial.false_refusals, control_scores),
            )
        )
    return found


def _row(e: Evaluation) -> str:
    verdict = "discriminates" if e.discriminating else "does not"
    b = e.best
    return (
        f"| {e.name} | {verdict} | {b.threshold:.3f} | {b.recall:.2f} | "
        f"{b.false_refusals:.2f} |"
    )


def _judge_lines(bad: list[Signals], good: list[Signals], unparsed: int) -> list[str]:
    lines = []
    for name, group in (("bad", bad), ("good", good)):
        if group:
            avg = mean(1.0 - r.scores["J1"] for r in group)
            listed = sum(1 for r in group if r.scores["J3"] > 0)
            lines.append(
                f"- {name}: mean confidence {avg:.2f}, "
                f"listed uncertain fragments in {listed} of {len(group)}"
            )
    lines.append(f"- unparsable judge answers: {unparsed}")
    return lines


def _per_recording_lines(recordings: list[Signals]) -> list[str]:
    lines = [
        "| id | bad | " + " | ".join(ENGINE_SIGNALS) + " |",
        "|---|---|" + "---|" * len(ENGINE_SIGNALS),
    ]
    for r in recordings:
        cells = " | ".join(f"{r.scores[n]:.2f}" for n in ENGINE_SIGNALS)
        lines.append(f"| {r.subject_id} | {'BAD' if r.bad else ''} | {cells} |")
    return lines


def render_report(
    recordings: list[Signals],
    controls: list[Signals],
    evaluations: list[Evaluation],
    judge_unparsed: int,
    marks_effect: list[str],
) -> str:
    bad = [r for r in recordings if r.bad]
    good = [r for r in recordings if not r.bad]
    trivial = trivial_point(recordings)
    warning = "Fewer than 5 bad: nothing is concluded." if len(bad) < 5 else ""
    lines = [
        "# Spike v2.1.0-8: confidence signals",
        "",
        f"Recordings {len(recordings)}: bad {len(bad)}, good {len(good)}. {warning}",
        f"Trivial baseline T: recall {trivial.recall:.2f}, "
        f"false refusals {trivial.false_refusals:.2f}.",
        "",
        "| signal | verdict | best t | recall | false refusals |",
        "|---|---|---|---|---|",
        *(_row(e) for e in evaluations),
        "",
        "## Bad recordings and who catches them (at each signal's best t)",
        "",
    ]
    best = {e.name: e.best.threshold for e in evaluations}
    for r in bad:
        caught = [n for n in ENGINE_SIGNALS if r.scores[n] >= best[n]]
        lines.append(f"- {r.subject_id}: caught by {', '.join(caught) or 'nobody'}")
    lines += ["", "## Controls (silence and noise)", ""]
    for c in controls:
        flagged = [n for n in CONTROL_SIGNALS if c.scores[n] >= best[n]]
        values = ", ".join(f"{n}={c.scores[n]:.3f}" for n in ENGINE_SIGNALS)
        lines.append(f"- {c.subject_id}: flagged by {flagged or 'nobody'}; {values}")
    lines += ["", "## Judge", "", *_judge_lines(bad, good, judge_unparsed)]
    lines += ["", "## Effect of the [?] marks (base temperature, both seeds)", ""]
    lines += [f"- {line}" for line in marks_effect]
    lines += ["", "## Per recording", "", *_per_recording_lines(recordings)]
    return "\n".join(lines) + "\n"


HYPOTHESIS_RULES = (("S2", 0.6), ("J3", 1.0))
SINGLE_RULES = (("S1", 4.0), ("S2", 0.6), ("J3", 1.0))
HOLDS_RECALL = 0.8
HOLDS_FALSE_REFUSALS = 0.2
FAILS_RECALL = 0.6
FAILS_FALSE_REFUSALS = 0.35
MIN_BAD_FOR_CONCLUSION = 5


@dataclass(frozen=True)
class Flagging:
    caught: int
    bad: int
    wrongly: int
    good: int

    @property
    def recall(self) -> float:
        return self.caught / self.bad if self.bad else 0.0

    @property
    def false_refusals(self) -> float:
        return self.wrongly / self.good if self.good else 0.0


def flagged_by(signals: Signals, rules: tuple[tuple[str, float], ...]) -> bool:
    return any(signals.scores[name] >= threshold for name, threshold in rules)


def flagging(
    recordings: list[Signals], rules: tuple[tuple[str, float], ...]
) -> Flagging:
    bad = [r for r in recordings if r.bad]
    good = [r for r in recordings if not r.bad]
    return Flagging(
        sum(flagged_by(r, rules) for r in bad),
        len(bad),
        sum(flagged_by(r, rules) for r in good),
        len(good),
    )


def hypothesis_verdict(h: Flagging, trivial_false_refusals: float) -> str:
    if h.bad < MIN_BAD_FOR_CONCLUSION:
        return "nothing concluded (fewer than 5 bad recordings)"
    if h.recall >= HOLDS_RECALL and (
        h.false_refusals <= HOLDS_FALSE_REFUSALS
        and h.false_refusals < trivial_false_refusals
    ):
        return "H holds"
    if h.recall < FAILS_RECALL or h.false_refusals > FAILS_FALSE_REFUSALS:
        return "H fails"
    return "inconclusive"


def _rate(label: str, f: Flagging) -> str:
    return f"- {label}: recall {f.caught}/{f.bad}, false refusals {f.wrongly}/{f.good}"


def render_hypothesis(
    recordings: list[Signals], groups: dict[str, list[Signals]] | None = None
) -> list[str]:
    trivial = trivial_point(recordings)
    h = flagging(recordings, HYPOTHESIS_RULES)
    verdict = hypothesis_verdict(h, trivial.false_refusals)
    lines = [
        "## Hypothesis H: S2 >= 0.6 or J3 >= 1",
        "",
        _rate("H", h) + f"; trivial baseline T false refusals "
        f"{trivial.false_refusals:.2f}",
        f"- **verdict by the frozen rule: {verdict}**",
    ]
    for label, rules in (
        ("S1 >= 4 alone", SINGLE_RULES[:1]),
        ("S2 >= 0.6 alone", SINGLE_RULES[1:2]),
        ("J3 >= 1 alone", SINGLE_RULES[2:]),
    ):
        lines.append(_rate(label, flagging(recordings, rules)))
    for label, members in (groups or {}).items():
        lines.append(_rate(label, flagging(members, HYPOTHESIS_RULES)))
    missed = [
        r.subject_id
        for r in recordings
        if r.bad and not flagged_by(r, HYPOTHESIS_RULES)
    ]
    lines.append(f"- bad recordings H misses: {', '.join(missed) or 'none'}")
    return lines
