import base64

import pytest

from manual.personal_proxy.confidence import (
    JUDGE_SCHEMA,
    JudgeResult,
    build_judge_payload,
    build_sample_payload,
    discriminates,
    invalid_items,
    is_bad,
    mean_pairwise_difference,
    min_sensitive_probability,
    operating_points,
    parse_judge,
    projection,
    symmetric_difference,
    weak_word_marks,
)
from manual.personal_proxy.corpus import utterance_by_id
from manual.personal_proxy.transcription_ab import reference_text

OPTIONS = {"num_ctx": 8192, "temperature": 0.618}


def test_marks_follow_only_words_below_the_threshold():
    words = [(" Позвони", 0.9), (" Майкл", 0.3), (" Браун.", 0.5)]

    assert weak_word_marks(words, 0.5) == "Позвони Майкл[?] Браун."


def test_projection_joins_digit_groups_and_drops_short_numbers():
    found = projection("Телефон 8 912 345-67-89, дом 5, год 1985.")

    assert "digits:89123456789" in found
    assert "digits:1985" in found
    assert not any(item == "digits:5" for item in found)


def test_projection_counts_one_address_marker_for_spoken_and_converted_forms():
    spoken = projection("почту dvolkovsobaka.gmail.com")
    converted = projection("почту dvolkov.sobaka@gmail.com")

    assert "addr:1" in spoken
    assert "addr:1" in converted


def test_projection_has_latin_words_and_name_stems_but_not_sentence_initial_ones():
    found = projection("Привет, Игорь из Northwind. Позвони Анне.")

    assert "latin:northwind" in found
    assert "name:игор" in found
    assert "name:анне" in found
    assert not any(item == "name:прив" for item in found)
    assert not any(item == "name:позв" for item in found)


def test_literal_addresses_appear_only_when_asked():
    text = "пиши на ivan.petrov@primer.com."

    assert "email:ivan.petrov@primer.com" in projection(text, literal_emails=True)
    assert not any(i.startswith("email:") for i in projection(text))


def test_symmetric_difference_counts_items_in_only_one_side():
    assert symmetric_difference(frozenset("ab"), frozenset("bc")) == 2


def test_mean_pairwise_difference_is_zero_for_identical_samples():
    same = frozenset({"a"})

    assert mean_pairwise_difference([same, same, same]) == 0.0
    assert mean_pairwise_difference([same, frozenset()]) == 1.0


def test_min_sensitive_probability_looks_at_digits_latin_and_capitalized_words():
    words = [(" Позвони", 0.2), (" Майкл", 0.4), (" 5", 0.9), (" git", 0.3)]

    assert min_sensitive_probability(words) == pytest.approx(0.3)


def test_min_sensitive_probability_is_one_without_sensitive_words():
    assert min_sensitive_probability([(" привет", 0.1), (" мир", 0.2)]) == 1.0


def test_invalid_items_flags_a_broken_address_and_a_wrong_length_number():
    assert invalid_items("пиши marina.kuznecova@.") == 1
    assert invalid_items("номер 12345678") == 1
    assert invalid_items("пиши a.b@mail.ru, номер 89123456789") == 0


def test_bad_when_a_labeled_span_is_lost():
    utterance = utterance_by_id("id_email")

    assert is_bad(utterance, "Пиши на почту.", "Пиши на почту.")


def test_good_when_the_spans_survive():
    utterance = utterance_by_id("id_email")
    text = reference_text(utterance)

    assert not is_bad(utterance, text, text)


def test_bad_when_the_output_translates_the_request():
    utterance = utterance_by_id("n_short_translate")
    whisper = reference_text(utterance)

    assert is_bad(utterance, whisper, 'Translate the word "apple" into English.')


def test_bad_when_an_address_is_invented():
    utterance = utterance_by_id("id_email")
    whisper = reference_text(utterance)

    assert is_bad(utterance, whisper, whisper + " x.y@mail.ru и a.b@c.ru")


def test_operating_points_give_recall_and_false_refusals_per_threshold():
    points = operating_points([0.9, 0.8, 0.2, 0.1], [True, True, False, False])

    best = max(points, key=lambda p: p.recall - p.false_refusals)
    assert (best.threshold, best.recall, best.false_refusals) == (0.8, 1.0, 0.0)


def test_signal_discriminates_when_it_beats_the_trivial_baseline():
    points = operating_points([0.9, 0.8, 0.2, 0.1], [True, True, False, False])

    assert discriminates(points, trivial_false_refusals=0.5)
    assert not discriminates(points, trivial_false_refusals=0.0)


def test_signal_does_not_discriminate_when_recall_needs_too_many_false_refusals():
    points = operating_points([0.9, 0.5, 0.8, 0.1], [True, True, False, False])

    assert not discriminates(points, trivial_false_refusals=1.0)


def test_parse_judge_reads_confidence_and_fragments():
    result = parse_judge('{"uncertain_fragments": ["8 912"], "confidence": 0.4}')

    assert result == JudgeResult(0.4, ["8 912"])


@pytest.mark.parametrize(
    "text",
    ["not json", '{"confidence": 2}', '{"uncertain_fragments": [], "confidence": "x"}'],
)
def test_parse_judge_rejects_malformed_answers(text):
    assert parse_judge(text) is None


def test_sample_payload_marks_words_and_sends_the_recording_in_images():
    payload = build_sample_payload("Майкл[?] Браун", b"wav", OPTIONS, 7, "gemma4:12b")
    message = payload["messages"][0]

    assert "Майкл[?] Браун" in message["content"]
    assert "[?]" in message["content"].split("Transcript:")[0]
    assert message["images"] == [base64.b64encode(b"wav").decode()]
    assert payload["options"]["seed"] == 7
    assert payload["options"]["temperature"] == 0.618


def test_judge_payload_is_deterministic_constrained_and_has_the_recording():
    payload = build_judge_payload("текст А", "текст Б", b"wav", OPTIONS, "gemma4:12b")
    content = payload["messages"][0]["content"]

    assert "текст А" in content
    assert "текст Б" in content
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["seed"] == 1
    assert payload["format"] == JUDGE_SCHEMA
    assert payload["messages"][0]["images"] == [base64.b64encode(b"wav").decode()]


def test_signal_must_also_flag_the_controls_when_they_are_given():
    points = operating_points([0.9, 0.8, 0.2, 0.1], [True, True, False, False])

    assert discriminates(points, 0.5, control_scores=[0.9, 0.85])
    assert not discriminates(points, 0.5, control_scores=[0.9, 0.1])


def test_revised_rule_does_not_count_a_latin_address_as_a_language_switch():
    from manual.personal_proxy.confidence import LabelRule

    utterance = utterance_by_id("id_email")
    whisper = "Пиши на почту иван.петров.собака.пример.ком"

    output = "Пиши на почту ivan.petrov@primer.com"

    assert is_bad(utterance, whisper, output)
    assert not is_bad(utterance, whisper, output, LabelRule.ADDRESSES_ARE_LATIN)


def test_revised_rule_still_catches_a_translation():
    from manual.personal_proxy.confidence import LabelRule

    utterance = utterance_by_id("n_short_translate")
    whisper = reference_text(utterance)

    assert is_bad(
        utterance,
        whisper,
        'Translate the word "apple" into English.',
        LabelRule.ADDRESSES_ARE_LATIN,
    )


def test_names_rule_does_not_count_a_latin_name_written_in_cyrillic_as_lost():
    from manual.personal_proxy.confidence import LabelRule

    utterance = utterance_by_id("m_short_call")
    whisper = "Позвони Майкл Браун."

    assert is_bad(utterance, whisper, whisper, LabelRule.ADDRESSES_ARE_LATIN)
    assert not is_bad(utterance, whisper, whisper, LabelRule.NAMES_IN_ANY_ALPHABET)


def test_names_rule_still_counts_a_lost_digit_span():
    from manual.personal_proxy.confidence import LabelRule

    utterance = utterance_by_id("id_two_people_phone")
    whisper = reference_text(utterance)

    assert is_bad(
        utterance,
        whisper,
        "Анна Лебедева просила перезвонить Игорю Мельникову по номеру 8 912 345 60 78.",
        LabelRule.NAMES_IN_ANY_ALPHABET,
    )
