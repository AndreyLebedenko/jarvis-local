import pytest

from jarvis.personal_proxy.check_result import (
    CheckedTranscript,
    CheckSource,
    Doubt,
    DoubtKind,
)
from jarvis.personal_proxy.confirmation_blocks import (
    HeardBlock,
    HeardDecision,
    SentBlock,
    heard_block_of,
    sent_block_of,
)
from jarvis.personal_proxy.payload import build_outbound_payload

HEARD = "Отправь Марине Крыловой письмо на marina@example.org"
FRAGMENT = "marina@example.org"


def _checked(doubts=()):
    return CheckedTranscript(
        text=HEARD, doubts=tuple(doubts), source=CheckSource.CHECKED, would_ask=True
    )


def test_the_heard_block_carries_the_whole_heard_text_and_the_doubts():
    doubt = Doubt(DoubtKind.FRAGMENT, FRAGMENT)

    block = heard_block_of(_checked([doubt]), HeardDecision.ASK_CONFIRMATION)

    assert block == HeardBlock(HEARD, (doubt,), HeardDecision.ASK_CONFIRMATION)
    assert block.heard_text == HEARD


def test_the_heard_block_does_not_show_the_text_or_fragments_in_repr_or_str():
    block = heard_block_of(
        _checked([Doubt(DoubtKind.FRAGMENT, FRAGMENT)]),
        HeardDecision.SEND_WITHOUT_QUESTION,
    )

    for rendered in (repr(block), str(block)):
        assert "Марин" not in rendered
        assert FRAGMENT not in rendered


def test_the_sent_block_equals_the_payload_messages_exactly_as_they_go_out():
    system = "\n  system words\u00a0with nbsp  \n"
    request = "  \u00a0sanitized <PERSON_1>\r\nrequest\n\n  "
    payload = build_outbound_payload(system, request)

    block = sent_block_of(payload)

    assert [
        {"role": role, "content": content} for role, content in block.messages
    ] == payload.to_chat_messages()


def test_the_sent_text_lists_every_message_that_goes_out():
    payload = build_outbound_payload("system words", "sanitized request")

    text = sent_block_of(payload).text

    assert "system words" in text
    assert "sanitized request" in text


def test_the_sent_block_does_not_show_the_text_in_repr_or_str():
    block = sent_block_of(build_outbound_payload("system words", "sanitized request"))

    for rendered in (repr(block), str(block)):
        assert "sanitized" not in rendered
        assert "system words" not in rendered


@pytest.mark.parametrize("block_type", [HeardBlock, SentBlock])
def test_blocks_are_frozen(block_type):
    block = (
        heard_block_of(_checked(), HeardDecision.ASK_CONFIRMATION)
        if block_type is HeardBlock
        else sent_block_of(build_outbound_payload("s", "u"))
    )

    with pytest.raises(AttributeError):
        block.anything = 1
