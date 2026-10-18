from dataclasses import replace

from manual.personal_proxy.decision import decide
from manual.personal_proxy.records import Arm
from manual.personal_proxy.report import render_report, stratum_label, stratum_rows
from manual.personal_proxy.scoring import ArmMetrics, GenerationScore
from manual.tests.test_personal_proxy_decision import _combined, _metrics


def _score(subject_id, arm=Arm.C_USER, audio_failure=False):
    return GenerationScore(
        subject_id=subject_id,
        arm=arm,
        seed=1,
        is_control=False,
        errored=False,
        valid=True,
        failure=None,
        verdict=None,
        raw_transcript="x",
        wer=0.0,
        audio_failure=audio_failure,
        spans_total=0,
        leaked_span_ids=(),
        leak_renderings=(),
        mapping_checked=0,
        mapping_errors=0,
        preservation=None,
        false_refusal=False,
        missed_refusal=False,
        fabrication=False,
        total_seconds=1.0,
        cold=False,
    )


def test_stratum_labels_split_at_two_and_fifteen_seconds():
    assert stratum_label(1.3).startswith("short")
    assert stratum_label(2.0).startswith("short")
    assert stratum_label(8.0) == "medium"
    assert stratum_label(15.0).startswith("long")


def test_stratum_rows_count_audio_failures_per_length_bucket():
    scores = [
        _score("a", audio_failure=True),
        _score("b"),
        _score("c", audio_failure=True),
    ]
    durations = {"a": 1.0, "b": 1.5, "c": 20.0}

    rows = stratum_rows(Arm.C_USER, scores, durations.__getitem__)

    assert {(r.label[:5], r.generations, r.audio_failures) for r in rows} == {
        ("short", 2, 1),
        ("long ", 1, 1),
    }


def _report(base, *combined, durations=lambda _: 5.0):
    decision = decide(base, list(combined))
    return render_report(
        meta={"model": "gemma4:12b"},
        decision=decision,
        metrics=[base, *combined],
        scores=[],
        duration_of=durations,
    )


def test_report_states_the_outcome_and_every_criterion():
    base = _metrics(Arm.T_PLUS_S)

    text = _report(base, _combined(Arm.C_USER), _combined(Arm.C_SYSTEM, valid=70))

    assert "Outcome: **GO**" in text
    assert "PASS 1 validity" in text
    assert "FAIL 1 validity" in text
    assert "model: gemma4:12b" in text


def test_report_flags_the_baseline_stop_condition():
    base = replace(_metrics(Arm.T_PLUS_S), audio_failures=20)

    assert "STOP CONDITION" in _report(base, _combined(Arm.C_USER))


def test_report_is_ascii_only():
    base = _metrics(Arm.T_PLUS_S)

    text = _report(base, _combined(Arm.C_USER))

    assert text.isascii()


def test_report_renders_missing_values_as_na():
    base = _metrics(Arm.T_PLUS_S)

    text = _report(base, _combined(Arm.C_USER, median_wer=None))

    assert "n/a" in text


def test_false_refusals_are_listed_per_arm_with_seed():
    scores = [
        replace(_score("id_card", Arm.C_USER), false_refusal=True),
        replace(_score("id_email", Arm.C_USER), false_refusal=True),
        replace(_score("id_card", Arm.C_SYSTEM), false_refusal=False),
    ]

    from manual.personal_proxy.report import false_refusal_ids

    assert false_refusal_ids(Arm.C_USER, scores) == ["id_card/s1", "id_email/s1"]
    assert false_refusal_ids(Arm.C_SYSTEM, scores) == []


def test_report_splits_false_refusals_by_whether_the_data_is_the_whole_request():
    base = _metrics(Arm.T_PLUS_S)
    decision = decide(base, [_combined(Arm.C_USER)])
    scores = [
        replace(_score("id_card", Arm.C_USER), false_refusal=True),
        replace(_score("id_email", Arm.C_USER), false_refusal=True),
    ]

    text = render_report(
        meta={},
        decision=decision,
        metrics=[base, _combined(Arm.C_USER)],
        scores=scores,
        duration_of=lambda _: 5.0,
    )

    assert "## False refusals" in text
    assert (
        "c_user: 2 total; data is the whole request: 1 ['id_card/s1']; "
        "other: 1 ['id_email/s1']"
    ) in text
    assert "looks safer on leaks" in text


def test_metrics_helper_types_line_up():
    assert isinstance(_metrics(Arm.C_USER), ArmMetrics)
