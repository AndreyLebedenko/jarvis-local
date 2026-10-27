import hashlib

import pytest

from jarvis.personal_proxy.sanitize import sanitize_prompts as production
from jarvis.personal_proxy.sanitize.sanitize_parsing import parse_sanitize_output
from jarvis.personal_proxy.sanitize.sanitize_requests import build_sanitize_request
from jarvis.personal_proxy.sanitize.sanitize_result import SanitizeFailure
from manual.personal_proxy import prompts as spike
from manual.personal_proxy.parse import parse_sanitize_output as spike_parse

TOPICS = "- the secret diagnosis of the user\n"
TRANSCRIPT = "Позвони Марине по номеру 8 912 345 67 89"


def test_the_frozen_texts_equal_the_spike_texts():
    assert production.TEXT_FORMAT == spike.TEXT_FORMAT
    assert production.TEXT_USER_PREFIX == spike.TEXT_USER_PREFIX
    assert production.TEXT_SCHEMA == spike.TEXT_SCHEMA
    assert ", ".join(production.PLACEHOLDER_TYPES) == spike.PLACEHOLDER_TYPES


def test_the_user_message_equals_the_spike_user_message():
    request = build_sanitize_request(TRANSCRIPT, TOPICS, 0.5)

    spike_user = spike.sanitize_text_messages(TRANSCRIPT, TOPICS)[1]
    assert {"role": "user", "content": request.prompt} == spike_user


def test_the_worked_example_is_a_reply_the_production_parser_accepts():
    outcome = parse_sanitize_output(production.EXAMPLE_REPLY)

    assert outcome.sanitized_text == "Напиши <PERSON_1> про договор"
    assert outcome.mapping == {"<PERSON_1>": "Тамара Игнатьева"}


@pytest.mark.parametrize("topics", ["", "- x"])
def test_the_prompt_holds_the_worked_example_and_the_numbering_rule(topics):
    prompt = production.sanitize_system_prompt(topics)

    assert production.EXAMPLE_REPLY in prompt
    assert "<PERSON_1>, never <PERSON>" in prompt


def test_the_parser_names_the_same_failures_as_the_spike_parser():
    outputs = ["", "prose", 'x {"a": 1} y', "[]", '{"verdict": "send"}']
    outputs.append(
        '{"verdict": "maybe", "reason": "", "sanitized_text": "", "mapping": {}}'
    )

    for text in outputs:
        expected = spike_parse(text, None, require_raw_transcript=False)
        got = parse_sanitize_output(text)
        assert isinstance(got, SanitizeFailure)
        assert got.failure.value == expected.failure.value


PROMPT_WITH_TOPICS_SHA256 = (
    "1bf7f77eec262e6fdbfbd6bbcead1ca2c3436464df564ac0b9eb44248978fdf3"
)
TOPIC_RULE_START = "6. If the whole request is mainly about one of the sensitive topics"
NO_SPEECH_RULE_TEXT = (
    'If there is no intelligible speech, set verdict to "refuse", reason to '
    '"no speech", and leave the texts empty.'
)


def _numbered_rules(prompt):
    return [
        line
        for line in prompt.splitlines()
        if line[:2] in {f"{n}." for n in range(1, 10)}
    ]


def test_the_prompt_with_topics_is_byte_identical_to_the_frozen_text():
    prompt = production.sanitize_system_prompt("- the secret diagnosis of the user")

    assert hashlib.sha256(prompt.encode()).hexdigest() == PROMPT_WITH_TOPICS_SHA256


@pytest.mark.parametrize("topics", ["", "   ", "\n\t \n", "​"])
def test_the_prompt_without_visible_topics_has_no_topics_rule_or_section(topics):
    prompt = production.sanitize_system_prompt(topics)

    assert "sensitive topic" not in prompt.casefold()
    assert "Sensitive topics:" not in prompt
    assert TOPIC_RULE_START not in prompt


def test_the_prompt_without_topics_keeps_the_no_speech_rule_numbered_six():
    prompt = production.sanitize_system_prompt("")

    assert f"6. {NO_SPEECH_RULE_TEXT}" in prompt
    assert "7." not in prompt
    assert len(_numbered_rules(prompt)) == 6


def test_the_prompt_without_topics_keeps_every_other_rule_and_the_format():
    with_topics = production.sanitize_system_prompt("- x")
    without = production.sanitize_system_prompt("")

    for line in _numbered_rules(with_topics)[:5]:
        assert line in without
    assert production.TEXT_FORMAT in without
    assert 'Otherwise verdict is "send" and reason is empty.' in without


def test_the_prompt_with_topics_still_numbers_the_no_speech_rule_seven():
    prompt = production.sanitize_system_prompt("- x")

    assert f"7. {NO_SPEECH_RULE_TEXT}" in prompt
    assert "- x" in prompt


def test_the_request_builder_drops_the_topics_for_an_empty_list():
    request = build_sanitize_request(TRANSCRIPT, "  \n", 0.5)

    assert request.system == production.sanitize_system_prompt("")
    assert "Sensitive topics" not in request.system


PROMPT_WITHOUT_TOPICS_OR_NAMES_SHA256 = (
    "4f3e002aaa5350931de54adfe7631296d2346ce49562981d28ff99e2b5fded56"
)
NAMES = "Альберт Эйнштейн\nNikola Tesla"
NAMES_RULE_START = 'Do not replace the names listed under "Public names"'


def test_the_prompt_without_topics_or_names_is_byte_identical_to_the_frozen_text():
    prompt = production.sanitize_system_prompt("")

    assert (
        hashlib.sha256(prompt.encode()).hexdigest()
        == PROMPT_WITHOUT_TOPICS_OR_NAMES_SHA256
    )


@pytest.mark.parametrize("names", ["", "   ", "\n\t \n", "​"])
def test_no_visible_names_leave_both_prompts_unchanged(names):
    assert production.sanitize_system_prompt(
        "", names
    ) == production.sanitize_system_prompt("")
    assert production.sanitize_system_prompt(
        "- x", names
    ) == production.sanitize_system_prompt("- x")


def test_names_without_topics_add_rule_six_and_shift_the_no_speech_rule_to_seven():
    prompt = production.sanitize_system_prompt("", NAMES)

    rules = _numbered_rules(prompt)
    assert len(rules) == 7
    assert rules[5].startswith(f"6. {NAMES_RULE_START}")
    assert f"7. {NO_SPEECH_RULE_TEXT}" in prompt
    assert prompt.index(NAMES_RULE_START) < prompt.index(NO_SPEECH_RULE_TEXT)


def test_names_with_topics_add_rule_seven_and_shift_the_no_speech_rule_to_eight():
    prompt = production.sanitize_system_prompt("- x", NAMES)

    rules = _numbered_rules(prompt)
    assert len(rules) == 8
    assert rules[5].startswith(TOPIC_RULE_START)
    assert rules[6].startswith(f"7. {NAMES_RULE_START}")
    assert f"8. {NO_SPEECH_RULE_TEXT}" in prompt
    assert "Sensitive topics:\n- x\n" in prompt


def test_the_names_section_lists_the_names_one_per_line():
    prompt = production.sanitize_system_prompt("", NAMES)

    assert f"\nPublic names:\n{NAMES}\n" in prompt
    assert production.TEXT_FORMAT in prompt


def test_the_names_rule_says_to_keep_names_as_said_in_any_case_form():
    prompt = production.sanitize_system_prompt("", NAMES)

    assert "exactly as said" in prompt
    assert "any case form" in prompt


def test_the_names_text_does_not_borrow_the_sensitive_topic_wording():
    prompt = production.sanitize_system_prompt("", NAMES)

    assert "sensitive topic" not in prompt.casefold()
    assert "Sensitive topics:" not in prompt
    assert TOPIC_RULE_START not in prompt


def test_the_request_builder_puts_the_names_into_the_system_prompt_only():
    request = build_sanitize_request(TRANSCRIPT, "", 0.5, NAMES)

    assert request.system == production.sanitize_system_prompt("", NAMES)
    assert "Эйнштейн" not in request.prompt
