import hashlib

import pytest

from jarvis.personal_proxy import sanitize_prompts as production
from jarvis.personal_proxy.sanitize_parsing import parse_sanitize_output
from jarvis.personal_proxy.sanitize_requests import build_sanitize_request
from jarvis.personal_proxy.sanitize_result import SanitizeFailure
from manual.personal_proxy import prompts as spike
from manual.personal_proxy.parse import parse_sanitize_output as spike_parse

TOPICS = "- the secret diagnosis of the user\n"
TRANSCRIPT = "Позвони Марине по номеру 8 912 345 67 89"


def test_the_frozen_texts_equal_the_spike_texts():
    assert production.RULES == spike.RULES
    assert production.TEXT_FORMAT == spike.TEXT_FORMAT
    assert production.TEXT_USER_PREFIX == spike.TEXT_USER_PREFIX
    assert production.TEXT_SCHEMA == spike.TEXT_SCHEMA
    assert ", ".join(production.PLACEHOLDER_TYPES) == spike.PLACEHOLDER_TYPES


def test_the_messages_equal_the_spike_messages():
    request = build_sanitize_request(TRANSCRIPT, TOPICS, 0.5)

    assert [
        {"role": "system", "content": request.system},
        {"role": "user", "content": request.prompt},
    ] == spike.sanitize_text_messages(TRANSCRIPT, TOPICS)


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
    "e33b9b6eb773356736fa95b030f36cfaa8bc5baaddda53f128649a2dff9cdc19"
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


def test_the_prompt_with_topics_is_byte_identical_to_the_measured_baseline():
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
