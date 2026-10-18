from manual.personal_proxy.corpus import utterance_by_id
from manual.personal_proxy.transcription_ab import (
    VARIANT_B_INSTRUCTION,
    PairedCounts,
    TranscriptScore,
    Variant,
    VariantMetrics,
    Verdict,
    aggregate,
    decide,
    paired_counts,
    reference_text,
    render_report,
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

    assert decide(a, _metrics(Variant.B, 20)) is Verdict.B_BETTER
    assert decide(a, _metrics(Variant.B, 21)) is Verdict.NO_DIFFERENCE


def test_worse_needs_four_more_failures():
    a = _metrics(Variant.A, 10)

    assert decide(a, _metrics(Variant.B, 14)) is Verdict.B_WORSE
    assert decide(a, _metrics(Variant.B, 13)) is Verdict.NO_DIFFERENCE


def test_fewer_failures_with_a_wer_regression_goes_to_the_owner():
    a = _metrics(Variant.A, 24, median_wer=0.10)

    assert decide(a, _metrics(Variant.B, 10, median_wer=0.13)) is Verdict.OWNER


def test_a_wer_margin_of_exactly_two_hundredths_still_counts_as_better():
    a = _metrics(Variant.A, 24, median_wer=0.10)

    assert decide(a, _metrics(Variant.B, 10, median_wer=0.12)) is Verdict.B_BETTER


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

    assert paired_counts(scores) == PairedCounts(a_only=1, b_only=1, both=1)


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
        controls={Variant.A: {"control_silence": ["", "x"]}},
        identical_to_main_run=(80, 88),
    )

    assert "Verdict: **NO_DIFFERENCE**" in text
    assert "expected: Код из смс" in text
    assert "actual:   864219" in text
    assert "Determinism check: 80/88" in text
    assert "control_silence" in text
