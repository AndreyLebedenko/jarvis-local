from jarvis.personal_proxy.sanitize.placeholders import (
    PLACEHOLDER,
    has_unresolved,
    known_entries,
)

MAPPING = {
    "<PERSON_1>": "Анна Лебедева",
    "<ORG_1>": "Северный Ветер",
    "<PHONE_1>": "8 915 234 56 78",
}


def test_the_strict_pattern_matches_whole_sanitize_placeholders_only():
    assert PLACEHOLDER.fullmatch("<PHONE_3>")
    assert PLACEHOLDER.fullmatch("<GOV_ID_2>")
    assert not PLACEHOLDER.fullmatch("PHONE_3")
    assert not PLACEHOLDER.fullmatch("<COLOR_1>")
    assert not PLACEHOLDER.fullmatch("<PERSON_0>")


def test_known_entries_come_from_the_mapping_in_order_of_first_use():
    sentence = "<ORG_1> и <PERSON_1> и снова <ORG_1>"

    assert list(known_entries(sentence, MAPPING)) == ["<ORG_1>", "<PERSON_1>"]
    assert known_entries(sentence, MAPPING)["<ORG_1>"] == "Северный Ветер"


def test_a_key_that_is_only_part_of_a_longer_token_is_not_known():
    assert known_entries("<PERSON_10> здесь", MAPPING) == {}


def test_a_placeholder_outside_the_mapping_is_unresolved():
    assert has_unresolved("<PERSON_1> и <PERSON_2>", MAPPING)


def test_gate_style_placeholders_outside_the_strict_pattern_are_unresolved():
    assert has_unresolved("<PERSON_01> здесь", MAPPING)
    assert has_unresolved("<FOO_1> здесь", MAPPING)


def test_a_sentence_of_known_placeholders_only_is_resolved():
    assert not has_unresolved("<PERSON_1> и <ORG_1>", MAPPING)
    assert not has_unresolved("Обычный текст <без> меток", MAPPING)
