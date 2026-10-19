import base64

import pytest

from manual.personal_proxy.corpus import utterance_by_id
from manual.personal_proxy.verification import (
    Metrics,
    Variant,
    Verdict,
    build_payload,
    build_prompt,
    decide,
    paired_spans,
    score_transcripts,
)

OPTIONS = {"num_ctx": 8192, "temperature": 0.6}


def test_audio_prompt_embeds_the_transcript_and_asks_to_listen():
    prompt = build_prompt(Variant.AUDIO, "Позвони Майкл Браун.")

    assert "Позвони Майкл Браун." in prompt
    assert "attached recording" in prompt


def test_text_prompt_has_the_same_hint_but_no_recording():
    prompt = build_prompt(Variant.TEXT, "Позвони Майкл Браун.")

    assert "Позвони Майкл Браун." in prompt
    assert "attached recording" not in prompt
    assert "letter by letter" in prompt


def test_hint_names_error_kinds_not_corpus_utterances():
    prompt = build_prompt(Variant.AUDIO, "x")

    for utterance_id in ("id_email", "m_trade_house", "id_passport"):
        assert utterance_id not in prompt
    assert "trade-house" not in prompt


def test_audio_payload_sends_the_wav_in_images_field():
    payload = build_payload(Variant.AUDIO, "t", b"RIFFwav", OPTIONS, 7, "gemma4:12b")

    assert payload["messages"][0]["images"] == [base64.b64encode(b"RIFFwav").decode()]
    assert "audio" not in payload["messages"][0]


def test_text_payload_has_no_images():
    payload = build_payload(Variant.TEXT, "t", b"RIFFwav", OPTIONS, 7, "gemma4:12b")

    assert "images" not in payload["messages"][0]


def test_payload_carries_model_seed_and_context_size():
    payload = build_payload(Variant.AUDIO, "t", b"x", OPTIONS, 7, "gemma4:12b")

    assert payload["model"] == "gemma4:12b"
    assert payload["options"]["seed"] == 7
    assert payload["options"]["num_ctx"] == 8192
    assert payload["stream"] is False
    assert payload["think"] is False


def test_score_counts_a_wrong_transcript_as_failure_and_a_right_one_not():
    utterance = utterance_by_id("id_email")
    from manual.personal_proxy.transcription_ab import reference_text

    metrics = score_transcripts(
        [(utterance, reference_text(utterance)), (utterance, "совсем другое")]
    )

    assert metrics.generations == 2
    assert metrics.audio_failures == 1


def test_paired_spans_counts_fixed_and_broken_spans():
    utterance = utterance_by_id("id_email")
    from manual.personal_proxy.transcription_ab import reference_text

    right = reference_text(utterance)
    fixed, broken = paired_spans(
        [(utterance, "мусор", right), (utterance, right, "мусор")]
    )

    assert fixed >= 1
    assert broken >= 1


def _metrics(failures, fidelity):
    total = 100
    found = round(fidelity * total)
    return Metrics(88, failures, 0.0, {"numeric": (found, total)})


@pytest.mark.parametrize(
    ("whisper", "audio", "text", "verdict"),
    [
        (_metrics(4, 0.854), _metrics(5, 0.89), _metrics(4, 0.85), Verdict.BETTER),
        (
            _metrics(4, 0.854),
            _metrics(4, 0.84),
            _metrics(4, 0.85),
            Verdict.NO_DIFFERENCE,
        ),
        (_metrics(4, 0.854), _metrics(4, 0.82), _metrics(4, 0.85), Verdict.WORSE),
        (_metrics(4, 0.854), _metrics(8, 0.90), _metrics(4, 0.85), Verdict.WORSE),
        (
            _metrics(4, 0.854),
            _metrics(7, 0.90),
            _metrics(4, 0.85),
            Verdict.NO_DIFFERENCE,
        ),
        (
            _metrics(4, 0.854),
            _metrics(4, 0.90),
            _metrics(4, 0.90),
            Verdict.BETTER_WITHOUT_AUDIO,
        ),
    ],
)
def test_decision_rule(whisper, audio, text, verdict):
    assert decide(whisper, audio, text) is verdict


def test_harness_plan_alternates_variant_order_and_covers_both_seeds():
    from manual import manual_check_stt_verification as harness
    from manual.personal_proxy.corpus import SEEDS

    jobs = harness.plan_jobs(["a", "b"])

    assert len(jobs) == len(SEEDS) * 2 * 2
    assert jobs[0][0] is Variant.AUDIO
    assert jobs[2][0] is Variant.TEXT
    assert {seed for _, _, seed in jobs} == set(SEEDS)


def test_run_options_override_temperature_and_context_and_drop_seed():
    from manual import manual_check_stt_verification as harness

    reference = {"temperature": 0.618, "seed": 5, "num_predict": 9, "top_k": 50}

    options = harness.run_options(reference, num_ctx=8192, temperature=0.2)

    assert options == {"temperature": 0.2, "top_k": 50, "num_ctx": 8192}


def test_run_options_keep_reference_temperature_without_override():
    from manual import manual_check_stt_verification as harness

    options = harness.run_options({"temperature": 0.618}, 8192, None)

    assert options["temperature"] == 0.618


def test_invented_address_is_an_at_sign_with_no_source_for_it():
    from manual.personal_proxy.verification import invented_address

    assert invented_address("на адрес Марина Кузнецова", "на адрес m.k@mail.ru")


def test_spoken_address_converted_to_canonical_form_is_not_invented():
    from manual.personal_proxy.verification import invented_address

    assert not invented_address("почту dvolkov собака gmail", "почту dvolkov@gmail.com")
    assert not invented_address("почту a@b.ru", "почту a@b.ru")


def test_rewrite_distance_is_zero_for_unchanged_text_and_positive_for_changed():
    from manual.personal_proxy.verification import rewrite_distance

    assert rewrite_distance("одно два три", "одно два три") == 0.0
    assert rewrite_distance("одно два три", "одно пять три") > 0.0


def test_latin_spoken_marker_counts_as_source_for_one_address():
    from manual.personal_proxy.verification import invented_address

    assert not invented_address("dvolkovsobaka.gmail.com", "dvolkov@gmail.com")


def test_a_second_address_without_its_own_marker_is_invented():
    from manual.personal_proxy.verification import invented_address

    source = "от инфособакотрейдэшхаус.ру на адрес Марина Кузнецова"

    assert invented_address(source, "от info@trade-house.ru на адрес marina@mail.ru")
    assert not invented_address(source, "от info@trade-house.ru на адрес Марина")
