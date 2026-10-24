import logging

from _service_fakes import HEARD, RecordingSink

from jarvis.personal_proxy.common.findings import Finding, GateCategory
from jarvis.personal_proxy.confirmation.confirmation_blocks import SentBlock
from jarvis.personal_proxy.reporting.service_blocks import (
    DryRunBlock,
    NoticeBlock,
    NoticeKind,
)
from jarvis.personal_proxy.reporting.status_sink import ProxyStatusSink
from jarvis.personal_proxy.sanitize.sanitize_result import SanitizeVerdict


class _Publisher:
    def __init__(self, fail=False):
        self.reasons = []
        self.fail = fail

    def set_proxy_last_block(self, reason):
        if self.fail:
            raise RuntimeError(HEARD)
        self.reasons.append(reason)


def _sink(publisher=None):
    chat = RecordingSink([])
    publisher = publisher or _Publisher()
    return chat, publisher, ProxyStatusSink(chat, publisher)


async def test_a_gate_block_is_published_as_its_category_and_position_only():
    chat, publisher, sink = _sink()
    finding = Finding(GateCategory.PHONE, 1, 4, 9)

    await sink.post(NoticeBlock(NoticeKind.GATE_BLOCKED, (finding,)))

    assert publisher.reasons == [
        {
            "kind": "gate_blocked",
            "detail": [
                {
                    "category": "phone",
                    "message_index": 1,
                    "start": 4,
                    "end": 9,
                    "stage": None,
                }
            ],
        }
    ]
    assert len(chat.blocks) == 1


async def test_a_refusal_publishes_its_kind_and_never_the_reason_text():
    _, publisher, sink = _sink()

    await sink.post(NoticeBlock(NoticeKind.REFUSED, reason="topic: private health"))

    assert publisher.reasons == [{"kind": "refused", "detail": None}]


async def test_a_notice_that_does_not_stop_a_request_is_not_a_block_reason():
    _, publisher, sink = _sink()

    for kind in (NoticeKind.INTERRUPTED, NoticeKind.SPEECH_FAILED, NoticeKind.BUSY):
        await sink.post(NoticeBlock(kind))

    assert publisher.reasons == []


async def test_a_request_that_goes_out_clears_the_reason():
    _, publisher, sink = _sink()

    await sink.post(NoticeBlock(NoticeKind.NOT_SENT))
    await sink.post(SentBlock((("user", "hello"),)))

    assert publisher.reasons == [{"kind": "not_sent", "detail": None}, None]


async def test_a_dry_run_stop_clears_the_reason():
    _, publisher, sink = _sink()
    block = DryRunBlock(
        None, "", (), False, "", {}, SanitizeVerdict.SEND, "", (), (("user", "x"),)
    )

    await sink.post(NoticeBlock(NoticeKind.NOT_SENT))
    await sink.post(block)

    assert publisher.reasons[-1] is None


async def test_a_failing_publisher_never_reaches_the_service_or_the_log(caplog):
    caplog.set_level(logging.DEBUG)
    chat, _, sink = _sink(_Publisher(fail=True))

    await sink.post(NoticeBlock(NoticeKind.NOT_SENT))

    assert len(chat.blocks) == 1
    assert "Status update failed: RuntimeError" in caplog.text
    assert HEARD not in caplog.text
