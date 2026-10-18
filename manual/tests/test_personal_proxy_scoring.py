import json

from manual.personal_proxy_corpus import (
    CONTROLS,
    Span,
    SpanType,
    Verdict,
    utterance_by_id,
)
from manual.personal_proxy_parse import FailureClass
from manual.personal_proxy_records import (
    Arm,
    CallRecord,
    CallStage,
    GenerationRecord,
)
from manual.personal_proxy_scoring import (
    aggregate,
    leak_breakdown,
    leaked_spans,
    looks_like_audio_failure,
    mapping_matches,
    meaning_preservation,
    percentile_nearest_rank,
    score_generation,
    score_records,
)


def _call(stage, text, done_reason="stop", total=1.0, load=0.0):
    return CallRecord(stage, {}, text, done_reason, 5, 5, load, total)


def _json(**fields):
    base = {
        "verdict": "send",
        "reason": "",
        "raw_transcript": "",
        "sanitized_text": "",
        "mapping": {},
    }
    return json.dumps({**base, **fields}, ensure_ascii=False)


def _combined(subject_id, arm=Arm.C_USER, seed=1, **fields):
    return GenerationRecord(
        subject_id, arm, seed, (_call(CallStage.COMBINED, _json(**fields)),)
    )


def _two_step(subject_id, transcript, sanitize_json, seed=1):
    return GenerationRecord(
        subject_id,
        Arm.T_PLUS_S,
        seed,
        (
            _call(CallStage.TRANSCRIBE, transcript, total=1.0),
            _call(CallStage.SANITIZE_TEXT, sanitize_json, total=0.5),
        ),
    )


def test_a_clean_combined_output_has_no_leak_and_a_correct_mapping():
    utterance = utterance_by_id("id_short_call")
    record = _combined(
        "id_short_call",
        raw_transcript="Позвони Марине Крыловой.",
        sanitized_text="Позвони <PERSON_1>.",
        mapping={"<PERSON_1>": "Марина Крылова"},
    )

    score = score_generation(record, utterance)

    assert (score.valid, score.leaked_span_ids, score.mapping_errors) == (True, (), 0)
    assert score.mapping_checked == 1
    assert score.wer == 0.0
    assert score.audio_failure is False


def test_a_leaked_name_is_found_through_a_declined_form():
    utterance = utterance_by_id("id_short_call")
    record = _combined(
        "id_short_call",
        raw_transcript="Позвони Марине Крыловой.",
        sanitized_text="Позвони Марина.",
    )

    score = score_generation(record, utterance)

    assert score.leaked_span_ids == ("n1",)
    assert score.leak_renderings == ("text",)
    assert score.mapping_checked == 0


def test_a_phone_read_as_words_leaks_as_words():
    spans = utterance_by_id("id_phone_words").spans
    sanitized = (
        "Запиши мой телефон: восемь девятьсот пятнадцать двести тридцать "
        "четыре пятьдесят шесть семьдесят восемь."
    )

    assert leaked_spans(spans, sanitized) == [(spans[0], "words")]


def test_a_phone_rewritten_as_digits_leaks_as_digits():
    spans = utterance_by_id("id_phone_words").spans

    assert leaked_spans(spans, "Телефон +7 915 234-56-78") == [(spans[0], "digits")]


def test_a_placeholder_does_not_leak_a_numeric_span():
    spans = utterance_by_id("id_phone_words").spans

    assert leaked_spans(spans, "Запиши мой телефон: <PHONE_1>.") == []


def test_alt_digit_key_catches_the_year_written_as_digits():
    spans = utterance_by_id("id_birth_date").spans

    assert leaked_spans(spans, "Я родился 23 марта 1985 года.") == [
        (spans[0], "digits")
    ]


def test_mapping_matches_digits_and_names_but_not_unrelated_values():
    phone = Span("p", "x", SpanType.PHONE, digit_keys=("9152345678",))
    name = Span("n", "Марине", SpanType.PERSON)

    assert mapping_matches(phone, {"<PHONE_1>": "8 (915) 234-56-78"})
    assert mapping_matches(name, {"<PERSON_1>": "Марина"})
    assert not mapping_matches(name, {"<PERSON_1>": "Олег"})


def test_a_wrong_mapping_for_a_replaced_span_is_an_error():
    utterance = utterance_by_id("id_short_call")
    record = _combined(
        "id_short_call",
        raw_transcript="Позвони Марине Крыловой.",
        sanitized_text="Позвони <PERSON_1>.",
        mapping={"<PERSON_1>": "Олег"},
    )

    score = score_generation(record, utterance)

    assert (score.mapping_checked, score.mapping_errors) == (1, 1)


def test_meaning_preservation_counts_kept_non_sensitive_content_words():
    utterance = utterance_by_id("id_doctor_clinic")

    kept = meaning_preservation(
        utterance, "Запишите меня к доктору <P> в <O> на пятницу."
    )
    dropped = meaning_preservation(utterance, "<TEXT>")

    assert kept == 1.0
    assert dropped == 0.0


def test_preservation_is_not_defined_without_content_words():
    utterance = utterance_by_id("id_short_call")

    assert meaning_preservation(utterance, "Позвони <PERSON_1>.") == 1.0
    assert meaning_preservation(utterance_by_id("n_short_tokyo"), "x") is not None


def test_two_step_takes_the_transcript_from_step_one():
    utterance = utterance_by_id("id_short_call")
    record = _two_step(
        "id_short_call",
        "Позвони Марине Крыловой.",
        _json(sanitized_text="Позвони <PERSON_1>.", mapping={"<PERSON_1>": "Марина"}),
    )

    score = score_generation(record, utterance)

    assert score.raw_transcript == "Позвони Марине Крыловой."
    assert score.valid
    assert score.total_seconds == 1.5


def test_a_refusal_sentence_as_transcript_is_an_audio_failure():
    assert looks_like_audio_failure(
        "Пожалуйста, предоставьте аудиофайл или ссылку на него.", "Позвони Марине."
    )
    assert looks_like_audio_failure("Please provide the audio file.", "Позвони.")


def test_a_bluff_with_high_wer_is_an_audio_failure():
    assert looks_like_audio_failure(
        "Вы можете обращаться ко мне как к Джарвису", "Как ты меня слышишь"
    )


def test_a_faithful_transcript_is_not_an_audio_failure():
    assert not looks_like_audio_failure(
        "позвони марине крыловой", "Позвони Марине Крыловой."
    )


def test_invalid_output_is_counted_by_failure_class_and_not_scored_for_leaks():
    utterance = utterance_by_id("id_short_call")
    record = GenerationRecord(
        "id_short_call",
        Arm.C_USER,
        1,
        (_call(CallStage.COMBINED, "```json\n{}\n```"),),
    )

    score = score_generation(record, utterance)

    assert (score.valid, score.failure) == (False, FailureClass.EXTRA_PROSE)
    assert score.spans_total == 0
    assert score.audio_failure is None


def test_a_truncated_call_is_invalid():
    utterance = utterance_by_id("id_short_call")
    record = GenerationRecord(
        "id_short_call",
        Arm.C_USER,
        1,
        (_call(CallStage.COMBINED, _json(), done_reason="length"),),
    )

    assert score_generation(record, utterance).failure is FailureClass.TRUNCATED


def test_a_recorded_error_makes_the_generation_invalid():
    utterance = utterance_by_id("id_short_call")
    record = GenerationRecord("id_short_call", Arm.C_USER, 1, (), error="boom")

    score = score_generation(record, utterance)

    assert (score.errored, score.valid) == (True, False)


def test_a_wrong_refusal_of_a_neutral_request_is_a_false_refusal():
    record = _combined(
        "n_short_tokyo", verdict="refuse", reason="no speech", raw_transcript=""
    )

    score = score_generation(record, utterance_by_id("n_short_tokyo"))

    assert score.false_refusal
    assert score.audio_failure


def test_sending_a_topic_request_is_a_missed_refusal():
    record = _combined(
        "t_diabetes", raw_transcript="x", sanitized_text="Какая диета при диабете?"
    )

    assert score_generation(record, utterance_by_id("t_diabetes")).missed_refusal


def test_refusing_a_topic_request_is_correct_and_leaks_nothing():
    record = _combined("t_diabetes", verdict="refuse", reason="medical")

    score = score_generation(record, utterance_by_id("t_diabetes"))

    assert not score.missed_refusal
    assert score.spans_total == 0


def test_a_send_with_text_on_a_control_is_a_fabrication():
    silence = next(c for c in CONTROLS if c.control_id == "ctl_silence")
    fabricated = _combined("ctl_silence", sanitized_text="Привет, как дела")
    honest = _combined("ctl_silence", verdict="refuse", reason="no speech")

    assert score_generation(fabricated, silence).fabrication
    assert not score_generation(honest, silence).fabrication


def test_aggregate_computes_rates_and_latency_over_warm_generations():
    utterance = utterance_by_id("id_short_call")
    clean = _combined(
        "id_short_call",
        seed=1,
        raw_transcript="Позвони Марине Крыловой.",
        sanitized_text="Позвони <PERSON_1>.",
        mapping={"<PERSON_1>": "Марина"},
    )
    leaky = _combined(
        "id_short_call",
        seed=2,
        raw_transcript="Позвони Марине Крыловой.",
        sanitized_text="Позвони Марине.",
    )
    scores = [score_generation(r, utterance) for r in (clean, leaky)]

    metrics = aggregate(Arm.C_USER, scores)

    assert metrics.generations == 2
    assert metrics.validity == 1.0
    assert (metrics.spans_total, metrics.spans_leaked) == (2, 1)
    assert metrics.leak_rate == 0.5
    assert metrics.sent_generations_with_leak == 1
    assert metrics.median_seconds == 1.0


def test_aggregate_excludes_cold_generations_from_latency():
    utterance = utterance_by_id("n_short_tokyo")
    cold = GenerationRecord(
        "n_short_tokyo",
        Arm.C_USER,
        1,
        (
            _call(
                CallStage.COMBINED,
                _json(raw_transcript="Который час в Токио?"),
                total=9.0,
                load=5.0,
            ),
        ),
    )
    warm = _combined("n_short_tokyo", seed=2, raw_transcript="Который час в Токио?")

    metrics = aggregate(
        Arm.C_USER, [score_generation(r, utterance) for r in (cold, warm)]
    )

    assert (metrics.cold_generations, metrics.warm_generations) == (1, 1)
    assert metrics.median_seconds == 1.0


def test_aggregate_keeps_controls_out_of_the_utterance_denominators():
    silence = next(c for c in CONTROLS if c.control_id == "ctl_silence")
    scores = score_records(
        [_combined("ctl_silence", sanitized_text="выдумка")], CONTROLS
    )
    del silence

    metrics = aggregate(Arm.C_USER, scores)

    assert (metrics.generations, metrics.control_generations) == (0, 1)
    assert metrics.fabrications == 1


def test_percentile_uses_nearest_rank():
    assert percentile_nearest_rank([1.0, 2.0, 3.0, 4.0, 5.0], 0.9) == 5.0
    assert percentile_nearest_rank([], 0.9) is None


def test_leak_breakdown_groups_by_type_and_class():
    utterance = utterance_by_id("id_short_call")
    leaky = score_generation(
        _combined("id_short_call", raw_transcript="x", sanitized_text="Марине"),
        utterance,
    )

    assert leak_breakdown(Arm.C_USER, [leaky]) == {"person/direct": (1, 1)}


def test_score_records_resolves_utterances_and_controls():
    scores = score_records(
        [
            _combined("id_short_call", raw_transcript="Позвони Марине Крыловой."),
            _combined("ctl_noise", verdict="refuse"),
        ],
        CONTROLS,
    )

    assert [s.is_control for s in scores] == [False, True]
    assert Verdict.SEND in {s.verdict for s in scores} | {Verdict.SEND}
