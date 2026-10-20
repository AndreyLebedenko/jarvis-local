import inspect

import pytest

from jarvis.personal_proxy.payload import (
    DEFAULT_SYSTEM_PROMPT,
    OutboundMessage,
    OutboundPayload,
    build_outbound_payload,
)

ALLOWED_BUILDER_INPUTS = {"system_prompt", "sanitized_request"}


def test_the_builder_accepts_exactly_the_allowed_input_sources():
    parameters = set(inspect.signature(build_outbound_payload).parameters)

    assert parameters == ALLOWED_BUILDER_INPUTS


def test_the_payload_is_a_system_message_then_a_user_message():
    payload = build_outbound_payload("SYSTEM TEXT", "USER TEXT")

    assert payload.to_chat_messages() == [
        {"role": "system", "content": "SYSTEM TEXT"},
        {"role": "user", "content": "USER TEXT"},
    ]


def test_the_payload_holds_no_text_but_the_two_inputs():
    payload = build_outbound_payload("SYSTEM TEXT", "USER TEXT")

    contents = [message.content for message in payload.messages]
    assert contents == ["SYSTEM TEXT", "USER TEXT"]
    assert set(payload.to_chat_messages()[0]) == {"role", "content"}


def test_the_default_system_prompt_asks_for_the_request_language_and_placeholders():
    assert "language of the request" in DEFAULT_SYSTEM_PROMPT
    assert "<PERSON_1>" in DEFAULT_SYSTEM_PROMPT


def test_a_non_text_input_is_refused_without_echoing_it():
    secret = 4242424242424242

    with pytest.raises(TypeError) as error:
        build_outbound_payload("system", secret)  # type: ignore[arg-type]

    assert str(secret) not in str(error.value)


def test_a_payload_cannot_be_constructed_outside_the_builder():
    with pytest.raises(TypeError):
        OutboundPayload(messages=())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        OutboundMessage("user", "text")  # type: ignore[call-arg]


def test_the_text_forms_of_a_payload_do_not_show_its_content():
    payload = build_outbound_payload("SYSTEM CANARY", "USER CANARY")

    shown = repr(payload) + str(payload) + repr(payload.messages)

    assert "CANARY" not in shown
