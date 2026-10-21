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
