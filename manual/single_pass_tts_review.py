"""Blind review and decision rule for tasks/spike-single-pass-tts-block.md.

Consumes GenerationMetrics only. Every render function returns text; the
caller decides where it is written.

The review runs in two sittings. The equalized sitting (B vs A-eq voices, and
the A-eq invented-claim flags) is separate because showing it beside the
production pairs lets the reviewer identify B: B's voice would appear twice
with the same canvas, and A's canvas would appear with two different voices.
"""

from __future__ import annotations

import json
import math
import random
import re
import statistics
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any

from manual.single_pass_tts_records import (
    Arm,
    GenerationKey,
    GenerationMetrics,
    Level,
    TagOutcome,
    VoiceHygiene,
)

MAX_TAG_FAILURES = 1
MAX_CANVAS_LOSSES = 4
MAX_VOICE_LOSSES = 6
MIN_SPEED_GAIN_SECONDS = 1.0
CLOSE_CANVAS_LOSSES = 7
BIAS_CORRECT_GUESSES = 13
BIAS_GUESS_PAIRS = 16

DECIDING_LEVELS = (Level.OFF, Level.MEDIUM)
VOICE_ARMS = (Arm.A_PROD, Arm.B, Arm.A_EQ)


class Sitting(StrEnum):
    PRODUCTION = "production"
    EQUALIZED = "equalized"

    @property
    def pair_prefix(self) -> str:
        return "P" if self is Sitting.PRODUCTION else "E"

    @property
    def voice_prefix(self) -> str:
        return "V" if self is Sitting.PRODUCTION else "W"


def voice_sitting(arm: Arm) -> Sitting:
    return Sitting.EQUALIZED if arm is Arm.A_EQ else Sitting.PRODUCTION


class PairKind(StrEnum):
    CANVAS = "canvas"
    VOICE = "voice"
    EQUALIZED_VOICE = "equalized_voice"

    @property
    def sheet_label(self) -> str:
        return "canvas" if self is PairKind.CANVAS else "voice"

    @property
    def sitting(self) -> Sitting:
        if self is PairKind.EQUALIZED_VOICE:
            return Sitting.EQUALIZED
        return Sitting.PRODUCTION


class Side(StrEnum):
    X = "X"
    Y = "Y"


class Judgement(StrEnum):
    X = "X"
    Y = "Y"
    EQUAL = "="


class PairResult(StrEnum):
    B_WON = "b_won"
    B_LOST = "b_lost"
    TIE = "tie"


class Decision(StrEnum):
    GO = "GO"
    CLOSE = "CLOSE"
    OWNER = "OWNER"


_BLOCKS = (
    (PairKind.CANVAS, Arm.A_PROD, DECIDING_LEVELS),
    (PairKind.VOICE, Arm.A_PROD, DECIDING_LEVELS),
    (PairKind.EQUALIZED_VOICE, Arm.A_EQ, (Level.MEDIUM,)),
)


# --- review key and plan -------------------------------------------------------


@dataclass(frozen=True)
class PairEntry:
    pair_id: str
    kind: PairKind
    level: Level
    prompt_id: str
    x_arm: Arm
    y_arm: Arm
    auto_result: PairResult | None = None
    auto_reason: str | None = None

    @property
    def b_side(self) -> Side:
        return Side.X if self.x_arm is Arm.B else Side.Y

    @property
    def sitting(self) -> Sitting:
        return self.kind.sitting


@dataclass(frozen=True)
class VoiceEntry:
    voice_id: str
    arm: Arm
    key: GenerationKey

    @property
    def sitting(self) -> Sitting:
        return voice_sitting(self.arm)


@dataclass(frozen=True)
class ReviewKey:
    review_seed: int
    pairs: tuple[PairEntry, ...]
    voices: tuple[VoiceEntry, ...]

    def shown_pairs_in(self, sitting: Sitting) -> tuple[PairEntry, ...]:
        return tuple(
            pair
            for pair in self.pairs
            if pair.auto_result is None and pair.sitting is sitting
        )

    def voices_in(self, sitting: Sitting) -> tuple[VoiceEntry, ...]:
        return tuple(voice for voice in self.voices if voice.sitting is sitting)


@dataclass(frozen=True)
class Panel:
    canvas: str
    voice: str | None = None


@dataclass(frozen=True)
class ShownPair:
    entry: PairEntry
    x: Panel
    y: Panel


@dataclass(frozen=True)
class ShownVoice:
    entry: VoiceEntry
    canvas: str
    voice: str


@dataclass(frozen=True)
class ReviewPlan:
    key: ReviewKey
    shown_pairs: tuple[ShownPair, ...]
    voices: tuple[ShownVoice, ...]

    def shown_pairs_in(self, sitting: Sitting) -> tuple[ShownPair, ...]:
        return tuple(p for p in self.shown_pairs if p.entry.sitting is sitting)

    def voices_in(self, sitting: Sitting) -> tuple[ShownVoice, ...]:
        return tuple(v for v in self.voices if v.entry.sitting is sitting)


class _MetricsIndex:
    def __init__(self, metrics: Iterable[GenerationMetrics]) -> None:
        self._by_slot = {(m.key, m.arm): m for m in metrics}

    def get(self, key: GenerationKey, arm: Arm) -> GenerationMetrics:
        try:
            return self._by_slot[(key, arm)]
        except KeyError:
            raise ValueError(f"no metrics for arm {arm} of {key.slug}") from None

    def of(self, arm: Arm, level: Level, seed: int | None = None):
        return sorted(
            (
                m
                for (key, slot_arm), m in self._by_slot.items()
                if slot_arm is arm and key.level is level and seed in (None, key.seed)
            ),
            key=lambda m: m.key,
        )


def _has_text(text: str | None) -> bool:
    return bool(text and text.strip())


def _auto_resolution(
    kind: PairKind, b: GenerationMetrics, other: GenerationMetrics
) -> tuple[PairResult, str] | None:
    if kind is PairKind.CANVAS:
        present = (_has_text(b.canvas_text), _has_text(other.canvas_text))
        what = "empty canvas"
    else:
        present = (_has_text(b.voice_text), _has_text(other.voice_text))
        what = "no usable voice"
    if all(present):
        return None
    if not any(present):
        return PairResult.TIE, f"both sides: {what}"
    if present[0]:
        return PairResult.B_WON, f"{other.arm}: {what}"
    return PairResult.B_LOST, f"{Arm.B}: {what}"


@dataclass(frozen=True)
class _PairDraft:
    kind: PairKind
    b: GenerationMetrics
    other: GenerationMetrics
    b_is_x: bool

    @property
    def x(self) -> GenerationMetrics:
        return self.b if self.b_is_x else self.other

    @property
    def y(self) -> GenerationMetrics:
        return self.other if self.b_is_x else self.b

    def entry(self, pair_id: str) -> PairEntry:
        auto = _auto_resolution(self.kind, self.b, self.other)
        return PairEntry(
            pair_id=pair_id,
            kind=self.kind,
            level=self.b.key.level,
            prompt_id=self.b.key.prompt_id,
            x_arm=self.x.arm,
            y_arm=self.y.arm,
            auto_result=auto[0] if auto else None,
            auto_reason=auto[1] if auto else None,
        )

    def panel(self, metrics: GenerationMetrics) -> Panel:
        voice = None if self.kind is PairKind.CANVAS else metrics.voice_text
        return Panel(canvas=metrics.canvas_text, voice=voice)


def _ids(prefix: str, count: int) -> list[str]:
    width = max(2, len(str(count)))
    return [f"{prefix}{n:0{width}d}" for n in range(1, count + 1)]


def _pair_drafts(
    index: _MetricsIndex, sitting: Sitting, review_seed: int, rng: random.Random
) -> list[_PairDraft]:
    drafts = []
    for kind, opponent, levels in _BLOCKS:
        if kind.sitting is not sitting:
            continue
        for level in levels:
            b_generations = index.of(Arm.B, level, review_seed)
            if not b_generations:
                raise ValueError(
                    f"no arm b metrics at level {level}, seed {review_seed}"
                )
            drafts.extend(
                _PairDraft(kind, b, index.get(b.key, opponent), rng.random() < 0.5)
                for b in b_generations
            )
    rng.shuffle(drafts)
    return drafts


def _sitting_pairs(
    index: _MetricsIndex, sitting: Sitting, review_seed: int, rng: random.Random
) -> tuple[list[PairEntry], list[ShownPair]]:
    drafts = _pair_drafts(index, sitting, review_seed, rng)
    ids = _ids(sitting.pair_prefix, len(drafts))
    entries = [draft.entry(pair_id) for pair_id, draft in zip(ids, drafts, strict=True)]
    shown = [
        ShownPair(entry, draft.panel(draft.x), draft.panel(draft.y))
        for entry, draft in zip(entries, drafts, strict=True)
        if entry.auto_result is None
    ]
    return entries, shown


def _sitting_voices(
    index: _MetricsIndex, sitting: Sitting, review_seed: int, rng: random.Random
) -> list[ShownVoice]:
    candidates = [
        m
        for level in DECIDING_LEVELS
        for arm in VOICE_ARMS
        if voice_sitting(arm) is sitting
        for m in index.of(arm, level, review_seed)
        if _has_text(m.voice_text)
    ]
    rng.shuffle(candidates)
    ids = _ids(sitting.voice_prefix, len(candidates))
    return [
        ShownVoice(VoiceEntry(voice_id, m.arm, m.key), m.canvas_text, m.voice_text)
        for voice_id, m in zip(ids, candidates, strict=True)
    ]


def build_review(
    metrics: Iterable[GenerationMetrics], *, review_seed: int, rng_seed: int
) -> ReviewPlan:
    index = _MetricsIndex(metrics)
    rng = random.Random(rng_seed)
    entries: list[PairEntry] = []
    shown: list[ShownPair] = []
    voices: list[ShownVoice] = []
    for sitting in Sitting:
        sitting_entries, sitting_shown = _sitting_pairs(
            index, sitting, review_seed, rng
        )
        entries.extend(sitting_entries)
        shown.extend(sitting_shown)
        voices.extend(_sitting_voices(index, sitting, review_seed, rng))
    key = ReviewKey(review_seed, tuple(entries), tuple(v.entry for v in voices))
    return ReviewPlan(key=key, shown_pairs=tuple(shown), voices=tuple(voices))


# --- rendering the sheet, the template, and the key --------------------------


_SHEET_INTRO = """\
Each pair shows two answers to the same prompt as X and Y, in random order.
Canvas pairs: judge the written answer. Voice pairs: judge each voice as a
spoken rendering of the canvas shown above it. Record the verdict and your
guess of which side is B in the answer file.

After the pairs, each voice is listed once with its own canvas: mark whether
the voice states any claim that is not present in that canvas.
"""


def _fenced(text: str) -> str:
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_run + 1)
    body = text if text.endswith("\n") else text + "\n"
    return f"{fence}text\n{body}{fence}\n"


def _panel_markdown(side: Side, panel: Panel) -> str:
    text = f"### {side} canvas\n\n{_fenced(panel.canvas)}"
    if panel.voice is not None:
        text += f"\n### {side} voice\n\n{_fenced(panel.voice)}"
    return text


def _pair_markdown(pair: ShownPair) -> str:
    entry = pair.entry
    heading = (
        f"## {entry.pair_id} ({entry.kind.sheet_label}, "
        f"level {entry.level}, prompt {entry.prompt_id})"
    )
    return "\n".join(
        (heading, "", _panel_markdown(Side.X, pair.x), _panel_markdown(Side.Y, pair.y))
    )


def _voice_markdown(voice: ShownVoice) -> str:
    entry = voice.entry
    heading = (
        f"## {entry.voice_id} (level {entry.key.level}, prompt {entry.key.prompt_id})"
    )
    return "\n".join(
        (
            heading,
            "",
            "### canvas",
            "",
            _fenced(voice.canvas),
            "### voice",
            "",
            _fenced(voice.voice),
        )
    )


def render_sheet_markdown(plan: ReviewPlan, sitting: Sitting) -> str:
    sections = [f"# Blind review sheet, {sitting} sitting\n", _SHEET_INTRO, "# Pairs\n"]
    sections.extend(_pair_markdown(pair) for pair in plan.shown_pairs_in(sitting))
    sections.append("# Invented claims\n")
    sections.extend(_voice_markdown(voice) for voice in plan.voices_in(sitting))
    return "\n".join(sections)


_TEMPLATE_INTRO = """# Fill every value; an empty "" is an error.
# verdict: "X" (X is better), "Y" (Y is better) or "=" (equal).
# guess_b: "X" or "Y", the side you think is B.
# invented: "yes" if the voice states any claim not present in its own
# canvas, otherwise "no".
"""


def render_answer_template(plan: ReviewPlan, sitting: Sitting) -> str:
    sections = [f"# Blind review answers, {sitting} sitting.\n" + _TEMPLATE_INTRO]
    sections.extend(
        f'[{pair.entry.pair_id}]\nverdict = ""\nguess_b = ""\n'
        for pair in plan.shown_pairs_in(sitting)
    )
    sections.extend(
        f'[{voice.entry.voice_id}]\ninvented = ""\n'
        for voice in plan.voices_in(sitting)
    )
    return "\n".join(sections)


def _pair_to_json(pair: PairEntry) -> dict[str, Any]:
    return {
        "id": pair.pair_id,
        "kind": pair.kind.value,
        "level": pair.level.value,
        "prompt_id": pair.prompt_id,
        "x": pair.x_arm.value,
        "y": pair.y_arm.value,
        "auto_result": pair.auto_result.value if pair.auto_result else None,
        "auto_reason": pair.auto_reason,
    }


def _pair_from_json(data: Mapping[str, Any]) -> PairEntry:
    auto = data["auto_result"]
    return PairEntry(
        pair_id=data["id"],
        kind=PairKind(data["kind"]),
        level=Level(data["level"]),
        prompt_id=data["prompt_id"],
        x_arm=Arm(data["x"]),
        y_arm=Arm(data["y"]),
        auto_result=PairResult(auto) if auto else None,
        auto_reason=data["auto_reason"],
    )


def _voice_to_json(voice: VoiceEntry) -> dict[str, Any]:
    return {
        "id": voice.voice_id,
        "arm": voice.arm.value,
        "level": voice.key.level.value,
        "prompt_id": voice.key.prompt_id,
        "seed": voice.key.seed,
    }


def _voice_from_json(data: Mapping[str, Any]) -> VoiceEntry:
    key = GenerationKey(Level(data["level"]), data["prompt_id"], data["seed"])
    return VoiceEntry(voice_id=data["id"], arm=Arm(data["arm"]), key=key)


def render_key_json(plan: ReviewPlan) -> str:
    key = plan.key
    document = {
        "review_seed": key.review_seed,
        "pairs": [_pair_to_json(pair) for pair in key.pairs],
        "voices": [_voice_to_json(voice) for voice in key.voices],
    }
    return json.dumps(document, indent=1) + "\n"


def load_key_json(text: str) -> ReviewKey:
    data = json.loads(text)
    return ReviewKey(
        review_seed=data["review_seed"],
        pairs=tuple(_pair_from_json(pair) for pair in data["pairs"]),
        voices=tuple(_voice_from_json(voice) for voice in data["voices"]),
    )


# --- reading the answers ------------------------------------------------------


@dataclass(frozen=True)
class ReviewAnswers:
    judgements: Mapping[str, Judgement]
    guesses: Mapping[str, Side]
    invented: Mapping[str, bool]


_JUDGEMENT_VALUES = {judgement.value: judgement for judgement in Judgement}
_GUESS_VALUES = {side.value: side for side in Side}
_INVENTED_VALUES = {"yes": True, "no": False}
_PAIR_FIELDS = {"verdict": _JUDGEMENT_VALUES, "guess_b": _GUESS_VALUES}
_VOICE_FIELDS = {"invented": _INVENTED_VALUES}

_FieldSpec = Mapping[str, Mapping[str, Any]]


def _read_entry(
    entry_id: str, section: Any, spec: _FieldSpec, errors: list[str]
) -> dict[str, Any]:
    if not isinstance(section, dict):
        errors.append(f"{entry_id}: section missing")
        return {}
    values = {}
    for name, allowed in spec.items():
        value = section.get(name)
        if isinstance(value, str) and value in allowed:
            values[name] = allowed[value]
        else:
            expected = ", ".join(f'"{option}"' for option in allowed)
            errors.append(
                f"{entry_id}.{name}: expected one of {expected}; got {value!r}"
            )
    return values


def _read_entries(
    data: Mapping[str, Any],
    specs: Mapping[str, _FieldSpec],
    sitting: Sitting,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    entries = {
        entry_id: _read_entry(entry_id, data.get(entry_id), spec, errors)
        for entry_id, spec in specs.items()
    }
    errors.extend(
        f"{entry_id}: not an entry of the {sitting} sitting"
        for entry_id in data
        if entry_id not in specs
    )
    return entries


def parse_answers(toml_text: str, key: ReviewKey, sitting: Sitting) -> ReviewAnswers:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"review answers are not valid TOML: {error}") from error
    pair_ids = [pair.pair_id for pair in key.shown_pairs_in(sitting)]
    voice_ids = [voice.voice_id for voice in key.voices_in(sitting)]
    specs: dict[str, _FieldSpec] = dict.fromkeys(pair_ids, _PAIR_FIELDS)
    specs |= dict.fromkeys(voice_ids, _VOICE_FIELDS)
    errors: list[str] = []
    entries = _read_entries(data, specs, sitting, errors)
    if errors:
        raise ValueError(
            f"invalid review answers for the {sitting} sitting:\n" + "\n".join(errors)
        )
    return ReviewAnswers(
        judgements={pid: entries[pid]["verdict"] for pid in pair_ids},
        guesses={pid: entries[pid]["guess_b"] for pid in pair_ids},
        invented={vid: entries[vid]["invented"] for vid in voice_ids},
    )


# --- scoring and the decision rule --------------------------------------------


@dataclass(frozen=True)
class Criterion:
    name: str
    measured: str
    threshold: str
    passed: bool


@dataclass(frozen=True)
class SpeedGain:
    """`median_seconds` is None when no pair is left or the median is undefined
    (the two middle gains are -inf and +inf)."""

    median_seconds: float | None
    matched: int
    dropped: int

    @property
    def passes(self) -> bool:
        return (
            self.median_seconds is not None
            and self.median_seconds >= MIN_SPEED_GAIN_SECONDS
        )


def _seconds(value: float | None) -> str:
    if value is None:
        return "undefined"
    if math.isinf(value):
        return "+inf" if value > 0 else "-inf"
    return f"{value:.3f}"


@dataclass(frozen=True)
class LevelResult:
    level: Level
    b_generations: int
    tag_failures: int
    canvas_pairs: int
    canvas_losses: int
    voice_pairs: int
    voice_losses: int
    b_invented: int
    a_prod_invented: int
    b_runaways: int
    a_prod_runaways: int
    speed: SpeedGain

    def criteria(self) -> tuple[Criterion, ...]:
        speed = self.speed
        return (
            Criterion(
                "1. tag failures among B generations",
                f"{self.tag_failures} of {self.b_generations}",
                f"<= {MAX_TAG_FAILURES}",
                self.tag_failures <= MAX_TAG_FAILURES,
            ),
            Criterion(
                "2. canvas pairs B lost",
                f"{self.canvas_losses} of {self.canvas_pairs}",
                f"<= {MAX_CANVAS_LOSSES}",
                self.canvas_losses <= MAX_CANVAS_LOSSES,
            ),
            Criterion(
                "3. voice pairs B lost vs A-prod",
                f"{self.voice_losses} of {self.voice_pairs}",
                f"<= {MAX_VOICE_LOSSES}",
                self.voice_losses <= MAX_VOICE_LOSSES,
            ),
            Criterion(
                "4. voices flagged for invented claims",
                f"B {self.b_invented}, A-prod {self.a_prod_invented}",
                "B <= A-prod",
                self.b_invented <= self.a_prod_invented,
            ),
            Criterion(
                "5. runaways",
                f"B {self.b_runaways}, A-prod {self.a_prod_runaways}",
                "B <= A-prod",
                self.b_runaways <= self.a_prod_runaways,
            ),
            Criterion(
                "6. median first-sentence gain (A-prod minus B), s",
                f"{_seconds(speed.median_seconds)} over {speed.matched} matched,"
                f" {speed.dropped} dropped",
                f">= {MIN_SPEED_GAIN_SECONDS}",
                speed.passes,
            ),
        )

    @property
    def go(self) -> bool:
        return all(criterion.passed for criterion in self.criteria())


@dataclass(frozen=True)
class GuessAccuracy:
    level: Level
    kind: PairKind
    correct: int
    shown: int

    @property
    def possible_bias(self) -> bool:
        return (
            self.shown > 0
            and self.correct * BIAS_GUESS_PAIRS >= BIAS_CORRECT_GUESSES * self.shown
        )


@dataclass(frozen=True)
class EqualizedBlock:
    """B vs A-eq at medium. Explains the decision, never changes it. Its guesses
    follow the production sitting, so they are not checked for bias."""

    voice_pairs: int
    voice_losses: int
    a_eq_voices: int
    a_eq_invented: int
    guess_correct: int
    guess_shown: int


_ARMS_WITHOUT_OWN_WALL_TIME = (Arm.A_EQ,)
_A_EQ_WALL_NOTE = (
    "A-eq median wall time is n/a: the harness runs A-eq's pass 2 after"
    " A-prod's pass 2, so A-eq timings include A-prod's pass 2."
)


@dataclass(frozen=True)
class ArmUsage:
    """`median_wall_seconds` is None for an arm whose timings are not its own."""

    arm: Arm
    level: Level
    generations: int
    median_wall_seconds: float | None
    eval_count_sum: int
    hygiene: VoiceHygiene


@dataclass(frozen=True)
class SpikeReport:
    """`equalized` is None when the equalized sitting was not reviewed."""

    decision: Decision
    close_reasons: tuple[str, ...]
    review_seed: int
    levels: tuple[LevelResult, ...]
    equalized: EqualizedBlock | None
    guesses: tuple[GuessAccuracy, ...]
    arm_usage: tuple[ArmUsage, ...]


def _pair_result(pair: PairEntry, answers: ReviewAnswers) -> PairResult:
    if pair.auto_result is not None:
        return pair.auto_result
    judgement = answers.judgements[pair.pair_id]
    if judgement is Judgement.EQUAL:
        return PairResult.TIE
    return (
        PairResult.B_WON if Side(judgement.value) is pair.b_side else PairResult.B_LOST
    )


def _losses(
    key: ReviewKey, answers: ReviewAnswers, kind: PairKind, level: Level
) -> tuple[int, int]:
    results = [
        _pair_result(pair, answers)
        for pair in key.pairs
        if (pair.kind, pair.level) == (kind, level)
    ]
    return len(results), results.count(PairResult.B_LOST)


def _flagged(key: ReviewKey, answers: ReviewAnswers, arm: Arm, level: Level) -> int:
    return sum(
        answers.invented[voice.voice_id]
        for voice in key.voices
        if (voice.arm, voice.key.level) == (arm, level)
    )


def _first_sentence_gain(a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    if b is None:
        return -math.inf
    if a is None:
        return math.inf
    return a - b


def _speed_gain(index: _MetricsIndex, level: Level) -> SpeedGain:
    all_gains = [
        _first_sentence_gain(
            index.get(b.key, Arm.A_PROD).first_sentence_seconds,
            b.first_sentence_seconds,
        )
        for b in index.of(Arm.B, level)
    ]
    gains = [gain for gain in all_gains if gain is not None]
    median = statistics.median(gains) if gains else None
    if median is not None and math.isnan(median):
        median = None
    return SpeedGain(median, len(gains), len(all_gains) - len(gains))


def _score_level(
    level: Level, index: _MetricsIndex, key: ReviewKey, answers: ReviewAnswers
) -> LevelResult:
    b_generations = index.of(Arm.B, level)
    if not b_generations:
        raise ValueError(f"no arm b metrics at level {level}")
    a_generations = index.of(Arm.A_PROD, level)
    canvas_pairs, canvas_losses = _losses(key, answers, PairKind.CANVAS, level)
    voice_pairs, voice_losses = _losses(key, answers, PairKind.VOICE, level)
    return LevelResult(
        level=level,
        b_generations=len(b_generations),
        tag_failures=sum(
            m.tag_outcome is not TagOutcome.WELL_FORMED for m in b_generations
        ),
        canvas_pairs=canvas_pairs,
        canvas_losses=canvas_losses,
        voice_pairs=voice_pairs,
        voice_losses=voice_losses,
        b_invented=_flagged(key, answers, Arm.B, level),
        a_prod_invented=_flagged(key, answers, Arm.A_PROD, level),
        b_runaways=sum(m.runaway for m in b_generations),
        a_prod_runaways=sum(m.runaway for m in a_generations),
        speed=_speed_gain(index, level),
    )


def close_reasons(levels: Sequence[LevelResult]) -> tuple[str, ...]:
    reasons = [
        f"canvas: B lost {result.canvas_losses} canvas pairs at level {result.level}"
        f" (>= {CLOSE_CANVAS_LOSSES})"
        for result in levels
        if result.canvas_losses >= CLOSE_CANVAS_LOSSES
    ]
    if not any(result.speed.passes for result in levels):
        reasons.append(
            f"speed: median gain below {MIN_SPEED_GAIN_SECONDS} s at both levels"
        )
    return tuple(reasons)


def decide(levels: Sequence[LevelResult]) -> Decision:
    if all(result.go for result in levels):
        return Decision.GO
    if close_reasons(levels):
        return Decision.CLOSE
    return Decision.OWNER


def _correct_guesses(pairs: Iterable[PairEntry], answers: ReviewAnswers) -> int:
    return sum(answers.guesses[pair.pair_id] is pair.b_side for pair in pairs)


def _guess_accuracy(
    key: ReviewKey, answers: ReviewAnswers
) -> tuple[GuessAccuracy, ...]:
    shown_pairs = key.shown_pairs_in(Sitting.PRODUCTION)
    accuracy = []
    for kind, _, levels in _BLOCKS:
        for level in levels if kind.sitting is Sitting.PRODUCTION else ():
            shown = [p for p in shown_pairs if (p.level, p.kind) == (level, kind)]
            correct = _correct_guesses(shown, answers)
            accuracy.append(GuessAccuracy(level, kind, correct, len(shown)))
    return tuple(accuracy)


def _equalized_block(key: ReviewKey, answers: ReviewAnswers) -> EqualizedBlock:
    voice_pairs, voice_losses = _losses(
        key, answers, PairKind.EQUALIZED_VOICE, Level.MEDIUM
    )
    voices = key.voices_in(Sitting.EQUALIZED)
    shown = key.shown_pairs_in(Sitting.EQUALIZED)
    return EqualizedBlock(
        voice_pairs=voice_pairs,
        voice_losses=voice_losses,
        a_eq_voices=len(voices),
        a_eq_invented=sum(answers.invented[voice.voice_id] for voice in voices),
        guess_correct=_correct_guesses(shown, answers),
        guess_shown=len(shown),
    )


def _summed_hygiene(generations: Sequence[GenerationMetrics]) -> VoiceHygiene:
    present = [m.hygiene for m in generations if m.hygiene is not None]
    return VoiceHygiene(
        **{
            f.name: sum(getattr(h, f.name) for h in present)
            for f in fields(VoiceHygiene)
        }
    )


def _arm_usage(index: _MetricsIndex) -> tuple[ArmUsage, ...]:
    usage = []
    for level in DECIDING_LEVELS:
        for arm in VOICE_ARMS:
            generations = index.of(arm, level)
            if generations:
                own_wall_time = arm not in _ARMS_WITHOUT_OWN_WALL_TIME
                usage.append(
                    ArmUsage(
                        arm=arm,
                        level=level,
                        generations=len(generations),
                        median_wall_seconds=statistics.median(
                            m.total_wall_seconds for m in generations
                        )
                        if own_wall_time
                        else None,
                        eval_count_sum=sum(m.eval_count_sum for m in generations),
                        hygiene=_summed_hygiene(generations),
                    )
                )
    return tuple(usage)


def _require_key_generations(index: _MetricsIndex, key: ReviewKey) -> None:
    for pair in key.pairs:
        generation = GenerationKey(pair.level, pair.prompt_id, key.review_seed)
        index.get(generation, pair.x_arm)
        index.get(generation, pair.y_arm)


def score(
    metrics: Iterable[GenerationMetrics],
    key: ReviewKey,
    production: ReviewAnswers,
    equalized: ReviewAnswers | None = None,
) -> SpikeReport:
    index = _MetricsIndex(metrics)
    _require_key_generations(index, key)
    levels = tuple(
        _score_level(level, index, key, production) for level in DECIDING_LEVELS
    )
    return SpikeReport(
        decision=decide(levels),
        close_reasons=close_reasons(levels),
        review_seed=key.review_seed,
        levels=levels,
        equalized=_equalized_block(key, equalized) if equalized is not None else None,
        guesses=_guess_accuracy(key, production),
        arm_usage=_arm_usage(index),
    )


# --- rendering the report -----------------------------------------------------


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def _decision_markdown(report: SpikeReport) -> str:
    if report.decision is Decision.GO:
        why = "all six criteria hold at both levels."
    elif report.decision is Decision.CLOSE:
        why = "; ".join(report.close_reasons) + "."
    else:
        why = "neither Go at both levels nor a Close condition; goes to the owner."
    return f"Decision: **{report.decision}** - {why}\n"


def _level_markdown(result: LevelResult) -> str:
    rows = (
        (c.name, c.measured, c.threshold, "pass" if c.passed else "FAIL")
        for c in result.criteria()
    )
    go = "holds" if result.go else "does not hold"
    return (
        f"## Level {result.level} (production block, B vs A-prod)\n\n"
        + _table(("criterion", "measured", "threshold", "result"), rows)
        + f"\nGo at this level: {go}.\n"
    )


def _guesses_markdown(report: SpikeReport) -> str:
    rows = (
        (g.level, g.kind, g.correct, g.shown, "yes" if g.possible_bias else "no")
        for g in report.guesses
    )
    return (
        "## Reviewer guess of B (reported, does not decide)\n\n"
        f"Possible bias when correct/shown >= {BIAS_CORRECT_GUESSES}/"
        f"{BIAS_GUESS_PAIRS}.\n\n"
        + _table(("level", "pairs", "correct", "shown", "possible bias"), rows)
    )


def _equalized_markdown(block: EqualizedBlock | None) -> str:
    title = "## Equalized block (explains, does not decide)\n\n"
    if block is None:
        return title + "The equalized sitting was not reviewed.\n"
    return title + (
        f"Voice pairs B lost vs A-eq at level {Level.MEDIUM}: "
        f"{block.voice_losses} of {block.voice_pairs}.\n\n"
        f"A-eq voices flagged for invented claims: {block.a_eq_invented} of "
        f"{block.a_eq_voices}.\n\n"
        f"Reviewer guess of B: {block.guess_correct} of {block.guess_shown} correct;"
        " unreliable by design (reviewed after the production sitting), so never"
        " flagged as bias.\n"
    )


def _wall_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _usage_markdown(report: SpikeReport) -> str:
    header = ("level", "arm", "generations", "median wall s", "eval_count sum")
    header += tuple(f.name for f in fields(VoiceHygiene))
    rows = (
        (
            u.level,
            u.arm,
            u.generations,
            _wall_seconds(u.median_wall_seconds),
            u.eval_count_sum,
            *(getattr(u.hygiene, f.name) for f in fields(VoiceHygiene)),
        )
        for u in report.arm_usage
    )
    return (
        "## Voice hygiene and cost per arm (reported, does not decide)\n\n"
        + _table(header, rows)
        + f"\n{_A_EQ_WALL_NOTE}\n"
    )


def render_report_markdown(report: SpikeReport) -> str:
    sections = [
        "# Single-pass TTS spike: decision report\n",
        f"Blind review on seed {report.review_seed}; automated measures on all"
        " seeds.\n",
        _decision_markdown(report),
        *(_level_markdown(result) for result in report.levels),
        _equalized_markdown(report.equalized),
        _guesses_markdown(report),
        _usage_markdown(report),
    ]
    return "\n".join(sections)
