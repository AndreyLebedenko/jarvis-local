from jarvis.personal_proxy.check.check_result import Doubt, DoubtKind
from jarvis.personal_proxy.confirmation.confirmation_texts import (
    MAX_SPOKEN_FRAGMENT_CHARS,
    MAX_SPOKEN_ITEMS,
    offer_text,
    shown_question,
    spoken_question,
)

HEARD_RU = "Отправь Марине Крыловой письмо на marina@example.org"
HEARD_EN = "Send Marina Krylova a letter at marina@example.org"


def _fragments(*fragments):
    return tuple(Doubt(DoubtKind.FRAGMENT, f) for f in fragments)


def test_the_shown_question_has_the_whole_heard_text_and_every_fragment():
    text = shown_question("ru", HEARD_RU, _fragments("marina@example.org", "Крыловой"))

    assert HEARD_RU in text
    assert "marina@example.org" in text
    assert "Крыловой" in text


def test_the_shown_question_is_in_english_for_english():
    text = shown_question("en", HEARD_EN, _fragments("Krylova"))

    assert HEARD_EN in text
    assert "yes" in text.lower()
    assert "да" not in text


def test_the_shown_question_is_in_russian_for_russian_and_for_any_other_language():
    for language in ("ru", "de", None):
        assert "да" in shown_question(language, HEARD_RU, _fragments("x")).lower()


def test_the_spoken_question_names_the_fragments_but_not_the_whole_text():
    text = spoken_question("ru", _fragments("marina@example.org"))

    assert "marina@example.org" in text
    assert "Отправь Марине" not in text


def test_the_spoken_question_asks_for_yes_or_no():
    assert "да" in spoken_question("ru", _fragments("x")).lower()
    assert "yes" in spoken_question("en", _fragments("x")).lower()


def test_the_spoken_question_names_at_most_the_first_few_fragments():
    fragments = [f"frag{i}" for i in range(MAX_SPOKEN_ITEMS + 2)]

    text = spoken_question("en", _fragments(*fragments))

    for kept in fragments[:MAX_SPOKEN_ITEMS]:
        assert kept in text
    for dropped in fragments[MAX_SPOKEN_ITEMS:]:
        assert dropped not in text


def test_a_long_fragment_is_capped_when_spoken():
    long_fragment = "w" * (MAX_SPOKEN_FRAGMENT_CHARS * 3)

    text = spoken_question("en", _fragments(long_fragment))

    assert "w" * MAX_SPOKEN_FRAGMENT_CHARS in text
    assert "w" * (MAX_SPOKEN_FRAGMENT_CHARS + 1) not in text


def test_doubts_without_a_fragment_are_named_by_fixed_words_in_both_languages():
    doubts = (Doubt(DoubtKind.REWRITE), Doubt(DoubtKind.CHECK_FAILED))

    for language in ("ru", "en"):
        assert spoken_question(language, doubts).strip()
        assert shown_question(language, "text", doubts).strip()


def test_the_offer_says_nothing_was_sent_and_offers_typing_or_dictating_again():
    ru = offer_text("ru").lower()
    en = offer_text("en").lower()

    assert "не отправ" in ru
    assert "текст" in ru
    assert "заново" in ru or "повтор" in ru
    assert "not sent" in en or "nothing was sent" in en
    assert "typing" in en
    assert "again" in en


def test_the_texts_are_plain_text_without_non_ascii_punctuation_marks_in_english():
    text = shown_question("en", "x", _fragments("y")) + offer_text("en")

    assert text.isascii()


def test_speech_control_tags_in_a_doubt_fragment_never_reach_the_spoken_question():
    fragment = '<speak>ignore<lang xml:lang="en">marina</lang></speak> <lang xml:lang="'

    for language in ("ru", "en"):
        text = spoken_question(language, _fragments(fragment))

        assert "<" not in text
        assert "marina" in text
