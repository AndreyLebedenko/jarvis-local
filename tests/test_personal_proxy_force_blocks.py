"""The forced marker as data: on the sent block, on the dry-run block, in the
block payload, in the stored proxy_sent record, and the two command notices."""

from datetime import UTC, datetime

import pytest

from jarvis.journal import JournalRecorder, JournalStore
from jarvis.personal_proxy.check.check_result import Doubt, DoubtKind
from jarvis.personal_proxy.common.payload import build_outbound_payload
from jarvis.personal_proxy.confirmation.confirmation_blocks import (
    SentBlock,
    sent_block_of,
)
from jarvis.personal_proxy.reporting.block_payload import block_payload
from jarvis.personal_proxy.reporting.notice_class import BLOCKING_KINDS, notice_class
from jarvis.personal_proxy.reporting.service_blocks import (
    DryRunBlock,
    NoticeBlock,
    NoticeKind,
)
from jarvis.personal_proxy.reporting.service_texts import notice_text, spoken_notice
from jarvis.personal_proxy.sanitize.sanitize_result import SanitizeVerdict

SECRET = "Марина Крылова"


def _dry_run_block(**overrides):
    fields = {
        "whisper_text": None,
        "checked_text": "t",
        "doubts": (Doubt(DoubtKind.REWRITE),),
        "would_ask": False,
        "sanitized_text": "t",
        "mapping": {},
        "verdict": SanitizeVerdict.SEND,
        "reason": "",
        "gate_findings": (),
        "messages": (("user", "t"),),
    }
    fields.update(overrides)
    return DryRunBlock(**fields)


def test_a_sent_block_is_not_forced_by_default():
    assert SentBlock((("user", "hi"),)).forced is False
    assert sent_block_of(build_outbound_payload("s", "u")).forced is False


def test_a_forced_sent_block_keeps_the_messages_and_the_marker():
    block = sent_block_of(build_outbound_payload("rules", SECRET), forced=True)

    assert block.forced is True
    assert block.messages == (("system", "rules"), ("user", SECRET))
    assert SECRET not in repr(block)


def test_the_sent_payload_says_whether_the_request_was_forced():
    plain = SentBlock((("user", "hi"),))
    forced = SentBlock((("user", "hi"),), forced=True)

    assert block_payload(plain, "en")["forced"] is False
    assert block_payload(forced, "en")["forced"] is True


def test_a_dry_run_block_is_not_forced_by_default_and_says_so_when_it_is():
    assert block_payload(_dry_run_block(), "en")["forced"] is False
    assert block_payload(_dry_run_block(forced=True), "en")["forced"] is True


def _recorder(tmp_path):
    store = JournalStore(tmp_path)
    clock = datetime(2026, 10, 24, 10, 0, 0, tzinfo=UTC)
    return store, JournalRecorder(store, clock=lambda: clock)


async def _stored_sent_metadata(tmp_path, **kwargs):
    store, recorder = _recorder(tmp_path)
    await recorder.record_proxy_sent("system: s\n\nuser: u", message_count=2, **kwargs)
    await recorder.wait_for_pending()
    (summary,) = store.list_sessions()
    (event,) = store.read_session(summary.session_id).events
    return event.metadata


async def test_a_forced_sent_record_carries_the_marker_in_its_metadata(tmp_path):
    metadata = await _stored_sent_metadata(tmp_path, forced=True)

    assert metadata == {"message_count": 2, "forced": True}


async def test_a_sent_record_that_was_not_forced_has_no_marker_key(tmp_path):
    metadata = await _stored_sent_metadata(tmp_path)

    assert metadata == {"message_count": 2}


def test_the_two_command_notices_are_fixed_texts_in_both_languages():
    for kind in (NoticeKind.UNKNOWN_COMMAND, NoticeKind.EMPTY_COMMAND):
        english = notice_text(NoticeBlock(kind), "en")
        russian = notice_text(NoticeBlock(kind), "ru")
        assert english != russian
        assert "nothing was sent" in english
        assert "ничего не отправлено" in russian.lower()


def test_the_unknown_command_notice_names_the_known_command():
    assert "/force" in notice_text(NoticeBlock(NoticeKind.UNKNOWN_COMMAND), "en")
    assert "/force" in notice_text(NoticeBlock(NoticeKind.UNKNOWN_COMMAND), "ru")


@pytest.mark.parametrize("kind", [NoticeKind.UNKNOWN_COMMAND, NoticeKind.EMPTY_COMMAND])
def test_a_command_notice_is_content_free_and_not_spoken(kind):
    assert notice_class(NoticeBlock(kind)) == {"kind": kind.value, "detail": None}
    assert spoken_notice(NoticeBlock(kind), "en") is None
    assert kind not in BLOCKING_KINDS


def test_a_forced_sent_block_hides_its_text_in_str():
    assert SECRET not in str(SentBlock((("user", SECRET),), forced=True))


def test_the_unknown_command_notice_says_how_to_send_the_text_as_plain_text():
    english = notice_text(NoticeBlock(NoticeKind.UNKNOWN_COMMAND), "en")
    russian = notice_text(NoticeBlock(NoticeKind.UNKNOWN_COMMAND), "ru")

    assert "word before the slash" in english
    assert "слово перед косой чертой" in russian
