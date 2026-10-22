from jarvis.personal_proxy.restoration_substitution import substitute

MAPPING = {"<PERSON_1>": "Анна Лебедева", "<PHONE_1>": "8 915 234 56 78"}


def test_every_occurrence_gets_the_base_form_original():
    text = "<PERSON_1> просила <PERSON_1> позвонить по <PHONE_1>."

    assert substitute(text, MAPPING) == (
        "Анна Лебедева просила Анна Лебедева позвонить по 8 915 234 56 78."
    )


def test_a_placeholder_missing_from_the_mapping_stays_in_the_text():
    assert (
        substitute("<PERSON_2> и <PERSON_1>", MAPPING) == "<PERSON_2> и Анна Лебедева"
    )


def test_a_gate_style_placeholder_outside_the_mapping_stays_in_the_text():
    assert substitute("<PERSON_01> <FOO_1>", MAPPING) == "<PERSON_01> <FOO_1>"


def test_an_original_that_looks_like_a_placeholder_is_not_substituted_again():
    mapping = {"<PERSON_1>": "<PERSON_2>", "<PERSON_2>": "Игорь Мельников"}

    assert substitute("<PERSON_1>", mapping) == "<PERSON_2>"
