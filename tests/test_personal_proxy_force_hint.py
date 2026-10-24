"""The /force hint in the notices of a request that could not be prepared or was
refused: shown for a typed request only, fixed text, both languages."""

from contextlib import asynccontextmanager

import pytest
from _service_fakes import Rig, closed, make_wav, settled

from jarvis.personal_proxy.reporting.service_blocks import NoticeBlock, NoticeKind
from jarvis.personal_proxy.reporting.service_texts import notice_text, spoken_notice
from jarvis.personal_proxy.request.proxy_inbox import TypedText, Utterance
from jarvis.personal_proxy.sanitize.sanitize_result import (
    SanitizeFailure,
    SanitizeFailureClass,
    SanitizeResult,
    SanitizeVerdict,
)

HINT_EN = "/force"
REASON = "a sensitive topic"
TYPED = TypedText("What is a relay?")
SPOKEN = Utterance(make_wav())
HINTED_KINDS = (NoticeKind.SANITIZE_FAILED, NoticeKind.REFUSED)


@asynccontextmanager
async def running(rig):
    rig.service.start()
    try:
        yield rig
    finally:
        await closed(rig.service)


async def notice_of(rig, item):
    async with running(rig):
        rig.service.submit(item)
        await settled(rig)
    (notice,) = rig.sink.of(NoticeBlock)
    return notice


def failing_rig(language="en"):
    rig = Rig(language=language)
    rig.stages.sanitized = SanitizeFailure(SanitizeFailureClass.UNEXPECTED_REFUSAL)
    return rig


def refusing_rig(language="en"):
    rig = Rig(language=language)
    rig.stages.sanitized = SanitizeResult(SanitizeVerdict.REFUSE, REASON, "", {})
    return rig


@pytest.mark.parametrize("kind", HINTED_KINDS)
@pytest.mark.parametrize("language", ["en", "ru"])
def test_a_forceable_notice_carries_the_force_command(kind, language):
    shown = notice_text(NoticeBlock(kind, forceable=True), language)

    assert HINT_EN in shown


@pytest.mark.parametrize("kind", HINTED_KINDS)
@pytest.mark.parametrize("language", ["en", "ru"])
def test_a_notice_that_is_not_forceable_has_no_hint(kind, language):
    assert HINT_EN not in notice_text(NoticeBlock(kind), language)


@pytest.mark.parametrize("language", ["en", "ru"])
def test_the_hint_does_not_replace_the_text_detail_or_reason(language):
    plain = notice_text(
        NoticeBlock(NoticeKind.SANITIZE_FAILED, SanitizeFailureClass.NO_JSON, REASON),
        language,
    )
    hinted = notice_text(
        NoticeBlock(
            NoticeKind.SANITIZE_FAILED,
            SanitizeFailureClass.NO_JSON,
            REASON,
            forceable=True,
        ),
        language,
    )
    refused_plain = notice_text(
        NoticeBlock(NoticeKind.REFUSED, reason=REASON), language
    )
    refused_hinted = notice_text(
        NoticeBlock(NoticeKind.REFUSED, reason=REASON, forceable=True), language
    )

    assert hinted.startswith(plain)
    assert refused_hinted.startswith(refused_plain)
    assert REASON in refused_hinted


def test_the_hint_texts_are_fixed_and_differ_by_language():
    english = notice_text(NoticeBlock(NoticeKind.REFUSED, forceable=True), "en")
    russian = notice_text(NoticeBlock(NoticeKind.REFUSED, forceable=True), "ru")

    assert "send" in english.casefold()
    assert "отправ" in russian.casefold()
    assert english != russian


@pytest.mark.parametrize("kind", HINTED_KINDS)
def test_the_spoken_sentence_never_carries_the_hint(kind):
    for language in ("en", "ru"):
        assert HINT_EN not in spoken_notice(NoticeBlock(kind, forceable=True), language)


@pytest.mark.parametrize(
    "kind",
    [kind for kind in NoticeKind if kind not in HINTED_KINDS],
)
def test_no_other_notice_kind_shows_the_hint(kind):
    block = NoticeBlock(kind, forceable=True)

    assert HINT_EN not in notice_text(block, "en").replace("/force (or /f)", "")


async def test_a_typed_request_that_fails_to_prepare_gets_a_forceable_notice():
    notice = await notice_of(failing_rig(), TYPED)

    assert (notice.kind, notice.forceable) == (NoticeKind.SANITIZE_FAILED, True)


async def test_a_spoken_request_that_fails_to_prepare_gets_a_plain_notice():
    notice = await notice_of(failing_rig(), SPOKEN)

    assert (notice.kind, notice.forceable) == (NoticeKind.SANITIZE_FAILED, False)


async def test_a_typed_refusal_gets_a_forceable_notice_that_keeps_the_reason():
    notice = await notice_of(refusing_rig(), TYPED)

    assert (notice.kind, notice.reason, notice.forceable) == (
        NoticeKind.REFUSED,
        REASON,
        True,
    )


async def test_a_spoken_refusal_gets_a_plain_notice():
    notice = await notice_of(refusing_rig(), SPOKEN)

    assert (notice.kind, notice.forceable) == (NoticeKind.REFUSED, False)


async def test_a_typed_send_that_is_empty_after_sanitizing_gets_a_forceable_notice():
    rig = Rig()
    rig.stages.sanitized = SanitizeResult(SanitizeVerdict.SEND, "", "  ", {})

    notice = await notice_of(rig, TYPED)

    assert (notice.kind, notice.forceable) == (NoticeKind.SANITIZE_FAILED, True)


async def test_the_spoken_sentence_of_a_typed_failure_is_the_plain_one():
    rig = failing_rig()

    notice = await notice_of(rig, TYPED)

    assert rig.spoken_texts == [spoken_notice(NoticeBlock(notice.kind), "en")]
