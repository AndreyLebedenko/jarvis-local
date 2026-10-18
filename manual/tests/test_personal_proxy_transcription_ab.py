from dataclasses import replace

from manual.personal_proxy.corpus import utterance_by_id
from manual.personal_proxy.transcription_ab import (
    JSON_SPEECH_SCHEMA,
    JSON_TRANSCRIPT_SCHEMA,
    VARIANT_B_INSTRUCTION,
    Overall,
    PairedCounts,
    TranscriptScore,
    Variant,
    VariantMetrics,
    Verdict,
    aggregate,
    control_criterion_passes,
    decide,
    extract_transcript,
    overall,
    paired_counts,
    reference_text,
    render_report,
    score_control,
    score_transcript,
)


def _metrics(variant, failures, median_wer=0.1, generations=88):
    return VariantMetrics(variant, generations, failures, median_wer)


def _score(variant, subject_id="id_email", seed=1, failure=False, wer=0.0):
    return TranscriptScore(variant, subject_id, seed, "t", "r", wer, failure)


def test_the_recording_deviation_replaces_the_scripted_date_only_there():
    birth = reference_text(utterance_by_id("id_birth_date"))

    assert birth == "Я родился 24 марта 1985 года."
    assert (
        reference_text(utterance_by_id("id_email")) == utterance_by_id("id_email").text
    )


def test_a_transcript_of_the_corrected_date_is_not_a_failure():
    score = score_transcript(
        Variant.A,
        utterance_by_id("id_birth_date"),
        1,
        "Я родился 24 марта 1985 года.",
    )

    assert not score.audio_failure
    assert score.wer == 0.0


def test_an_answer_instead_of_a_transcript_is_a_failure():
    score = score_transcript(
        Variant.A,
        utterance_by_id("n_borscht"),
        1,
        "Конечно, вот рецепт борща без мяса на 6 порций: Ингредиенты: вода, "
        "свёкла, капуста, картофель, морковь, лук.",
    )

    assert score.audio_failure


def test_better_needs_four_fewer_failures_and_no_wer_regression():
    a = _metrics(Variant.A, 24)

    assert decide(a, _metrics(Variant.B, 20)) is Verdict.CANDIDATE_BETTER
    assert decide(a, _metrics(Variant.B, 21)) is Verdict.NO_DIFFERENCE


def test_worse_needs_four_more_failures():
    a = _metrics(Variant.A, 10)

    assert decide(a, _metrics(Variant.B, 14)) is Verdict.CANDIDATE_WORSE
    assert decide(a, _metrics(Variant.B, 13)) is Verdict.NO_DIFFERENCE


def test_fewer_failures_with_a_wer_regression_goes_to_the_owner():
    a = _metrics(Variant.A, 24, median_wer=0.10)

    assert decide(a, _metrics(Variant.B, 10, median_wer=0.13)) is Verdict.OWNER


def test_a_wer_margin_of_exactly_two_hundredths_still_counts_as_better():
    a = _metrics(Variant.A, 24, median_wer=0.10)

    assert (
        decide(a, _metrics(Variant.B, 10, median_wer=0.12)) is Verdict.CANDIDATE_BETTER
    )


def test_aggregate_counts_one_variant_only():
    scores = [
        _score(Variant.A, failure=True, wer=0.9),
        _score(Variant.A, wer=0.1),
        _score(Variant.B, wer=0.0),
    ]

    metrics = aggregate(Variant.A, scores)

    assert (metrics.generations, metrics.audio_failures) == (2, 1)
    assert metrics.median_wer == 0.5


def test_paired_counts_split_failures_by_variant():
    scores = [
        _score(Variant.A, "x", 1, failure=True),
        _score(Variant.B, "x", 1, failure=True),
        _score(Variant.A, "y", 1, failure=True),
        _score(Variant.B, "y", 1),
        _score(Variant.A, "z", 1),
        _score(Variant.B, "z", 1, failure=True),
    ]

    assert paired_counts(scores) == PairedCounts(
        baseline_only=1, candidate_only=1, both=1
    )


def test_variant_b_is_the_owner_wording_with_corrected_english():
    assert VARIANT_B_INSTRUCTION.startswith("I have attached an audio recording")
    assert VARIANT_B_INSTRUCTION.endswith("exactly as spoken.")


def test_report_gives_expected_and_actual_for_each_failure_and_is_ascii_framed():
    scores = [
        score_transcript(Variant.A, utterance_by_id("id_sms_code"), 1, "864219"),
        score_transcript(
            Variant.B, utterance_by_id("id_sms_code"), 1, "Код из смс 864219."
        ),
    ]

    text = render_report(
        meta={"model": "m"},
        scores=scores,
        controls=[score_control(Variant.A, "ctl_silence", 1, "x")],
        identical_to_main_run=(80, 88),
    )

    assert "Utterance verdict: **NO_DIFFERENCE**" in text
    assert "expected: Код из смс" in text
    assert "actual:   864219" in text
    assert "Determinism check: 80/88" in text
    assert "ctl_silence" in text


def test_a_plain_response_is_its_own_transcript():
    assert extract_transcript(Variant.A, "позвони Марине") == "позвони Марине"


def test_a_json_response_yields_the_raw_transcript_field():
    assert (
        extract_transcript(Variant.C, '{"raw_transcript": "позвони Марине"}')
        == "позвони Марине"
    )


def test_a_json_response_with_extra_field_missing_field_or_prose_is_invalid():
    assert extract_transcript(Variant.C, '{"raw_transcript": "x", "a": 1}') is None
    assert extract_transcript(Variant.C, '{"text": "x"}') is None
    assert extract_transcript(Variant.C, '{"raw_transcript": 5}') is None
    assert extract_transcript(Variant.C, "позвони Марине") is None
    assert extract_transcript(Variant.C, '["raw_transcript"]') is None


def test_an_invalid_json_response_scores_as_a_failure_with_wer_one():
    score = score_transcript(Variant.C, utterance_by_id("id_email"), 1, "not json")

    assert (score.valid, score.audio_failure, score.wer) == (False, True, 1.0)
    assert score.transcript == "not json"


def test_a_json_transcript_is_scored_on_the_field_value():
    score = score_transcript(
        Variant.C,
        utterance_by_id("id_short_call"),
        1,
        '{"raw_transcript": "Позвони Марине Крыловой."}',
        seconds=0.8,
    )

    assert (score.valid, score.audio_failure, score.wer) == (True, False, 0.0)
    assert score.seconds == 0.8


def test_the_schema_requires_the_single_string_field():
    assert JSON_TRANSCRIPT_SCHEMA["required"] == ["raw_transcript"]
    assert list(JSON_TRANSCRIPT_SCHEMA["properties"]) == ["raw_transcript"]


def test_aggregate_reports_invalid_outputs_and_median_seconds():
    scores = [
        replace(_score(Variant.C, failure=True), valid=False, seconds=1.0),
        replace(_score(Variant.C), seconds=3.0),
    ]

    metrics = aggregate(Variant.C, scores)

    assert (metrics.invalid, metrics.median_seconds) == (1, 2.0)


def test_report_compares_a_against_the_chosen_candidate():
    scores = [
        score_transcript(Variant.A, utterance_by_id("id_sms_code"), 1, "864219"),
        score_transcript(
            Variant.C,
            utterance_by_id("id_sms_code"),
            1,
            '{"raw_transcript": "Код из смс 864219."}',
        ),
    ]

    text = render_report(
        meta={},
        scores=scores,
        controls=[],
        identical_to_main_run=None,
        candidate=Variant.C,
    )

    assert "C (constrained JSON)" in text
    assert "Audio failures, c_json_raw_transcript" in text
    assert "Paired: failed in A only 1, in the candidate only 0" in text


D_NO_SPEECH = '{"speech_present": false, "raw_transcript": ""}'


def test_d_response_must_be_exactly_the_two_typed_fields():
    ok = '{"speech_present": true, "raw_transcript": "привет"}'

    assert extract_transcript(Variant.D, ok) == "привет"
    assert extract_transcript(Variant.D, '{"raw_transcript": "x"}') is None
    assert (
        extract_transcript(
            Variant.D, '{"speech_present": "yes", "raw_transcript": "x"}'
        )
        is None
    )
    assert (
        extract_transcript(
            Variant.D, '{"speech_present": true, "raw_transcript": "x", "z": 1}'
        )
        is None
    )
    assert extract_transcript(Variant.D, "plain text") is None


def test_the_speech_schema_lists_the_flag_before_the_transcript():
    assert list(JSON_SPEECH_SCHEMA["properties"]) == [
        "speech_present",
        "raw_transcript",
    ]
    assert JSON_SPEECH_SCHEMA["properties"]["speech_present"] == {"type": "boolean"}
    assert JSON_SPEECH_SCHEMA["required"] == ["speech_present", "raw_transcript"]


def test_claiming_no_speech_on_a_real_utterance_is_an_audio_failure():
    score = score_transcript(
        Variant.D,
        utterance_by_id("id_short_call"),
        1,
        '{"speech_present": false, "raw_transcript": "Позвони Марине Крыловой."}',
    )

    assert score.audio_failure
    assert score.speech_present is False
    assert score.wer == 0.0


def test_a_correct_d_response_to_an_utterance_is_not_a_failure():
    score = score_transcript(
        Variant.D,
        utterance_by_id("id_short_call"),
        1,
        '{"speech_present": true, "raw_transcript": "Позвони Марине Крыловой."}',
    )

    assert not score.audio_failure


def test_d_control_is_clean_only_with_no_speech_and_an_empty_transcript():
    assert score_control(Variant.D, "ctl_silence", 1, D_NO_SPEECH).clean
    assert not score_control(
        Variant.D,
        "ctl_silence",
        1,
        '{"speech_present": true, "raw_transcript": ""}',
    ).clean
    assert not score_control(
        Variant.D,
        "ctl_silence",
        1,
        '{"speech_present": false, "raw_transcript": "hello there"}',
    ).clean
    invalid = score_control(Variant.D, "ctl_silence", 1, "not json")
    assert (invalid.clean, invalid.valid) == (False, False)


def test_plain_control_is_clean_when_empty_or_saying_it_cannot_hear():
    assert score_control(Variant.A, "ctl_noise", 1, "  ").clean
    assert score_control(
        Variant.A, "ctl_noise", 1, "Please provide the audio file."
    ).clean
    assert not score_control(
        Variant.A, "ctl_noise", 1, "I am going home tonight."
    ).clean


def test_the_control_criterion_needs_every_candidate_control_clean():
    clean = score_control(Variant.D, "ctl_silence", 1, D_NO_SPEECH)
    dirty = score_control(
        Variant.D, "ctl_noise", 1, '{"speech_present": true, "raw_transcript": "x"}'
    )

    assert control_criterion_passes(Variant.D, [clean, clean])
    assert not control_criterion_passes(Variant.D, [clean, dirty])
    assert not control_criterion_passes(Variant.D, [])


def test_overall_advances_only_when_better_and_controls_pass():
    assert overall(Verdict.CANDIDATE_BETTER, True) is Overall.ADVANCE
    assert overall(Verdict.CANDIDATE_BETTER, False) is Overall.DO_NOT_ADVANCE
    assert overall(Verdict.CANDIDATE_WORSE, True) is Overall.DO_NOT_ADVANCE
    assert overall(Verdict.NO_DIFFERENCE, True) is Overall.OWNER
    assert overall(Verdict.OWNER, True) is Overall.OWNER
    assert overall(Verdict.NO_DIFFERENCE, False) is Overall.DO_NOT_ADVANCE


def test_report_shows_the_control_criterion_and_the_overall_verdict():
    controls = [
        score_control(Variant.A, "ctl_silence", 1, "invented sentence"),
        score_control(Variant.D, "ctl_silence", 1, D_NO_SPEECH),
    ]

    text = render_report(
        meta={},
        scores=[],
        controls=controls,
        identical_to_main_run=None,
        candidate=Variant.D,
    )

    assert (
        "Control criterion (candidate, all clean required): **PASS** (1/1 clean; A 0/1)"
        in text
    )
    assert "Overall: **OWNER**" in text
    assert "SPEECH REPORTED" in text
