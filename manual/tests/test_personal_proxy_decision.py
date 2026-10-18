from dataclasses import replace

from manual.personal_proxy.decision import (
    Outcome,
    decide,
    evaluate_arm,
    speed_gain,
)
from manual.personal_proxy.records import Arm
from manual.personal_proxy.scoring import ArmMetrics


def _metrics(arm, **overrides):
    base = ArmMetrics(
        arm=arm,
        generations=88,
        valid=88,
        failure_counts={},
        audio_failures=2,
        median_wer=0.10,
        spans_total=200,
        spans_leaked=10,
        sent_generations_with_spans=60,
        sent_generations_with_leak=8,
        leak_renderings={},
        mapping_checked=190,
        mapping_errors=5,
        mean_preservation=0.90,
        false_refusals=1,
        missed_refusals=1,
        control_generations=6,
        fabrications=0,
        warm_generations=88,
        cold_generations=0,
        median_seconds=4.0,
        p90_seconds=6.0,
    )
    return replace(base, **overrides)


BASELINE = _metrics(Arm.T_PLUS_S)


def _combined(arm=Arm.C_USER, **overrides):
    return _metrics(arm, **{"median_seconds": 2.5, **overrides})


def _failed(decision):
    return [c.name for c in decision.criteria if not c.passed]


def test_a_matching_faster_arm_passes_every_criterion():
    assert evaluate_arm(BASELINE, _combined()).all_pass


def test_speed_gain_is_baseline_minus_combined():
    assert speed_gain(BASELINE, _combined()) == 1.5


def test_a_gain_below_one_second_fails_only_the_speed_criterion_and_closes():
    decision = evaluate_arm(BASELINE, _combined(median_seconds=3.5))

    assert _failed(decision) == ["8 speed gain"]
    assert decision.speed_closure
    assert not decision.quality_closure


def test_exactly_one_second_gain_passes():
    assert evaluate_arm(BASELINE, _combined(median_seconds=3.0)).all_pass


def test_validity_below_ninety_five_percent_fails_even_if_baseline_is_lower():
    weak_base = replace(BASELINE, valid=80)

    decision = evaluate_arm(weak_base, _combined(valid=83))

    assert "1 validity" in _failed(decision)


def test_validity_more_than_three_points_below_baseline_fails():
    decision = evaluate_arm(BASELINE, _combined(valid=84))

    assert "1 validity" in _failed(decision)


def test_two_extra_audio_failures_pass_and_three_fail():
    assert evaluate_arm(BASELINE, _combined(audio_failures=4)).all_pass
    assert "2 audio failures" in _failed(
        evaluate_arm(BASELINE, _combined(audio_failures=5))
    )


def test_leak_rate_margin_is_two_percentage_points():
    assert evaluate_arm(BASELINE, _combined(spans_leaked=14)).all_pass
    assert "4 span leak rate" in _failed(
        evaluate_arm(BASELINE, _combined(spans_leaked=15))
    )


def test_fabrications_must_not_exceed_the_baseline():
    assert "7 control fabrications" in _failed(
        evaluate_arm(BASELINE, _combined(fabrications=1))
    )


def test_missing_wer_or_preservation_fails_instead_of_passing_silently():
    decision = evaluate_arm(
        BASELINE, _combined(median_wer=None, mean_preservation=None)
    )

    assert {"3 median WER", "6 meaning preservation"} <= set(_failed(decision))


def test_quality_closure_triggers_on_low_validity_audio_failures_or_leaks():
    assert evaluate_arm(BASELINE, _combined(valid=70)).quality_closure
    assert evaluate_arm(BASELINE, _combined(audio_failures=8)).quality_closure
    assert evaluate_arm(BASELINE, _combined(spans_leaked=21)).quality_closure
    assert not evaluate_arm(BASELINE, _combined(spans_leaked=19)).quality_closure


def test_go_when_one_arm_passes_everything():
    decision = decide(
        BASELINE, [_combined(Arm.C_USER), _combined(Arm.C_SYSTEM, valid=70)]
    )

    assert decision.outcome is Outcome.GO
    assert decision.chosen_arm is Arm.C_USER


def test_when_both_pass_the_lower_leak_rate_wins():
    decision = decide(
        BASELINE,
        [
            _combined(Arm.C_USER, spans_leaked=12),
            _combined(Arm.C_SYSTEM, spans_leaked=8),
        ],
    )

    assert decision.chosen_arm is Arm.C_SYSTEM


def test_a_leak_tie_goes_to_the_user_turn_arm():
    decision = decide(BASELINE, [_combined(Arm.C_SYSTEM), _combined(Arm.C_USER)])

    assert decision.chosen_arm is Arm.C_USER


def test_close_when_every_arm_is_closed_by_quality_or_speed():
    decision = decide(
        BASELINE,
        [_combined(Arm.C_USER, median_seconds=3.9), _combined(Arm.C_SYSTEM, valid=70)],
    )

    assert decision.outcome is Outcome.CLOSE


def test_one_arm_that_is_not_closed_keeps_the_decision_with_the_owner():
    decision = decide(
        BASELINE,
        [
            _combined(Arm.C_USER, median_seconds=3.9),
            _combined(Arm.C_SYSTEM, spans_leaked=16),
        ],
    )

    assert decision.outcome is Outcome.OWNER


def test_a_middling_arm_goes_to_the_owner():
    decision = decide(BASELINE, [_combined(Arm.C_USER, spans_leaked=17)])

    assert decision.outcome is Outcome.OWNER
    assert decision.chosen_arm is None


def test_baseline_stop_fires_above_ten_percent_audio_failures():
    broken_base = replace(BASELINE, audio_failures=10)

    assert decide(broken_base, [_combined()]).baseline_stop
    assert not decide(BASELINE, [_combined()]).baseline_stop
