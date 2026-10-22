import json

import pytest

from jarvis.personal_proxy.block_payload import block_payload
from jarvis.personal_proxy.chat_sink import TransportChatSink
from jarvis.personal_proxy.check_result import Doubt, DoubtKind
from jarvis.personal_proxy.confirmation_blocks import (
    HeardBlock,
    HeardDecision,
    SentBlock,
)
from jarvis.personal_proxy.findings import Finding, GateCategory
from jarvis.personal_proxy.restoration_result import RestorationMethod
from jarvis.personal_proxy.sanitize_result import SanitizeVerdict
from jarvis.personal_proxy.service_blocks import (
    AnswerBlock,
    DryRunBlock,
    NoticeBlock,
    NoticeKind,
)

SECRET = "Марина Крылова"


def test_a_heard_block_carries_the_whole_heard_text_and_its_doubts():
    block = HeardBlock(
        SECRET, (Doubt(DoubtKind.FRAGMENT, "Крылова"),), HeardDecision.ASK_CONFIRMATION
    )

    assert block_payload(block, "ru") == {
        "type": "heard",
        "text": SECRET,
        "doubts": [{"kind": "fragment", "fragment": "Крылова"}],
        "decision": "ask_confirmation",
    }


def test_a_sent_block_lists_every_message_that_went_out():
    block = SentBlock((("system", "rules"), ("user", "Hi <PERSON_1>")))

    assert block_payload(block, "en") == {
        "type": "sent",
        "messages": [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "Hi <PERSON_1>"},
        ],
    }


def test_an_answer_block_carries_the_method_and_the_unresolved_flag():
    block = AnswerBlock("Привет, Марина.", RestorationMethod.SUBSTITUTED, True)

    assert block_payload(block, "ru") == {
        "type": "answer",
        "text": "Привет, Марина.",
        "method": "substituted",
        "unresolved": True,
    }


def test_a_notice_is_rendered_from_the_fixed_texts_in_the_asked_language():
    block = NoticeBlock(NoticeKind.INTERRUPTED)

    assert block_payload(block, "en") == {
        "type": "notice",
        "kind": "interrupted",
        "text": "The request was interrupted.",
    }
    assert block_payload(block, "ru")["text"] == "Запрос прерван."


def test_a_gate_notice_names_the_category_and_position_but_no_value():
    block = NoticeBlock(
        NoticeKind.GATE_BLOCKED, (Finding(GateCategory.PHONE, 1, 4, 9),)
    )

    text = block_payload(block, "en")["text"]

    assert "a phone number" in text
    assert "message 2, characters 4-9" in text


def test_a_dry_run_block_carries_the_whole_intermediate_state():
    block = DryRunBlock(
        whisper_text="heard",
        checked_text="checked",
        doubts=(Doubt(DoubtKind.REWRITE),),
        would_ask=True,
        sanitized_text="clean <PERSON_1>",
        mapping={"<PERSON_1>": SECRET},
        verdict=SanitizeVerdict.SEND,
        reason="",
        gate_findings=(Finding(GateCategory.EMAIL, 0, 1, 2),),
        messages=(("user", "clean <PERSON_1>"),),
    )

    payload = block_payload(block, "en")

    assert payload["type"] == "dry_run"
    assert payload["mapping"] == {"<PERSON_1>": SECRET}
    assert payload["doubts"] == [{"kind": "rewrite", "fragment": None}]
    assert payload["gate_findings"] == [
        {"category": "email", "message_index": 0, "start": 1, "end": 2, "stage": None}
    ]
    assert payload["verdict"] == "send"
    json.dumps(payload)


def test_a_value_that_is_not_a_block_is_refused_without_echoing_it():
    with pytest.raises(TypeError) as raised:
        block_payload(SECRET, "en")

    assert SECRET not in str(raised.value)


class _Publisher:
    def __init__(self):
        self.payloads = []

    def publish_proxy_block(self, payload):
        self.payloads.append(payload)


async def test_the_sink_publishes_each_block_in_the_current_language():
    publisher = _Publisher()
    language = ["en"]
    sink = TransportChatSink(publisher, lambda: language[0])

    await sink.post(NoticeBlock(NoticeKind.INTERRUPTED))
    language[0] = "ru"
    await sink.post(NoticeBlock(NoticeKind.INTERRUPTED))

    assert [payload["text"] for payload in publisher.payloads] == [
        "The request was interrupted.",
        "Запрос прерван.",
    ]
