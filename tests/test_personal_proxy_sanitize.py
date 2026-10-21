import json

import pytest

from jarvis.core.config import GenerationOptions, PersonalProxySettings
from jarvis.personal_proxy.check_result import CheckedTranscript, CheckSource
from jarvis.personal_proxy.sanitize import sanitize
from jarvis.personal_proxy.sanitize_parsing import parse_sanitize_output
from jarvis.personal_proxy.sanitize_prompts import TEXT_SCHEMA
from jarvis.personal_proxy.sanitize_result import (
    MAX_REASON_LENGTH,
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)

SETTINGS = PersonalProxySettings()
TRANSCRIPT = "Позвони Марине Ивановой по номеру 8 912 345 67 89"
TOPICS = "- the secret diagnosis of the user"
SANITIZED = "Позвони <PERSON_1> по номеру <PHONE_1>"
MAPPING = {"<PERSON_1>": "Марина Иванова", "<PHONE_1>": "8 912 345 67 89"}


def _reply(**changes):
    document = {
        "verdict": "send",
        "reason": "",
        "sanitized_text": SANITIZED,
        "mapping": MAPPING,
    } | changes
    return json.dumps(document, ensure_ascii=False)


def _checked(text=TRANSCRIPT):
    return CheckedTranscript(text, (), CheckSource.CHECKED, False)


class FakeBackend:
    def __init__(self, reply):
        self._reply = reply
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if isinstance(self._reply, BaseException):
            raise self._reply
        return self._reply


async def _sanitize(reply, transcript=TRANSCRIPT, topics=TOPICS):
    backend = FakeBackend(reply)
    result = await sanitize(_checked(transcript), topics, backend, SETTINGS)
    return result, backend


async def test_a_valid_send_is_returned_with_text_and_mapping():
    result, _ = await _sanitize(_reply())

    assert result == SanitizeResult(SanitizeVerdict.SEND, "", SANITIZED, MAPPING)


async def test_the_request_has_a_system_and_a_user_message_and_the_schema():
    _, backend = await _sanitize(_reply())

    request = backend.requests[0]
    assert TOPICS in request.system
    assert TRANSCRIPT in request.prompt
    assert TRANSCRIPT not in request.system
    assert request.response_format == TEXT_SCHEMA
    assert request.audio_base64 == ""


async def test_the_options_come_from_the_settings_without_a_seed():
    _, backend = await _sanitize(_reply())

    assert backend.requests[0].options == GenerationOptions(
        temperature=SETTINGS.check_temperature, num_predict=2048
    )


async def test_the_transcript_text_of_the_checked_transcript_is_sanitized():
    other = "Другой текст"
    _, backend = await _sanitize(_reply(), transcript=other)

    assert other in backend.requests[0].prompt


async def test_a_refusal_keeps_the_bounded_reason_and_drops_text_and_mapping():
    reply = _reply(
        verdict="refuse",
        reason="r" * (MAX_REASON_LENGTH + 50),
        sanitized_text="leaked text",
        mapping={"not even a placeholder": ""},
    )

    result, _ = await _sanitize(reply)

    assert result == SanitizeResult(
        SanitizeVerdict.REFUSE, "r" * MAX_REASON_LENGTH, "", {}
    )


async def test_an_empty_transcript_is_refused_as_no_speech_without_a_model_call():
    result, backend = await _sanitize(_reply(), transcript="  \n")

    assert result == SanitizeResult(SanitizeVerdict.REFUSE, "no speech", "", {})
    assert backend.requests == []


@pytest.mark.parametrize("error", [RuntimeError("x"), TimeoutError()])
async def test_a_backend_error_or_timeout_is_a_typed_failure(error):
    result, _ = await _sanitize(error)

    assert result == SanitizeFailure(SanitizeFailureClass.BACKEND_FAILED)


async def test_a_reply_that_is_not_text_is_a_backend_failure():
    result, _ = await _sanitize(None)

    assert result == SanitizeFailure(SanitizeFailureClass.BACKEND_FAILED)


async def test_the_topics_never_appear_in_a_result_repr():
    ok, _ = await _sanitize(_reply())
    refused, _ = await _sanitize(_reply(verdict="refuse", reason=TOPICS))
    failed, _ = await _sanitize("not json " + TOPICS)

    for result in (ok, refused, failed):
        shown = repr(result)
        assert TOPICS not in shown
        assert TRANSCRIPT not in shown
        assert "<PERSON_1>" not in shown
        assert "Марина" not in shown
        assert SANITIZED not in shown


def test_the_length_cap_is_a_truncation_failure():
    assert parse_sanitize_output(_reply(), "length") == SanitizeFailure(
        SanitizeFailureClass.TRUNCATED
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", SanitizeFailureClass.EMPTY),
        ("   \n", SanitizeFailureClass.EMPTY),
        ("Sorry, I cannot.", SanitizeFailureClass.NO_JSON),
        ("{not json}", SanitizeFailureClass.NO_JSON),
        ("Here you go: " + _reply(), SanitizeFailureClass.EXTRA_PROSE),
        (_reply() + " Done.", SanitizeFailureClass.EXTRA_PROSE),
        ("[1, 2]", SanitizeFailureClass.WRONG_TYPE),
        (
            json.dumps({"verdict": "send", "reason": "", "mapping": {}}),
            SanitizeFailureClass.MISSING_FIELD,
        ),
        (_reply(verdict=1), SanitizeFailureClass.WRONG_TYPE),
        (_reply(reason=None), SanitizeFailureClass.WRONG_TYPE),
        (_reply(sanitized_text=["a"]), SanitizeFailureClass.WRONG_TYPE),
        (_reply(mapping=["a"]), SanitizeFailureClass.WRONG_TYPE),
        (_reply(mapping={"<PERSON_1>": 5}), SanitizeFailureClass.WRONG_TYPE),
        (_reply(verdict="maybe"), SanitizeFailureClass.BAD_VERDICT),
        (_reply(verdict="SEND"), SanitizeFailureClass.BAD_VERDICT),
    ],
)
def test_each_parse_failure_class(text, expected):
    assert parse_sanitize_output(text) == SanitizeFailure(expected)


@pytest.mark.parametrize("text", ["", "  \n"])
def test_a_send_needs_a_non_empty_sanitized_text(text):
    assert parse_sanitize_output(_reply(sanitized_text=text)) == SanitizeFailure(
        SanitizeFailureClass.EMPTY_SANITIZED_TEXT
    )


@pytest.mark.parametrize(
    "key",
    [
        "PERSON_1",
        "<PERSON>",
        "<PERSON_0>",
        "<PERSON_01>",
        "<NAME_1>",
        "<person_1>",
        "<PERSON_1> ",
        "x<PERSON_1>",
        "<PERSON_1>\n",
        "",
        "<PERSON_X>",
    ],
)
def test_a_mapping_key_must_be_a_listed_type_with_a_number(key):
    assert parse_sanitize_output(_reply(mapping={key: "value"})) == SanitizeFailure(
        SanitizeFailureClass.BAD_PLACEHOLDER
    )


@pytest.mark.parametrize(
    "key", ["<PERSON_1>", "<GOV_ID_2>", "<OTHER_10>", "<EMAIL_1>", "<SECRET_3>"]
)
def test_a_mapping_key_of_a_listed_type_is_accepted(key):
    result = parse_sanitize_output(_reply(mapping={key: "value"}))

    assert result.mapping == {key: "value"}


@pytest.mark.parametrize("value", ["", "   "])
def test_a_mapping_value_must_not_be_empty(value):
    assert parse_sanitize_output(
        _reply(mapping={"<PERSON_1>": value})
    ) == SanitizeFailure(SanitizeFailureClass.EMPTY_MAPPING_VALUE)


def test_a_send_without_any_mapping_is_valid():
    result = parse_sanitize_output(_reply(mapping={}, sanitized_text="Привет"))

    assert result == SanitizeResult(SanitizeVerdict.SEND, "", "Привет", {})


def test_a_send_drops_the_model_reason():
    result = parse_sanitize_output(_reply(reason="all fine"))

    assert result.reason == ""


def test_a_refusal_with_bad_mapping_keys_is_still_a_refusal():
    result = parse_sanitize_output(
        _reply(verdict="refuse", reason="topic", mapping={"x": ""})
    )

    assert result == SanitizeResult(SanitizeVerdict.REFUSE, "topic", "", {})


def test_a_refusal_still_needs_all_fields_and_types():
    assert parse_sanitize_output(
        json.dumps({"verdict": "refuse", "reason": "t"})
    ) == SanitizeFailure(SanitizeFailureClass.MISSING_FIELD)


ZERO_WIDTH = "​‍⁠﻿ \n"


@pytest.mark.parametrize("shape", ["array", "object", "digits"])
def test_a_reply_that_breaks_the_json_decoder_is_a_typed_failure(shape):
    text = {
        "array": "[" * 100000,
        "object": "{" + '"a":' * 100000,
        "digits": "1" * 6000,
    }[shape]

    assert parse_sanitize_output(text) == SanitizeFailure(SanitizeFailureClass.NO_JSON)


def test_extra_prose_around_an_undecodable_object_is_a_typed_failure():
    text = "here: {" + "[" * 100000 + "}"

    assert parse_sanitize_output(text) == SanitizeFailure(SanitizeFailureClass.NO_JSON)


async def test_a_zero_width_only_transcript_is_no_speech_without_a_model_call():
    result, backend = await _sanitize(_reply(), transcript=ZERO_WIDTH)

    assert result == SanitizeResult(SanitizeVerdict.REFUSE, "no speech", "", {})
    assert backend.requests == []


def test_a_send_with_zero_width_only_text_is_refused_as_empty():
    assert parse_sanitize_output(_reply(sanitized_text=ZERO_WIDTH)) == SanitizeFailure(
        SanitizeFailureClass.EMPTY_SANITIZED_TEXT
    )


def test_a_byte_order_mark_before_the_json_is_ignored():
    assert parse_sanitize_output("﻿" + _reply()).sanitized_text == SANITIZED


def test_a_duplicate_key_is_a_typed_failure():
    text = _reply().replace('"reason": ""', '"reason": "", "verdict": "refuse"')

    assert parse_sanitize_output(text) == SanitizeFailure(
        SanitizeFailureClass.WRONG_TYPE
    )


def test_unknown_extra_fields_are_ignored():
    result = parse_sanitize_output(_reply(note="x", raw_transcript="y"))

    assert result == SanitizeResult(SanitizeVerdict.SEND, "", SANITIZED, MAPPING)


def test_the_mapping_of_a_result_cannot_be_changed():
    result = parse_sanitize_output(_reply())

    with pytest.raises(TypeError):
        result.mapping["<PERSON_2>"] = "x"


def test_str_of_a_result_and_a_failure_hides_the_content():
    sent = parse_sanitize_output(_reply())
    refused = parse_sanitize_output(_reply(verdict="refuse", reason="diagnosis"))
    failed = parse_sanitize_output("diagnosis not json")

    for item in (sent, refused, failed):
        shown = f"{item!s} {item!r}"
        assert "diagnosis" not in shown
        assert "Позвони" not in shown
        assert "Марина" not in shown
