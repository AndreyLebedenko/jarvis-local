import json
import math

import pytest

from manual.single_pass_tts_records import (
    Arm,
    GenerationKey,
    GenerationMetrics,
    Level,
    TagOutcome,
    VoiceHygiene,
)
from manual.single_pass_tts_review import (
    Decision,
    Judgement,
    PairKind,
    PairResult,
    ReviewAnswers,
    Side,
    Sitting,
    build_review,
    load_key_json,
    parse_answers,
    render_answer_template,
    render_key_json,
    render_report_markdown,
    render_sheet_markdown,
    score,
)

PROMPTS = tuple(f"p{n:02d}" for n in range(1, 17))
SEEDS = (1, 2)
REVIEW_SEED = 1
RNG_SEED = 7


def _metric(level, prompt_id, seed, arm, **overrides):
    canvas_arm = Arm.A_PROD if arm is Arm.A_EQ else arm
    values = {
        "key": GenerationKey(level, prompt_id, seed),
        "arm": arm,
        "canvas_text": f"canvas {canvas_arm} {level} {prompt_id} s{seed}",
        "voice_text": f"voice {arm} {level} {prompt_id} s{seed}",
        "first_sentence_seconds": 1.0 if arm is Arm.B else 3.0,
        "total_wall_seconds": 5.0,
        "eval_count_sum": 100,
        "runaway": False,
        "hygiene": VoiceHygiene(),
        "tag_outcome": TagOutcome.WELL_FORMED if arm is Arm.B else None,
    }
    values.update(overrides)
    return GenerationMetrics(**values)


def _arms(level):
    if level is Level.MEDIUM:
        return (Arm.A_PROD, Arm.A_EQ, Arm.B)
    return (Arm.A_PROD, Arm.B)


def _metrics(overrides=None):
    """`overrides` maps (level, prompt_id, seed, arm) to GenerationMetrics fields."""
    overrides = overrides or {}
    return [
        _metric(level, prompt_id, seed, arm, **overrides.get(slot, {}))
        for level in Level
        for prompt_id in PROMPTS
        for seed in SEEDS
        for arm in _arms(level)
        for slot in [(level, prompt_id, seed, arm)]
    ]


def _for_prompts(level, arm, count, fields, seeds=(REVIEW_SEED,)):
    return {
        (level, prompt_id, seed, arm): fields
        for prompt_id in PROMPTS[:count]
        for seed in seeds
    }


def _shown(key, sitting):
    return [p for p in key.pairs if p.auto_result is None and p.sitting is sitting]


def _b_side(pair):
    return Side.X if pair.x_arm is Arm.B else Side.Y


def _other_side(side):
    return Side.Y if side is Side.X else Side.X


def _answers(
    key, sitting=Sitting.PRODUCTION, *, b_lost=None, flagged=None, wrong_guesses=None
):
    """Counts are per group and applied to the lowest prompt ids first.

    b_lost and wrong_guesses: {(PairKind, Level): n}; flagged: {(Arm, Level): n}.
    Every other pair is a B win with a correct guess; every other voice is clean.
    """
    losses_left = dict(b_lost or {})
    wrong_left = dict(wrong_guesses or {})
    flags_left = dict(flagged or {})
    judgements, guesses, invented = {}, {}, {}
    for pair in sorted(_shown(key, sitting), key=lambda p: p.prompt_id):
        group = (pair.kind, pair.level)
        b_side = _b_side(pair)
        if losses_left.get(group, 0) > 0:
            losses_left[group] -= 1
            judgements[pair.pair_id] = Judgement(_other_side(b_side).value)
        else:
            judgements[pair.pair_id] = Judgement(b_side.value)
        if wrong_left.get(group, 0) > 0:
            wrong_left[group] -= 1
            guesses[pair.pair_id] = _other_side(b_side)
        else:
            guesses[pair.pair_id] = b_side
    for voice in sorted(key.voices, key=lambda v: (v.key, v.arm)):
        if voice.sitting is not sitting:
            continue
        group = (voice.arm, voice.key.level)
        invented[voice.voice_id] = flags_left.get(group, 0) > 0
        if invented[voice.voice_id]:
            flags_left[group] -= 1
    return ReviewAnswers(judgements=judgements, guesses=guesses, invented=invented)


def _decide(metrics=None, *, equalized=None, **answer_counts):
    """`equalized` holds _answers counts for the equalized sitting; None means
    that sitting was not reviewed."""
    metrics = metrics if metrics is not None else _metrics()
    key = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED).key
    production = _answers(key, Sitting.PRODUCTION, **answer_counts)
    if equalized is None:
        return score(metrics, key, production)
    return score(
        metrics, key, production, _answers(key, Sitting.EQUALIZED, **equalized)
    )


def _level(report, level):
    return next(result for result in report.levels if result.level is level)


def _filled_template(plan, sitting, verdict="X", guess="Y", invented="no"):
    return (
        render_answer_template(plan, sitting)
        .replace('verdict = ""', f'verdict = "{verdict}"')
        .replace('guess_b = ""', f'guess_b = "{guess}"')
        .replace('invented = ""', f'invented = "{invented}"')
    )


# --- blind review plan -------------------------------------------------------


def test_plan_is_identical_for_the_same_rng_seed():
    metrics = _metrics()

    first = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    second = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    assert first == second


def test_pair_order_differs_between_rng_seeds():
    metrics = _metrics()

    def order(rng_seed):
        plan = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=rng_seed)
        return [(p.kind, p.level, p.prompt_id) for p in plan.key.pairs]

    assert order(1) != order(2)


def test_pair_order_is_shuffled_rather_than_grouped_by_kind():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    kinds = [pair.kind for pair in plan.key.pairs]

    assert kinds != sorted(kinds)


def test_b_appears_both_as_x_and_as_y():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    x_arms = {pair.x_arm for pair in plan.key.pairs}

    assert Arm.B in x_arms
    assert x_arms - {Arm.B}


def test_plan_has_canvas_and_voice_pairs_per_level_and_equalized_pairs_at_medium():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    counts = {}
    for pair in plan.key.pairs:
        group = (pair.kind, pair.level)
        counts[group] = counts.get(group, 0) + 1

    assert counts == {
        (PairKind.CANVAS, Level.OFF): 16,
        (PairKind.CANVAS, Level.MEDIUM): 16,
        (PairKind.VOICE, Level.OFF): 16,
        (PairKind.VOICE, Level.MEDIUM): 16,
        (PairKind.EQUALIZED_VOICE, Level.MEDIUM): 16,
    }


def test_equalized_pairs_oppose_b_to_a_eq_and_the_others_to_a_prod():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    for pair in plan.key.pairs:
        opponent = ({pair.x_arm, pair.y_arm} - {Arm.B}).pop()
        expected = Arm.A_EQ if pair.kind is PairKind.EQUALIZED_VOICE else Arm.A_PROD
        assert opponent is expected


def test_pair_ids_follow_the_shuffled_order():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    def ids(sitting):
        return [p.pair_id for p in plan.key.pairs if p.sitting is sitting]

    assert ids(Sitting.PRODUCTION) == [f"P{n:02d}" for n in range(1, 65)]
    assert ids(Sitting.EQUALIZED) == [f"E{n:02d}" for n in range(1, 17)]


def test_equalized_pairs_and_a_eq_voices_form_their_own_sitting():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    for pair in plan.key.pairs:
        equalized = pair.kind is PairKind.EQUALIZED_VOICE
        assert (pair.sitting is Sitting.EQUALIZED) is equalized
    for voice in plan.key.voices:
        assert (voice.sitting is Sitting.EQUALIZED) is (voice.arm is Arm.A_EQ)


def test_plan_uses_only_generations_of_the_review_seed():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    sheet = "".join(render_sheet_markdown(plan, sitting) for sitting in Sitting)

    assert " s1" in sheet
    assert " s2" not in sheet
    assert {voice.key.seed for voice in plan.key.voices} == {REVIEW_SEED}


def test_voice_pair_shows_each_voice_with_its_own_canvas():
    metrics = _metrics()
    plan = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    voice_pair = next(p for p in plan.shown_pairs if p.entry.kind is PairKind.VOICE)

    entry = voice_pair.entry
    x_suffix = f"{entry.x_arm} {entry.level} {entry.prompt_id} s1"

    assert voice_pair.x.canvas == f"canvas {x_suffix}"
    assert voice_pair.x.voice == f"voice {x_suffix}"


def test_voice_pair_without_b_voice_is_auto_resolved_as_b_lost_and_not_shown():
    metrics = _metrics(_for_prompts(Level.OFF, Arm.B, 1, {"voice_text": None}))

    plan = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    pair = next(
        p
        for p in plan.key.pairs
        if (p.kind, p.level, p.prompt_id) == (PairKind.VOICE, Level.OFF, "p01")
    )
    assert pair.auto_result is PairResult.B_LOST
    assert pair.auto_reason
    assert pair.pair_id not in {shown.entry.pair_id for shown in plan.shown_pairs}


def test_voice_pair_without_a_voice_is_auto_resolved_as_b_won():
    metrics = _metrics(_for_prompts(Level.OFF, Arm.A_PROD, 1, {"voice_text": None}))

    plan = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    pair = next(
        p
        for p in plan.key.pairs
        if (p.kind, p.level, p.prompt_id) == (PairKind.VOICE, Level.OFF, "p01")
    )
    assert pair.auto_result is PairResult.B_WON


def test_voice_pair_without_either_voice_is_auto_resolved_as_tie():
    overrides = _for_prompts(Level.OFF, Arm.A_PROD, 1, {"voice_text": None})
    overrides |= _for_prompts(Level.OFF, Arm.B, 1, {"voice_text": None})

    plan = build_review(_metrics(overrides), review_seed=REVIEW_SEED, rng_seed=1)

    pair = next(
        p
        for p in plan.key.pairs
        if (p.kind, p.level, p.prompt_id) == (PairKind.VOICE, Level.OFF, "p01")
    )
    assert pair.auto_result is PairResult.TIE


@pytest.mark.parametrize(
    ("empty_arms", "expected"),
    [
        ((Arm.B,), PairResult.B_LOST),
        ((Arm.A_PROD,), PairResult.B_WON),
        ((Arm.A_PROD, Arm.B), PairResult.TIE),
    ],
)
def test_canvas_pair_with_an_empty_canvas_is_auto_resolved(empty_arms, expected):
    overrides = {}
    for arm in empty_arms:
        overrides |= _for_prompts(Level.MEDIUM, arm, 1, {"canvas_text": "  \n"})

    plan = build_review(_metrics(overrides), review_seed=REVIEW_SEED, rng_seed=1)

    pair = next(
        p
        for p in plan.key.pairs
        if (p.kind, p.level, p.prompt_id) == (PairKind.CANVAS, Level.MEDIUM, "p01")
    )
    assert pair.auto_result is expected


def test_invented_claim_section_lists_every_existing_voice_once():
    metrics = _metrics(_for_prompts(Level.OFF, Arm.B, 3, {"voice_text": None}))

    plan = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    listed = [(voice.arm, voice.key) for voice in plan.key.voices]
    assert len(listed) == len(set(listed)) == 16 * 5 - 3
    assert [voice.voice_id for voice in plan.key.voices] == [
        *(f"V{n:02d}" for n in range(1, 62)),
        *(f"W{n:02d}" for n in range(1, 17)),
    ]
    assert plan.voices[0].canvas.startswith("canvas ")


def test_sheet_does_not_reveal_arms_or_the_equalized_block():
    neutral = {
        (level, prompt_id, REVIEW_SEED, arm): {
            "canvas_text": "neutral canvas",
            "voice_text": "neutral voice",
        }
        for level in Level
        for prompt_id in PROMPTS
        for arm in _arms(level)
    }
    plan = build_review(_metrics(neutral), review_seed=REVIEW_SEED, rng_seed=1)

    sheet = render_sheet_markdown(plan, Sitting.PRODUCTION).lower()

    for leak in ("a_prod", "a_eq", "a-prod", "a-eq", "equaliz", "arm"):
        assert leak not in sheet


def test_sheet_lists_shown_pairs_and_voices_but_not_auto_resolved_pairs():
    metrics = _metrics(_for_prompts(Level.OFF, Arm.B, 1, {"voice_text": None}))
    plan = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    auto_id = next(p.pair_id for p in plan.key.pairs if p.auto_result is not None)

    sheets = {sitting: render_sheet_markdown(plan, sitting) for sitting in Sitting}

    assert all(f"## {auto_id} " not in sheet for sheet in sheets.values())
    for pair in plan.shown_pairs:
        for sitting, sheet in sheets.items():
            listed = f"## {pair.entry.pair_id} " in sheet
            assert listed is (pair.entry.sitting is sitting)
    for voice in plan.voices:
        for sitting, sheet in sheets.items():
            listed = f"## {voice.entry.voice_id} " in sheet
            assert listed is (voice.entry.sitting is sitting)


def _production_voice_panels(plan):
    return [
        panel
        for pair in plan.shown_pairs_in(Sitting.PRODUCTION)
        for panel in (pair.x, pair.y)
        if panel.voice is not None
    ]


def test_production_sitting_never_repeats_a_voice_panel_across_voice_pairs():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    panels = [(p.canvas, p.voice) for p in _production_voice_panels(plan)]

    assert len(panels) == len(set(panels)) == 64


def test_production_sitting_never_shows_one_canvas_with_two_voices():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    shown = [(p.canvas, p.voice) for p in _production_voice_panels(plan)]
    shown += [
        (v.canvas, v.voice)
        for v in plan.voices
        if v.entry.sitting is Sitting.PRODUCTION
    ]

    voices_per_canvas = {}
    for canvas, voice in shown:
        voices_per_canvas.setdefault(canvas, set()).add(voice)

    assert all(len(voices) == 1 for voices in voices_per_canvas.values())
    assert "voice a_eq" not in render_sheet_markdown(plan, Sitting.PRODUCTION)


def test_sheet_fence_is_longer_than_any_backtick_run_in_model_text():
    canvas = "Code:\n``````python\nprint(1)\n``````\n"
    metrics = _metrics(_for_prompts(Level.OFF, Arm.B, 16, {"canvas_text": canvas}))
    plan = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    sheet = render_sheet_markdown(plan, Sitting.PRODUCTION)

    assert "```````text\n" + canvas + "```````\n" in sheet


def test_key_json_round_trips():
    metrics = _metrics(_for_prompts(Level.OFF, Arm.B, 2, {"voice_text": None}))
    plan = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    text = render_key_json(plan)

    assert load_key_json(text) == plan.key
    assert json.loads(text)["review_seed"] == REVIEW_SEED


@pytest.mark.parametrize(
    ("sitting", "pairs", "voices"),
    [(Sitting.PRODUCTION, 64, 64), (Sitting.EQUALIZED, 16, 16)],
)
def test_filled_answer_template_parses_per_sitting(sitting, pairs, voices):
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    text = _filled_template(plan, sitting, "=", "Y", "yes")

    answers = parse_answers(text, plan.key, sitting)

    assert set(answers.judgements.values()) == {Judgement.EQUAL}
    assert set(answers.guesses.values()) == {Side.Y}
    assert set(answers.invented.values()) == {True}
    assert len(answers.judgements) == pairs
    assert len(answers.invented) == voices


def test_answers_of_one_sitting_are_rejected_for_the_other():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    text = _filled_template(plan, Sitting.EQUALIZED)

    with pytest.raises(ValueError) as error:
        parse_answers(text, plan.key, Sitting.PRODUCTION)

    message = str(error.value)
    assert "E01: not an entry of the production sitting" in message
    assert "P01: section missing" in message


def test_answer_template_has_no_entry_for_auto_resolved_pairs():
    metrics = _metrics(_for_prompts(Level.OFF, Arm.B, 1, {"voice_text": None}))
    plan = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    auto_id = next(p.pair_id for p in plan.key.pairs if p.auto_result is not None)

    assert all(
        f"[{auto_id}]" not in render_answer_template(plan, sitting)
        for sitting in Sitting
    )


def test_unfilled_answer_template_reports_every_entry_at_once():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    with pytest.raises(ValueError) as error:
        parse_answers(
            render_answer_template(plan, Sitting.EQUALIZED), plan.key, Sitting.EQUALIZED
        )

    message = str(error.value)
    assert "E01.verdict" in message
    assert "W16.invented" in message
    assert "guess_b" not in message


def test_answer_errors_are_aggregated_across_kinds_of_mistake():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    text = (
        _filled_template(plan, Sitting.PRODUCTION)
        .replace('[P03]\nverdict = "X"', '[P03]\nverdict = "maybe"')
        .replace('[P04]\nverdict = "X"\nguess_b = "Y"', '[P04]\nverdict = "X"')
        .replace('[V05]\ninvented = "no"', '[V05]\ninvented = "y"')
        .replace("[P06]", "[P99]")
    )

    with pytest.raises(ValueError) as error:
        parse_answers(text, plan.key, Sitting.PRODUCTION)

    message = str(error.value)
    for expected in ("P03.verdict", "P04.guess_b", "V05.invented", "P06", "P99"):
        assert expected in message


def test_answer_values_are_accepted_in_any_case_and_with_spaces():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    text = _filled_template(plan, Sitting.PRODUCTION, " y", "x ", "YES")

    answers = parse_answers(text, plan.key, Sitting.PRODUCTION)

    assert set(answers.judgements.values()) == {Judgement.Y}
    assert set(answers.guesses.values()) == {Side.X}
    assert set(answers.invented.values()) == {True}


def test_empty_guess_is_an_abstention_but_an_empty_verdict_is_an_error():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    abstaining = _filled_template(plan, Sitting.PRODUCTION, guess="")

    answers = parse_answers(abstaining, plan.key, Sitting.PRODUCTION)
    assert set(answers.guesses.values()) == {None}

    with pytest.raises(ValueError, match=r"P01\.verdict"):
        parse_answers(
            _filled_template(plan, Sitting.PRODUCTION, verdict=""),
            plan.key,
            Sitting.PRODUCTION,
        )


def test_abstentions_count_as_not_correct_and_are_reported_as_not_guessed():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)
    answers = parse_answers(
        _filled_template(plan, Sitting.PRODUCTION, verdict="=", guess=""),
        plan.key,
        Sitting.PRODUCTION,
    )

    report = score(_metrics(), plan.key, answers)

    assert all((g.correct, g.guessed) == (0, 0) for g in report.guesses)
    assert not any(g.possible_bias for g in report.guesses)
    assert "| guessed |" in render_report_markdown(report)


def test_answers_that_are_not_toml_raise_value_error():
    plan = build_review(_metrics(), review_seed=REVIEW_SEED, rng_seed=RNG_SEED)

    with pytest.raises(ValueError, match="TOML"):
        parse_answers("[P01\nverdict = ", plan.key, Sitting.PRODUCTION)


# --- scoring and the decision rule --------------------------------------------


def test_all_six_criteria_at_both_levels_is_go():
    report = _decide()

    assert report.decision is Decision.GO
    assert all(c.passed for level in report.levels for c in level.criteria())


@pytest.mark.parametrize(
    ("failures", "decision"), [(1, Decision.GO), (2, Decision.OWNER)]
)
def test_tag_failure_boundary(failures, decision):
    metrics = _metrics(
        _for_prompts(
            Level.OFF, Arm.B, failures, {"tag_outcome": TagOutcome.MISSING}, (2,)
        )
    )

    report = _decide(metrics)

    assert _level(report, Level.OFF).tag_failures == failures
    assert report.decision is decision


@pytest.mark.parametrize(
    ("losses", "decision"),
    [(4, Decision.GO), (5, Decision.OWNER), (6, Decision.OWNER), (7, Decision.CLOSE)],
)
def test_canvas_loss_boundaries_at_one_level(losses, decision):
    report = _decide(b_lost={(PairKind.CANVAS, Level.MEDIUM): losses})

    assert _level(report, Level.MEDIUM).canvas_losses == losses
    assert report.decision is decision


@pytest.mark.parametrize(
    ("losses", "decision"), [(6, Decision.GO), (7, Decision.OWNER)]
)
def test_voice_loss_boundary(losses, decision):
    report = _decide(b_lost={(PairKind.VOICE, Level.OFF): losses})

    assert _level(report, Level.OFF).voice_losses == losses
    assert report.decision is decision


def test_tie_is_not_a_loss():
    metrics = _metrics()
    key = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED).key
    answers = _answers(key)
    ties = dict.fromkeys(answers.judgements, Judgement.EQUAL)

    report = score(metrics, key, ReviewAnswers(ties, answers.guesses, answers.invented))

    assert _level(report, Level.OFF).canvas_losses == 0
    assert report.decision is Decision.GO


def test_auto_resolved_canvas_losses_count_against_b():
    metrics = _metrics(_for_prompts(Level.OFF, Arm.B, 7, {"canvas_text": ""}))

    report = _decide(metrics)

    assert _level(report, Level.OFF).canvas_losses == 7
    assert report.decision is Decision.CLOSE


@pytest.mark.parametrize(
    ("b_flags", "a_flags", "decision"),
    [(3, 3, Decision.GO), (4, 3, Decision.OWNER)],
)
def test_invented_claim_criterion(b_flags, a_flags, decision):
    flagged = {(Arm.B, Level.OFF): b_flags, (Arm.A_PROD, Level.OFF): a_flags}

    report = _decide(flagged=flagged)

    result = _level(report, Level.OFF)
    assert (result.b_invented, result.a_prod_invented) == (b_flags, a_flags)
    assert report.decision is decision


def test_a_eq_invented_flags_are_reported_but_do_not_count_for_a_prod():
    report = _decide(
        flagged={(Arm.B, Level.MEDIUM): 1},
        equalized={"flagged": {(Arm.A_EQ, Level.MEDIUM): 5}},
    )

    assert _level(report, Level.MEDIUM).a_prod_invented == 0
    assert (report.equalized.a_eq_invented, report.equalized.a_eq_voices) == (5, 16)
    assert report.decision is Decision.OWNER


@pytest.mark.parametrize(
    ("b_runaways", "decision"), [(2, Decision.GO), (3, Decision.OWNER)]
)
def test_runaway_criterion_counts_both_seeds(b_runaways, decision):
    overrides = _for_prompts(Level.OFF, Arm.A_PROD, 1, {"runaway": True}, SEEDS)
    overrides |= _for_prompts(Level.OFF, Arm.B, b_runaways, {"runaway": True}, (2,))

    report = _decide(_metrics(overrides))

    result = _level(report, Level.OFF)
    assert (result.b_runaways, result.a_prod_runaways) == (b_runaways, 2)
    assert report.decision is decision


def _with_gain(level, gain):
    return _for_prompts(
        level, Arm.A_PROD, 16, {"first_sentence_seconds": 1.0 + gain}, SEEDS
    )


@pytest.mark.parametrize(
    ("gain", "decision"), [(1.0, Decision.GO), (0.99, Decision.OWNER)]
)
def test_speed_gain_boundary_at_one_level(gain, decision):
    report = _decide(_metrics(_with_gain(Level.MEDIUM, gain)))

    assert _level(report, Level.MEDIUM).speed.median_seconds == pytest.approx(gain)
    assert report.decision is decision


def test_speed_gain_below_threshold_at_both_levels_is_close():
    overrides = _with_gain(Level.OFF, 0.5) | _with_gain(Level.MEDIUM, 0.9)

    report = _decide(_metrics(overrides))

    assert report.decision is Decision.CLOSE


def test_go_at_one_level_only_goes_to_owner():
    report = _decide(b_lost={(PairKind.VOICE, Level.MEDIUM): 16})

    assert _level(report, Level.OFF).go
    assert not _level(report, Level.MEDIUM).go
    assert report.decision is Decision.OWNER


def test_missing_b_first_sentence_counts_as_negative_infinite_gain():
    overrides = _for_prompts(
        Level.OFF, Arm.B, 16, {"first_sentence_seconds": None}, SEEDS
    )

    report = _decide(_metrics(overrides))

    assert _level(report, Level.OFF).speed.median_seconds == -math.inf
    assert report.decision is Decision.OWNER


def test_missing_a_first_sentence_counts_as_positive_infinite_gain():
    overrides = _for_prompts(
        Level.OFF, Arm.A_PROD, 16, {"first_sentence_seconds": None}, SEEDS
    )

    report = _decide(_metrics(overrides))

    assert _level(report, Level.OFF).speed.median_seconds == math.inf
    assert report.decision is Decision.GO


def test_minority_of_infinite_gains_does_not_move_the_median():
    overrides = _for_prompts(Level.OFF, Arm.B, 15, {"first_sentence_seconds": None})

    report = _decide(_metrics(overrides))

    assert _level(report, Level.OFF).speed.median_seconds == 2.0


def test_pairs_without_either_first_sentence_are_dropped_and_counted():
    overrides = _for_prompts(
        Level.OFF, Arm.B, 3, {"first_sentence_seconds": None}, SEEDS
    )
    overrides |= _for_prompts(
        Level.OFF, Arm.A_PROD, 3, {"first_sentence_seconds": None}, SEEDS
    )

    speed = _level(_decide(_metrics(overrides)), Level.OFF).speed

    assert (speed.matched, speed.dropped) == (26, 6)
    assert speed.median_seconds == 2.0


@pytest.mark.parametrize(
    "production_counts",
    [{}, {"b_lost": {(PairKind.VOICE, Level.OFF): 7}}],
)
def test_equalized_block_never_changes_the_decision(production_counts):
    all_lost = {"b_lost": {(PairKind.EQUALIZED_VOICE, Level.MEDIUM): 16}}

    not_reviewed = _decide(**production_counts)
    all_won = _decide(equalized={}, **production_counts)
    lost = _decide(equalized=all_lost, **production_counts)

    assert not_reviewed.equalized is None
    assert (lost.equalized.voice_losses, lost.equalized.voice_pairs) == (16, 16)
    assert not_reviewed.decision is all_won.decision is lost.decision
    assert not_reviewed.levels == all_won.levels == lost.levels


def test_unreviewed_equalized_block_is_reported_as_not_reviewed():
    text = render_report_markdown(_decide())

    assert "not reviewed" in text


def test_equalized_guesses_are_reported_as_unreliable_and_never_flagged():
    report = _decide(equalized={})

    assert (report.equalized.guess_correct, report.equalized.guess_shown) == (16, 16)
    assert all(g.kind is not PairKind.EQUALIZED_VOICE for g in report.guesses)
    assert "unreliable" in render_report_markdown(report)


@pytest.mark.parametrize(("wrong", "flagged"), [(3, True), (4, False)])
def test_guess_bias_flag_at_13_of_16_correct(wrong, flagged):
    report = _decide(wrong_guesses={(PairKind.CANVAS, Level.OFF): wrong})

    accuracy = next(
        g for g in report.guesses if (g.kind, g.level) == (PairKind.CANVAS, Level.OFF)
    )
    assert (accuracy.correct, accuracy.shown) == (16 - wrong, 16)
    assert accuracy.possible_bias is flagged


def test_guess_bias_threshold_scales_with_fewer_shown_pairs():
    metrics = _metrics(_for_prompts(Level.OFF, Arm.B, 8, {"voice_text": None}))

    report = _decide(metrics, wrong_guesses={(PairKind.VOICE, Level.OFF): 1})

    accuracy = next(
        g for g in report.guesses if (g.kind, g.level) == (PairKind.VOICE, Level.OFF)
    )
    assert (accuracy.correct, accuracy.shown) == (7, 8)
    assert accuracy.possible_bias


def test_hygiene_and_cost_are_aggregated_per_arm_and_level():
    overrides = _for_prompts(
        Level.OFF,
        Arm.B,
        2,
        {"hygiene": VoiceHygiene(markdown_markers=2, raw_urls=1), "eval_count_sum": 7},
        SEEDS,
    )

    report = _decide(_metrics(overrides))

    usage = next(u for u in report.arm_usage if (u.arm, u.level) == (Arm.B, Level.OFF))
    assert usage.hygiene == VoiceHygiene(markdown_markers=8, raw_urls=4)
    assert usage.eval_count_sum == 4 * 7 + 28 * 100
    assert usage.median_wall_seconds == 5.0
    assert usage.generations == 32


def test_a_eq_wall_time_is_not_reported_but_its_counts_are():
    report = _decide()

    usage = next(u for u in report.arm_usage if u.arm is Arm.A_EQ)
    text = render_report_markdown(report)
    a_eq_row = next(line for line in text.splitlines() if "| a_eq |" in line)

    assert usage.median_wall_seconds is None
    assert usage.eval_count_sum == 32 * 100
    assert "| n/a |" in a_eq_row


def test_report_markdown_is_ascii_and_states_decision_and_thresholds():
    overrides = _for_prompts(
        Level.OFF, Arm.B, 16, {"first_sentence_seconds": None}, SEEDS
    )
    report = _decide(_metrics(overrides))

    text = render_report_markdown(report)

    assert text.isascii()
    assert "OWNER" in text
    assert "-inf" in text
    assert "<= 4" in text


def test_score_rejects_a_key_whose_generation_metrics_are_missing():
    metrics = _metrics()
    key = build_review(metrics, review_seed=REVIEW_SEED, rng_seed=RNG_SEED).key
    incomplete = [m for m in metrics if m.key.prompt_id != "p05"]

    with pytest.raises(ValueError, match="p05"):
        score(incomplete, key, _answers(key))
