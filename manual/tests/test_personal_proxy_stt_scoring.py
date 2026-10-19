from manual.personal_proxy.corpus import utterance_by_id
from manual.personal_proxy.stt_scoring import (
    Adequacy,
    Coexistence,
    Engine,
    EngineMetrics,
    Outcome,
    adequacy,
    aggregate,
    choose,
    control_is_clean,
    cpu_resource_ok,
    fidelity_by_group,
    overall_fidelity,
    render_report,
    resource_ok,
    score_transcript,
    span_group,
)


def _score(
    engine,
    subject="id_short_call",
    pass_no=2,
    text="Позвони Марине Крыловой.",
    seconds=1.0,
    audio=4.0,
):
    return score_transcript(
        engine, utterance_by_id(subject), pass_no, text, seconds, audio
    )


def _found(score):
    return {g: (f, t) for g, f, t in score.found_by_group}


def _metrics(engine, failures=0, fidelity=(9, 10), seconds=1.0):
    return EngineMetrics(
        engine,
        88,
        failures,
        0.1,
        {"numeric": fidelity, "email": (0, 0), "person": (0, 0), "other": (0, 0)},
        seconds,
        seconds,
        0.2,
    )


def test_span_groups_split_numeric_email_person_and_other():
    phone = utterance_by_id("id_phone_words").spans[0]
    email = utterance_by_id("id_email").spans[0]
    person = utterance_by_id("id_short_call").spans[0]
    org = utterance_by_id("id_employer_boss").spans[0]

    assert [span_group(s) for s in (phone, email, person, org)] == [
        "numeric",
        "email",
        "person",
        "other",
    ]


def test_a_correct_transcript_finds_every_span_and_is_not_a_failure():
    score = _score(Engine.GIGAAM)

    assert not score.audio_failure
    assert _found(score)["person"] == (1, 1)


def test_a_misheard_name_is_not_found():
    score = _score(Engine.GIGAAM, text="Позвони Лене Орловой.")

    assert _found(score)["person"] == (0, 1)


def test_digits_in_a_different_grouping_are_still_found():
    score = _score(
        Engine.WHISPER_RU,
        "id_sms_code",
        text="Код из смс: 864219.",
    )

    assert _found(score)["numeric"] == (1, 1)
    assert not score.audio_failure


def test_an_answer_instead_of_a_transcript_is_a_failure():
    score = _score(
        Engine.WHISPER_RU,
        "n_borscht",
        text="Конечно, вот рецепт: свёкла, капуста, картофель, морковь, лук, вода.",
    )

    assert score.audio_failure


def test_controls_are_clean_only_without_word_characters():
    assert control_is_clean("")
    assert control_is_clean("  . ... ")
    assert not control_is_clean("Продолжение следует")


def test_fidelity_for_the_baseline_counts_found_spans_by_group():
    pairs = [
        (utterance_by_id("id_short_call"), "Позвони Марине Крыловой."),
        (utterance_by_id("id_short_write"), "Напиши кому-то."),
    ]

    groups = fidelity_by_group(pairs)

    assert groups["person"] == (1, 2)
    assert overall_fidelity(groups) == 0.5


def test_aggregate_takes_warm_timing_from_the_second_pass_only():
    scores = [
        _score(Engine.GIGAAM, pass_no=1, seconds=9.0),
        _score(Engine.GIGAAM, pass_no=2, seconds=1.0),
        _score(Engine.WHISPER_RU, pass_no=2, seconds=5.0),
    ]

    metrics = aggregate(Engine.GIGAAM, scores)

    assert (metrics.generations, metrics.median_seconds) == (2, 1.0)
    assert metrics.median_rtf == 0.25


def _co(share=1.0, engine_s=1.0, isolated=1.0):
    return Coexistence(Engine.GIGAAM, 1.0, share, engine_s, isolated, 1.0, 1.0)


def test_resources_need_full_gpu_share_a_fast_engine_and_no_big_slowdown():
    assert resource_ok(_co())
    assert not resource_ok(_co(share=0.9))
    assert not resource_ok(_co(engine_s=3.5, isolated=3.5))
    assert not resource_ok(_co(engine_s=2.1, isolated=1.0))
    assert not resource_ok(None)


def test_the_cpu_path_is_adequate_at_three_seconds_or_less():
    assert cpu_resource_ok(_metrics(Engine.GIGAAM_CPU, seconds=3.0))
    assert not cpu_resource_ok(_metrics(Engine.GIGAAM_CPU, seconds=3.1))


def test_adequacy_needs_accuracy_fidelity_and_resources():
    good = _metrics(Engine.GIGAAM, failures=8, fidelity=(9, 10))

    assert adequacy(good, 0.9, True).adequate
    assert not adequacy(_metrics(Engine.GIGAAM, failures=9), 0.9, True).adequate
    assert not adequacy(good, 0.95, True).adequate
    assert not adequacy(good, 0.9, False).adequate


def test_a_single_adequate_engine_wins_and_none_means_none():
    w, g = _metrics(Engine.WHISPER_RU), _metrics(Engine.GIGAAM)

    assert choose(w, g, True, False) is Outcome.WHISPER
    assert choose(w, g, False, True) is Outcome.GIGAAM
    assert choose(w, g, False, False) is Outcome.NONE_ADEQUATE


def test_two_adequate_engines_compare_failures_then_fidelity_then_speed():
    assert (
        choose(
            _metrics(Engine.WHISPER_RU, failures=6),
            _metrics(Engine.GIGAAM, failures=3),
            True,
            True,
        )
        is Outcome.GIGAAM
    )
    assert (
        choose(
            _metrics(Engine.WHISPER_RU, failures=4, fidelity=(95, 100)),
            _metrics(Engine.GIGAAM, failures=4, fidelity=(90, 100)),
            True,
            True,
        )
        is Outcome.WHISPER
    )
    assert (
        choose(
            _metrics(Engine.WHISPER_RU, failures=4, seconds=3.0),
            _metrics(Engine.GIGAAM, failures=4, seconds=1.0),
            True,
            True,
        )
        is Outcome.GIGAAM
    )
    assert (
        choose(
            _metrics(Engine.WHISPER_RU, failures=4, seconds=1.2),
            _metrics(Engine.GIGAAM, failures=4, seconds=1.0),
            True,
            True,
        )
        is Outcome.OWNER
    )


def test_report_lists_failures_with_expected_and_actual_and_the_outcome():
    scores = [
        _score(Engine.GIGAAM, "id_sms_code", text="864219"),
        _score(Engine.GIGAAM, "id_short_call"),
    ]
    metrics = [aggregate(Engine.GIGAAM, scores)]

    text = render_report(
        meta={"model": "m"},
        metrics=metrics,
        scores=scores,
        controls={Engine.GIGAAM: [("Продолжение следует", False)]},
        baseline={
            "numeric": (1, 2),
            "email": (0, 0),
            "person": (0, 0),
            "other": (0, 0),
        },
        baseline_failures=22,
        baseline_wer=0.165,
        adequacies={Engine.GIGAAM: Adequacy(True, True, False)},
        outcome=Outcome.NONE_ADEQUATE,
        memory={Engine.GIGAAM: {"peak_mib": 1000}},
        coexistence=[_co()],
    )

    assert "Outcome: **NONE_ADEQUATE**" in text
    assert "expected: Код из смс" in text
    assert "actual:   864219" in text
    assert "TEXT: 'Продолжение следует'" in text
    assert "Ollama GPU share 1.0 -> 1.0" in text
