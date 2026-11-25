import io
import re

import soundfile as sf

from jarvis.audio.tts_silero import normalize_numbers, transliterate_latin
from manual.manual_check_silero_v5_question_intonation import (
    CASES,
    PAIR_SENTENCES,
    QUESTION,
    build_arg_parser,
    build_round_three_cases,
    build_round_two_cases,
    build_route,
    cases_for_round,
    mark_words,
    wav_duration_seconds,
)

MARKED_WORD = re.compile(r"\*([^*]+)\*")


def case_by_id(case_id):
    return next(case for case in CASES if case.id == case_id)


def test_case_ids_are_unique():
    ids = [case.id for case in CASES]

    assert len(ids) == len(set(ids))


def test_each_article_word_is_the_centre_of_exactly_one_case():
    words = QUESTION.rstrip("?").split()
    centres = [
        MARKED_WORD.findall(case.text)
        for case in CASES
        if case.id.startswith("general_centre_")
    ]

    assert centres == [[word] for word in words]


def test_centre_cases_differ_from_the_baseline_only_by_asterisks():
    for case in CASES:
        if case.id.startswith("general_centre_"):
            assert case.text.replace("*", "") == QUESTION


def test_only_the_unpaired_case_has_an_odd_number_of_asterisks():
    odd = [case.id for case in CASES if case.text.count("*") % 2]

    assert odd == ["malformed_unpaired"]


def test_production_preprocessing_keeps_asterisks_for_the_model():
    for case in CASES:
        prepared = transliterate_latin(normalize_numbers(case.text))

        assert prepared == case.text


def test_route_uses_the_requested_model_and_speaker_without_accent_overrides():
    route = build_route("v5_6_ru", "xenia")

    assert (route.model, route.speaker, route.language) == ("v5_6_ru", "xenia", "ru")
    assert route.put_accent is None and route.put_yo is None


def test_arg_parser_defaults_match_the_documented_handoff():
    args = build_arg_parser().parse_args([])

    assert (args.model, args.speaker, args.round, args.out_dir) == (
        "v5_6_ru",
        ["xenia"],
        1,
        None,
    )


def test_arg_parser_accepts_several_speakers_for_round_two():
    args = build_arg_parser().parse_args(
        ["--round", "2", "--speaker", "xenia", "aidar"]
    )

    assert (args.round, args.speaker) == (2, ["xenia", "aidar"])


def test_mark_words_wraps_only_the_chosen_words_and_ends_with_a_question_mark():
    assert mark_words("Вы уже отправили нам договор", (0, 4)) == (
        "*Вы* уже отправили нам *договор*?"
    )


def test_mark_words_without_indexes_gives_the_plain_question():
    assert mark_words("Вы уже отправили нам договор", ()) == (
        "Вы уже отправили нам договор?"
    )


def test_round_two_has_six_cases_per_question_with_unique_ids_across_rounds():
    cases = build_round_two_cases()
    ids = [case.id for case in cases] + [case.id for case in CASES]

    assert len(cases) == 6 * len(PAIR_SENTENCES)
    assert len(ids) == len(set(ids))


def test_round_two_cases_differ_from_their_question_only_by_asterisks():
    plain = {question.sentence + "?" for question in PAIR_SENTENCES}

    for case in build_round_two_cases():
        assert case.text.replace("*", "") in plain


def test_round_two_pairs_with_last_word_mark_it_and_the_remaining_pair_does_not():
    for question in PAIR_SENTENCES:
        last_word = question.sentence.split()[question.last_word]
        by_id = {case.id: case for case in build_round_two_cases()}
        paired = [
            case
            for case_id, case in by_id.items()
            if case_id.startswith(f"r2_{question.id}_w") and case_id.endswith("_last")
        ]
        unpaired = [
            case
            for case_id, case in by_id.items()
            if case_id.startswith(f"r2_{question.id}_w")
            and not case_id.endswith("_last")
        ]

        assert len(paired) == len(question.content_words) - 1
        assert all(f"*{last_word}*" in case.text for case in paired)
        assert all(case.text.count("*") == 4 for case in paired + unpaired)
        assert all(f"*{last_word}*" not in case.text for case in unpaired)


def test_cases_for_round_selects_the_requested_catalogue():
    assert cases_for_round(1) is CASES
    assert cases_for_round(2) == build_round_two_cases()


def test_wav_duration_is_frames_over_sample_rate():
    buffer = io.BytesIO()
    sf.write(buffer, [0.0] * 24000, 48000, format="WAV")

    assert wav_duration_seconds(buffer.getvalue()) == 0.5


def test_round_three_is_round_two_as_statements():
    questions = build_round_two_cases()
    statements = build_round_three_cases()

    assert [case.text.removesuffix(".") for case in statements] == [
        case.text.removesuffix("?") for case in questions
    ]
    assert all(case.text.endswith(".") for case in statements)
    assert [case.id.replace("r3_", "r2_") for case in statements] == [
        case.id for case in questions
    ]


def test_round_three_cases_ask_about_the_audible_asterisk():
    assert all("asterisk" in case.listen_for for case in build_round_three_cases())


def test_cases_for_round_three_selects_the_statement_catalogue():
    assert cases_for_round(3) == build_round_three_cases()


def test_arg_parser_accepts_round_three():
    assert build_arg_parser().parse_args(["--round", "3"]).round == 3
