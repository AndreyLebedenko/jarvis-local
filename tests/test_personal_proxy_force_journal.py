"""What a forced request leaves in the Journal: the real service with fake
stages, the writer in the sink chain, and a real recorder over a real store."""

from datetime import UTC, datetime

from _service_fakes import RecordingSink, Rig, closed, settled

from jarvis.journal import JournalRecorder, JournalStore
from jarvis.journal.fork import build_fork_seed
from jarvis.personal_proxy.common.payload import DEFAULT_SYSTEM_PROMPT
from jarvis.personal_proxy.reporting.journal_writer import ProxyJournalWriter
from jarvis.personal_proxy.request.proxy_inbox import TypedText

TEXT = "What happened with the internet on Wednesday, 21 October this year?"


def _clock():
    base = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    moments = iter(base.replace(second=second) for second in range(60))
    return lambda: next(moments)


class Journaled:
    def __init__(self, tmp_path, *, dry_run=False):
        self.store = JournalStore(tmp_path / "journal")
        self.recorder = JournalRecorder(self.store, clock=_clock())
        self.writer = ProxyJournalWriter(
            RecordingSink([]), self.recorder, dry_run=dry_run
        )
        self.rig = Rig(sink=self.writer, dry_run=dry_run)

    async def request(self, typed):
        self.rig.service.start()
        try:
            self.rig.service.submit(TypedText(typed))
            await settled(self.rig)
        finally:
            await closed(self.rig.service)
        await self.writer.close()
        await self.recorder.wait_for_pending()

    def events(self):
        found = []
        for summary in self.store.list_sessions():
            found.extend(self.store.read_session(summary.session_id).events)
        return found

    def event_of(self, source):
        (event,) = [e for e in self.events() if e.source == source]
        return event


async def test_a_forced_request_stores_the_heard_the_marked_sent_and_the_answer(
    tmp_path,
):
    journal = Journaled(tmp_path)

    await journal.request(f"/force {TEXT}")

    assert [e.source for e in journal.events()] == [
        "proxy_heard",
        "proxy_sent",
        "proxy_answer",
    ]
    sent = journal.event_of("proxy_sent")
    assert sent.text == f"system: {DEFAULT_SYSTEM_PROMPT}\n\nuser: {TEXT}"
    assert sent.metadata == {"message_count": 2, "forced": True}


async def test_the_heard_record_of_a_forced_request_is_stored_as_for_any_typed_one(
    tmp_path,
):
    journal = Journaled(tmp_path)

    await journal.request(f"/f {TEXT}")

    heard = journal.event_of("proxy_heard")
    assert heard.text == TEXT
    assert heard.media == ()
    assert heard.metadata == {
        "origin": "typed",
        "decision": "send_without_question",
        "doubt_kinds": [],
    }


async def test_a_request_that_was_not_forced_has_no_marker_in_its_record(tmp_path):
    journal = Journaled(tmp_path)

    await journal.request(TEXT)

    assert "forced" not in journal.event_of("proxy_sent").metadata


async def test_a_forced_request_in_dry_run_writes_nothing(tmp_path):
    journal = Journaled(tmp_path, dry_run=True)

    await journal.request(f"/force {TEXT}")

    assert journal.events() == []


async def test_a_refused_command_stores_only_a_content_free_notice(tmp_path):
    journal = Journaled(tmp_path)

    await journal.request(f"/forse {TEXT}")

    (event,) = journal.events()
    assert event.source == "proxy_notice"
    assert event.text == ""
    assert event.metadata == {
        "notice_kind": "unknown_command",
        "notice_detail": None,
    }


async def test_a_gate_blocked_forced_request_keeps_its_heard_text_and_no_sent_record(
    tmp_path,
):
    journal = Journaled(tmp_path)

    await journal.request("/force Call +7 912 345-67-89")

    assert [e.source for e in journal.events()] == ["proxy_heard", "proxy_notice"]


async def test_the_forced_records_stay_out_of_a_fork_seed(tmp_path):
    journal = Journaled(tmp_path)
    await journal.request(f"/force {TEXT}")
    session_id = journal.store.list_sessions()[0].session_id

    seed = build_fork_seed(journal.store.read_session(session_id), budget_chars=10_000)

    assert seed.turns == ()
    assert seed.drop_report.excluded_events == 3
