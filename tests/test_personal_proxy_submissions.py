import logging

import pytest

from jarvis.audio.input import UtteranceChunk
from jarvis.core.lifecycle import TextSubmissionReason
from jarvis.personal_proxy.request.proxy_inbox import (
    InboxFullError,
    TypedText,
    Utterance,
)
from jarvis.personal_proxy.service.proxy_service import ServiceClosedError
from jarvis.personal_proxy.service.proxy_submissions import ProxySubmissions

SECRET = "Марина Крылова"


class _Service:
    def __init__(self, error=None):
        self.items = []
        self.error = error

    def submit(self, item):
        if self.error is not None:
            raise self.error
        self.items.append(item)


def _submissions(service, dropped, max_chars=20):
    async def report_dropped():
        dropped.append("dropped")

    return ProxySubmissions(
        service, text_max_chars=max_chars, report_dropped=report_dropped
    )


async def test_an_utterance_is_enqueued_with_its_wav_bytes():
    service = _Service()
    chunk = UtteranceChunk(wav_bytes=b"RIFFwav", start_seconds=0, end_seconds=1)

    await _submissions(service, []).on_utterance(chunk)

    assert service.items == [Utterance(b"RIFFwav")]


@pytest.mark.parametrize("error", [InboxFullError(), ServiceClosedError()])
async def test_a_dropped_utterance_is_reported_not_raised(error):
    dropped = []
    chunk = UtteranceChunk(wav_bytes=b"x", start_seconds=0, end_seconds=1)

    await _submissions(_Service(error), dropped).on_utterance(chunk)

    assert dropped == ["dropped"]


async def test_accepted_text_is_enqueued_unchanged():
    service = _Service()

    result = await _submissions(service, []).submit_text(f"  {SECRET} ")

    assert result.reason is TextSubmissionReason.ACCEPTED
    assert result.max_chars == 20
    assert service.items == [TypedText(f"  {SECRET} ")]


@pytest.mark.parametrize("text", ["", "   \n"])
async def test_blank_text_is_empty_and_not_enqueued(text):
    service = _Service()

    result = await _submissions(service, []).submit_text(text)

    assert result.reason is TextSubmissionReason.EMPTY
    assert service.items == []


async def test_text_over_the_limit_is_refused_and_not_enqueued():
    service = _Service()

    result = await _submissions(service, [], max_chars=5).submit_text("x" * 6)

    assert result.reason is TextSubmissionReason.OVER_LIMIT
    assert result.max_chars == 5
    assert service.items == []


@pytest.mark.parametrize("error", [InboxFullError(), ServiceClosedError()])
async def test_text_that_cannot_be_enqueued_is_busy(error):
    result = await _submissions(_Service(error), []).submit_text("hello")

    assert result.reason is TextSubmissionReason.BUSY


async def test_nothing_is_logged(caplog):
    caplog.set_level(logging.DEBUG)
    service = _Service(InboxFullError())
    submissions = _submissions(service, [])

    await submissions.submit_text(SECRET)
    await submissions.on_utterance(UtteranceChunk(b"x", 0, 1))

    assert caplog.records == []
