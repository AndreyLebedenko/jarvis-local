"""The exchange of the personal proxy in the Journal, end to end: the real
service with fake stages, the writer in the sink chain, and a real recorder over
a real store. Every test names what must be stored (or must not)."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _service_fakes import (
    ANSWER_DELTAS,
    HEARD,
    MAPPING,
    SANITIZED,
    RecordingSink,
    Rig,
    closed,
    make_wav,
    settled,
)

from jarvis.core.config import HistorySemanticSettings
from jarvis.history import (
    AutomaticRetrievalSelectionLimits,
    ConservativeUtf8TokenEstimator,
    ConversationTurn,
    RecentHistoryExchange,
    RecentHistorySelection,
    build_automatic_retrieval_request,
    select_automatic_retrieval_passages,
)
from jarvis.journal import (
    HistoryRetrievalQuery,
    HistoryRetrievalService,
    JournalRecorder,
    JournalSearchIndex,
    JournalStore,
    Pymorphy3Normalizer,
    SemanticCandidateResult,
    SemanticCandidateStatus,
)
from jarvis.journal.events import JournalEvent
from jarvis.journal.fork import build_fork_seed
from jarvis.journal.provenance import ProvenanceEligibility, ProvenanceSourceKind
from jarvis.personal_proxy.check_result import Doubt, DoubtKind
from jarvis.personal_proxy.confirmation_blocks import HeardBlock, HeardDecision
from jarvis.personal_proxy.external_error import (
    ExternalClientError,
    ExternalErrorKind,
)
from jarvis.personal_proxy.findings import GateCategory
from jarvis.personal_proxy.journal_writer import ProxyJournalWriter
from jarvis.personal_proxy.proxy_inbox import TypedText, Utterance
from jarvis.personal_proxy.restoration_result import RestorationMethod
from jarvis.personal_proxy.sanitize_result import SanitizeResult, SanitizeVerdict
from jarvis.personal_proxy.service_blocks import (
    AnswerBlock,
    AnswerCompleteBlock,
    DryRunBlock,
    NoticeBlock,
    NoticeKind,
    RequestSourceBlock,
)

FIRST_ANSWER = "Хорошо, передаю Марине Крыловой."
SECOND_ANSWER = "Это займёт минуту."
UTTERANCE = Utterance(make_wav())
RAW_TRANSCRIPT = "передай марине крыловой что документы готовы"


def clock_ticks():
    base = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
    moments = iter(base.replace(second=second) for second in range(60))
    return lambda: next(moments)


class Journaled:
    """A rig whose sink chain ends in a writer over a real recorder."""

    def __init__(self, tmp_path: Path, *, dry_run=False, recorder=None, **rig_args):
        self.store = JournalStore(tmp_path / "journal")
        self.recorder = recorder or JournalRecorder(self.store, clock=clock_ticks())
        self.chat = RecordingSink([])
        self.writer = ProxyJournalWriter(self.chat, self.recorder, dry_run=dry_run)
        self.rig = Rig(sink=self.writer, dry_run=dry_run, **rig_args)

    async def request(self, item):
        self.rig.service.start()
        try:
            self.rig.service.submit(item)
            await settled(self.rig)
        finally:
            await closed(self.rig.service)
        await self.writer.close()
        await self.recorder.wait_for_pending()

    def events(self) -> list[JournalEvent]:
        found: list[JournalEvent] = []
        for summary in self.store.list_sessions():
            found.extend(self.store.read_session(summary.session_id).events)
        return found

    def sessions(self):
        return self.store.list_sessions()


# --- what a full request leaves in the Journal ------------------------------


async def test_a_full_request_leaves_heard_sent_and_answer_in_one_session(tmp_path):
    journal = Journaled(tmp_path)

    await journal.request(UTTERANCE)

    assert len(journal.sessions()) == 1
    assert [(e.source, e.role) for e in journal.events()] == [
        ("proxy_heard", "user"),
        ("proxy_sent", "system"),
        ("proxy_answer", "assistant"),
    ]


async def test_the_heard_record_holds_the_whole_text_the_recording_and_the_raw_text(
    tmp_path,
):
    journal = Journaled(tmp_path)
    journal.rig.stages.transcription = type(journal.rig.stages.transcription)(
        RAW_TRANSCRIPT, (), ()
    )

    await journal.request(UTTERANCE)

    heard = journal.events()[0]
    assert heard.text == HEARD
    assert heard.metadata["raw_transcript"] == RAW_TRANSCRIPT
    assert heard.metadata["origin"] == "voice"
    assert heard.metadata["decision"] == "send_without_question"
    (media,) = heard.media
    stored = journal.store.media_path(heard.session_id, media).read_bytes()
    assert stored == UTTERANCE.wav


async def test_a_typed_request_is_stored_as_typed_without_a_recording(tmp_path):
    journal = Journaled(tmp_path)

    await journal.request(TypedText("Привет, как дела?"))

    heard = journal.events()[0]
    assert heard.text == "Привет, как дела?"
    assert heard.media == ()
    assert heard.metadata["origin"] == "typed"
    assert "raw_transcript" not in heard.metadata


async def test_the_sent_record_is_the_sanitized_request_that_went_out(tmp_path):
    journal = Journaled(tmp_path)

    await journal.request(UTTERANCE)

    sent = journal.events()[1]
    (payload,) = journal.rig.payloads_sent
    assert sent.text == "\n\n".join(f"{m.role}: {m.content}" for m in payload.messages)
    assert SANITIZED in sent.text
    assert sent.metadata["message_count"] == len(payload.messages)


async def test_one_answer_record_holds_the_sentences_as_shown_and_spoken(tmp_path):
    journal = Journaled(tmp_path)

    await journal.request(UTTERANCE)

    answer = journal.events()[2]
    assert answer.text == f"{FIRST_ANSWER} {SECOND_ANSWER}"
    assert answer.text == " ".join(journal.rig.spoken_texts)
    assert answer.metadata["incomplete"] is False
    assert answer.metadata["methods"] == [
        RestorationMethod.SUBSTITUTED.value,
        RestorationMethod.PASSTHROUGH.value,
    ]


async def test_an_interrupted_answer_is_stored_with_what_was_shown_as_incomplete(
    tmp_path,
):
    journal = Journaled(tmp_path)
    journal.rig.stages.stream_error = ExternalClientError(ExternalErrorKind.TIMEOUT)

    await journal.request(UTTERANCE)

    answer = next(e for e in journal.events() if e.source == "proxy_answer")
    assert answer.text == FIRST_ANSWER
    assert journal.rig.spoken_texts[0] == FIRST_ANSWER
    assert answer.metadata["incomplete"] is True
    notice = journal.events()[-1]
    assert notice.source == "proxy_notice"
    assert notice.metadata["notice_kind"] == NoticeKind.ANSWER_INCOMPLETE.value


# --- notices are content-free ------------------------------------------------


async def test_a_gate_block_is_stored_as_category_and_position_only(tmp_path):
    journal = Journaled(tmp_path)
    journal.rig.stages.sanitized = SanitizeResult(
        SanitizeVerdict.SEND, "", "Позвони на +7 912 345 67 89", {}
    )

    await journal.request(UTTERANCE)

    notice = journal.events()[-1]
    assert notice.source == "proxy_notice"
    assert notice.text == ""
    assert notice.metadata["notice_kind"] == "gate_blocked"
    (finding, *_) = notice.metadata["notice_detail"]
    assert finding["category"] == GateCategory.PHONE.value
    assert set(finding) == {"category", "message_index", "start", "end", "stage"}
    assert "912" not in json.dumps(notice.metadata)


async def test_a_refusal_stores_its_kind_and_never_the_models_reason(tmp_path):
    journal = Journaled(tmp_path)
    journal.rig.stages.sanitized = SanitizeResult(
        SanitizeVerdict.REFUSE, "тема: здоровье ребёнка", "", {}
    )

    await journal.request(UTTERANCE)

    notice = journal.events()[-1]
    assert notice.metadata["notice_kind"] == "refused"
    assert "здоровье" not in json.dumps(notice.metadata, ensure_ascii=False)
    assert [e.source for e in journal.events()] == ["proxy_notice"]


# --- what is never written ---------------------------------------------------


async def test_a_dry_run_writes_nothing_and_creates_no_session(tmp_path):
    journal = Journaled(tmp_path, dry_run=True)

    await journal.request(UTTERANCE)

    assert [type(b) for b in journal.chat.blocks] == [DryRunBlock]
    assert journal.sessions() == []
    assert journal.recorder.session_id is None


async def test_the_mapping_and_the_raw_external_answer_are_never_written(tmp_path):
    journal = Journaled(tmp_path)

    await journal.request(UTTERANCE)

    stored = [json.dumps(_as_dict(e), ensure_ascii=False) for e in journal.events()]
    raw_answer = "".join(ANSWER_DELTAS)
    placeholder = next(iter(MAPPING))
    assert all(raw_answer not in text for text in stored)
    assert all("mapping" not in text for text in stored)
    sent, answer = stored[1], journal.events()[2].text
    assert all(original not in sent for original in MAPPING.values())
    assert placeholder not in answer
    assert placeholder in sent


# --- failures of persistence never change the request ------------------------


class FailingRecorder:
    def __init__(self, message="storage broke"):
        self.message = message
        self.attempts = 0

    async def record_proxy_heard(self, *args, **kwargs):
        self._fail()

    async def record_proxy_sent(self, *args, **kwargs):
        self._fail()

    async def record_proxy_answer(self, *args, **kwargs):
        self._fail()

    async def record_proxy_notice(self, *args, **kwargs):
        self._fail()

    async def wait_for_pending(self):
        pass

    def _fail(self):
        self.attempts += 1
        raise RuntimeError(self.message)


async def test_a_failing_recorder_changes_neither_what_is_sent_nor_what_is_shown(
    tmp_path,
):
    working = Journaled(tmp_path / "working")
    failing = Journaled(tmp_path / "failing", recorder=FailingRecorder())

    await working.request(UTTERANCE)
    await failing.request(UTTERANCE)

    assert failing.recorder.attempts > 0
    assert [p.to_chat_messages() for p in failing.rig.payloads_sent] == [
        p.to_chat_messages() for p in working.rig.payloads_sent
    ]
    assert failing.rig.spoken_texts == working.rig.spoken_texts
    assert [type(b) for b in failing.chat.blocks] == [
        type(b) for b in working.chat.blocks
    ]


async def test_blocks_reach_the_chat_sink_before_and_despite_persistence(tmp_path):
    order = []

    class Chat(RecordingSink):
        async def post(self, block):
            order.append("chat")
            await super().post(block)

    class Recorder(FailingRecorder):
        def _fail(self):
            order.append("persist")
            super()._fail()

    chat = Chat([])
    writer = ProxyJournalWriter(chat, Recorder(), dry_run=False)

    await writer.post(NoticeBlock(NoticeKind.NO_SPEECH))

    assert order == ["chat", "persist"]
    assert [b.kind for b in chat.of(NoticeBlock)] == [NoticeKind.NO_SPEECH]


async def test_nothing_is_persisted_when_the_chat_sink_itself_fails():
    recorder = FailingRecorder()
    writer = ProxyJournalWriter(
        RecordingSink([], fail_on=NoticeBlock), recorder, dry_run=False
    )

    with pytest.raises(RuntimeError):
        await writer.post(NoticeBlock(NoticeKind.NO_SPEECH))

    assert recorder.attempts == 0


# --- logs --------------------------------------------------------------------


async def test_logs_never_contain_the_heard_text_the_mapping_or_the_answer(
    tmp_path, caplog
):
    caplog.set_level(logging.DEBUG)
    private = (HEARD, *MAPPING.values(), FIRST_ANSWER, SECOND_ANSWER, SANITIZED)
    working = Journaled(tmp_path / "working")
    failing = Journaled(tmp_path / "failing", recorder=FailingRecorder(HEARD))

    await working.request(UTTERANCE)
    await failing.request(UTTERANCE)

    assert "Journal write failed: RuntimeError" in caplog.text
    for text in private:
        assert text not in caplog.text


def test_the_writer_and_the_source_block_hide_personal_text_from_repr():
    writer = ProxyJournalWriter(RecordingSink([]), FailingRecorder(), dry_run=False)
    block = RequestSourceBlock(b"audio-bytes", HEARD)

    shown = repr(writer) + repr(block) + str(block)

    assert HEARD not in shown
    assert "audio-bytes" not in shown


# --- the answer buffer -------------------------------------------------------


class RecordingRecorder:
    def __init__(self):
        self.answers = []
        self.notices = []
        self.heard = []
        self.answer_kwargs = []

    async def record_proxy_heard(self, text, **kwargs):
        self.heard.append(kwargs)

    async def record_proxy_sent(self, *args, **kwargs):
        pass

    async def record_proxy_answer(self, text, **kwargs):
        self.answers.append((text, kwargs["incomplete"]))
        self.answer_kwargs.append(kwargs)

    async def record_proxy_notice(self, kind, detail):
        self.notices.append(kind)


def answer(text):
    return AnswerBlock(text, RestorationMethod.PASSTHROUGH, False)


async def test_a_doubt_is_stored_as_its_class_and_never_its_fragment():
    recorder = RecordingRecorder()
    writer = ProxyJournalWriter(RecordingSink([]), recorder, dry_run=False)

    await writer.post(
        HeardBlock(
            HEARD,
            (Doubt(DoubtKind.FRAGMENT, "Марине Крыловой"),),
            HeardDecision.ASK_CONFIRMATION,
        )
    )

    (stored,) = recorder.heard
    assert stored["doubt_kinds"] == (DoubtKind.FRAGMENT.value,)
    assert stored["decision"] == "ask_confirmation"
    assert "Марине" not in repr(stored)


async def test_an_interrupt_notice_closes_the_answer_as_incomplete_before_itself():
    recorder = RecordingRecorder()
    writer = ProxyJournalWriter(RecordingSink([]), recorder, dry_run=False)

    await writer.post(answer("Первое."))
    await writer.post(NoticeBlock(NoticeKind.INTERRUPTED))

    assert recorder.answers == [("Первое.", True)]
    assert recorder.notices == ["interrupted"]


async def test_a_speech_problem_in_the_middle_does_not_split_the_answer():
    recorder = RecordingRecorder()
    writer = ProxyJournalWriter(RecordingSink([]), recorder, dry_run=False)

    await writer.post(answer("Первое."))
    await writer.post(NoticeBlock(NoticeKind.SPEECH_FAILED))
    await writer.post(answer("Второе."))
    await writer.post(AnswerCompleteBlock())

    assert recorder.answers == [("Первое. Второе.", False)]


async def test_closing_writes_a_pending_answer_as_incomplete_once():
    recorder = RecordingRecorder()
    writer = ProxyJournalWriter(RecordingSink([]), recorder, dry_run=False)

    await writer.post(answer("Первое."))
    await writer.close()
    await writer.close()

    assert recorder.answers == [("Первое.", True)]


# --- provenance, retrieval, fork and search ---------------------------------


class NoSemantic:
    def query(self, request):
        return SemanticCandidateResult(SemanticCandidateStatus.UNAVAILABLE)


def retrieval_over(tmp_path: Path, store: JournalStore):
    index = JournalSearchIndex(store, tmp_path / "derived")
    index.rebuild()
    settings = HistorySemanticSettings(
        model="fixture",
        query_prefix="",
        passage_prefix="",
        separation=0.05,
        top_ratio=0.98,
        dimension=1,
    )
    service = HistoryRetrievalService(
        index.repository, NoSemantic(), settings, Pymorphy3Normalizer()
    )
    return index, service


async def test_proxy_records_are_found_by_model_search_but_never_by_auto_retrieval(
    tmp_path,
):
    journal = Journaled(tmp_path)
    await journal.request(UTTERANCE)
    _, service = retrieval_over(tmp_path, journal.store)

    model = service.retrieve(
        HistoryRetrievalQuery(
            "Марине", required_eligibility=ProvenanceEligibility.MODEL_SEARCH
        )
    )
    auto = service.retrieve(
        HistoryRetrievalQuery(
            "Марине",
            required_eligibility=ProvenanceEligibility.AUTO_RETRIEVAL,
        )
    )

    kinds = {c.provenance.source_kind for c in model.candidates}
    assert kinds == {
        ProvenanceSourceKind.PROXY_REQUEST,
        ProvenanceSourceKind.PROXY_ANSWER,
    }
    assert auto.candidates == ()


async def test_the_automatic_selector_drops_proxy_records_and_counts_them(tmp_path):
    journal = Journaled(tmp_path)
    await journal.request(UTTERANCE)
    _, service = retrieval_over(tmp_path, journal.store)
    candidates = service.retrieve(HistoryRetrievalQuery("Марине")).candidates
    exchange = RecentHistoryExchange(
        turns=(ConversationTurn(role="user", text="Что с документами?"),)
    )
    recent = RecentHistorySelection(
        prefix_turns=(),
        exchanges=(exchange,),
        estimated_tokens=0,
        max_tokens=256,
        total_exchange_count=1,
        selected_exchange_count=1,
        dropped_exchange_count=0,
        requested_minimum_recent_exchanges=1,
        minimum_recent_exchanges_met=True,
        truncated=False,
        blank_context_cleared=False,
    )
    request = build_automatic_retrieval_request("документы", recent)

    selection = select_automatic_retrieval_passages(
        request,
        candidates,
        AutomaticRetrievalSelectionLimits(),
        estimator=ConservativeUtf8TokenEstimator(),
    )

    assert candidates
    assert selection.selected_passages == ()
    assert selection.skipped_ineligible_count == len(candidates)


async def test_no_proxy_record_enters_a_fork_seed_and_the_drops_are_counted(tmp_path):
    journal = Journaled(tmp_path)
    await journal.request(UTTERANCE)
    session_id = journal.sessions()[0].session_id

    seed = build_fork_seed(journal.store.read_session(session_id), budget_chars=10_000)

    assert seed.turns == ()
    assert seed.drop_report.excluded_events == 3


async def test_the_journal_search_labels_the_answer_with_its_source(tmp_path):
    journal = Journaled(tmp_path)
    await journal.request(UTTERANCE)
    index, _ = retrieval_over(tmp_path, journal.store)

    hits = index.search("передаю Марине")

    assert [hit.source for hit in hits] == ["proxy_answer"]


def _as_dict(event: JournalEvent) -> dict:
    return {
        "source": event.source,
        "role": event.role,
        "text": event.text,
        "media": list(event.media),
        "metadata": event.metadata,
    }


class BrokenStore(JournalStore):
    def append(self, event):
        raise OSError("disk full")


async def test_a_failing_store_logs_no_personal_text_either(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    journal = Journaled(tmp_path)
    broken = JournalRecorder(BrokenStore(tmp_path / "broken"), clock=clock_ticks())
    journal.recorder = broken
    journal.writer = ProxyJournalWriter(journal.chat, broken, dry_run=False)
    journal.rig = Rig(sink=journal.writer)

    await journal.request(UTTERANCE)

    assert "Journal write failed" in caplog.text
    for text in (HEARD, FIRST_ANSWER, SANITIZED):
        assert text not in caplog.text
    assert journal.rig.payloads_sent


async def test_a_disabled_journal_records_nothing_and_changes_nothing(tmp_path):
    store = JournalStore(tmp_path / "journal")
    journal = Journaled(
        tmp_path, recorder=JournalRecorder(store, enabled=False, clock=clock_ticks())
    )

    await journal.request(UTTERANCE)

    assert store.list_sessions() == []
    assert len(journal.rig.payloads_sent) == 1


async def test_a_dry_run_writer_forwards_every_block_and_persists_none():
    recorder = RecordingRecorder()
    chat = RecordingSink([])
    writer = ProxyJournalWriter(chat, recorder, dry_run=True)

    await writer.post(RequestSourceBlock(b"wav", HEARD))
    await writer.post(HeardBlock(HEARD, (), HeardDecision.SEND_WITHOUT_QUESTION))
    await writer.post(answer("Первое."))
    await writer.post(NoticeBlock(NoticeKind.GATE_BLOCKED))
    await writer.post(AnswerCompleteBlock())
    await writer.close()

    assert len(chat.blocks) == 3
    assert (recorder.heard, recorder.answers, recorder.notices) == ([], [], [])


async def test_a_new_request_closes_an_answer_still_being_held_as_incomplete():
    recorder = RecordingRecorder()
    writer = ProxyJournalWriter(RecordingSink([]), recorder, dry_run=False)

    await writer.post(answer("Первое."))
    await writer.post(RequestSourceBlock(None, None))

    assert recorder.answers == [("Первое.", True)]


async def test_one_unresolved_sentence_marks_the_whole_answer_unresolved():
    recorder = RecordingRecorder()
    writer = ProxyJournalWriter(RecordingSink([]), recorder, dry_run=False)

    await writer.post(AnswerBlock("Первое.", RestorationMethod.PASSTHROUGH, False))
    await writer.post(AnswerBlock("Второе.", RestorationMethod.SUBSTITUTED, True))
    await writer.post(AnswerBlock("Третье.", RestorationMethod.PASSTHROUGH, False))
    await writer.post(AnswerCompleteBlock())

    (kwargs,) = recorder.answer_kwargs
    assert kwargs["unresolved_placeholders"] is True


async def test_a_clean_answer_is_not_marked_unresolved():
    recorder = RecordingRecorder()
    writer = ProxyJournalWriter(RecordingSink([]), recorder, dry_run=False)

    await writer.post(answer("Первое."))
    await writer.post(AnswerCompleteBlock())

    (kwargs,) = recorder.answer_kwargs
    assert kwargs["unresolved_placeholders"] is False
