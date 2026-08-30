import asyncio
import base64
import io
from datetime import datetime

import numpy as np
import soundfile as sf

import jarvis.app as main_module
from jarvis.app import (
    ConversationHistory,
    Orchestrator,
)
from jarvis.audio.input import (
    UtteranceChunk,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    FilesSettings,
)
from jarvis.core.lifecycle import (
    AttachmentSubmissionReason,
    ModelRequestInput,
    NewContextReason,
    TurnAccepted,
    TurnSource,
)
from jarvis.core.solo_session import SoloSessionState
from jarvis.dialog.backend import (
    ResponseToken,
)
from jarvis.files import SessionFileRepository, resolve_session_file_scope
from jarvis.inputs.attachments import (
    AttachmentClass,
    AttachmentPlan,
    AttachmentPlanItem,
    AttachmentUpload,
    PendingAudioMedia,
    PlannedImageMedia,
    PlannedTextPart,
    compose_turn_images,
    compose_turn_text,
)
from jarvis.inputs.capture import ScreenshotCaptured
from jarvis.inputs.clipboard import ClipboardSubmitted
from jarvis.journal import (
    JournalEvent,
    JournalEventRecord,
    JournalEventRef,
    JournalRecorder,
    JournalStore,
)
from jarvis.journal.fork import ForkSessionReason
from jarvis.ui.contract import (
    EventLevel,
    SystemEvent,
)
from tests.main_split._support_from_test_main import (
    _assert_model_request_started,
    _complete_event,
    _FakeBackend,
    _FakeJournalRecorder,
    _FakeSoundCues,
    _orchestrator,
    _RequestRecorder,
)

# --- Orchestrator: attachment turns (task-v1.6.0-6) ------------------------
#
# on_attachment_submission() goes through the same _start_turn() shared
# path as on_utterance()/on_clipboard() - busy-guard, thinking cue, and
# history recording are already covered above and are not re-tested from
# scratch here. These tests focus on what this task actually owns: turning
# an accepted AttachmentPlan into composed text/media, normalizing any
# pending audio (the one plan item planning could not fully resolve), and
# the attachment-specific source/input metadata.

_ATTACHMENT_SAMPLE_RATE = 16000


def _attachment_wav_bytes(duration_seconds: float) -> bytes:
    samples = np.zeros(
        int(_ATTACHMENT_SAMPLE_RATE * duration_seconds), dtype=np.float32
    )
    buffer = io.BytesIO()
    sf.write(buffer, samples, _ATTACHMENT_SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def _image_plan_item(filename: str = "photo.png") -> AttachmentPlanItem:
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.IMAGE,
        accepted=True,
        image=PlannedImageMedia(base64_data=base64.b64encode(b"png-bytes").decode()),
    )


def _text_plan_item(
    filename: str = "notes.txt", content: str = "hello"
) -> AttachmentPlanItem:
    wrapped = f"[Attached file: {filename}]\n{content}\n[End of {filename}]"
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.TEXT,
        accepted=True,
        text=PlannedTextPart(content=wrapped, truncated=False),
    )


def _audio_plan_item(
    filename: str = "memo.wav", duration_seconds: float = 2.0
) -> AttachmentPlanItem:
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.AUDIO,
        accepted=True,
        pending_audio=PendingAudioMedia(
            data=_attachment_wav_bytes(duration_seconds),
            content_type="audio/wav",
            duration_seconds=duration_seconds,
        ),
    )


def _undecodable_audio_plan_item(filename: str = "broken.wav") -> AttachmentPlanItem:
    return AttachmentPlanItem(
        filename=filename,
        attachment_class=AttachmentClass.AUDIO,
        accepted=True,
        pending_audio=PendingAudioMedia(
            data=b"RIFF then garbage", content_type="audio/wav", duration_seconds=1.0
        ),
    )


class _TurnAcceptedRecorder:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[TurnAccepted] = []
        bus.subscribe(TurnAccepted, self._on_event)

    async def _on_event(self, event: TurnAccepted) -> None:
        self.events.append(event)


async def test_on_attachment_submission_sends_composed_text_and_image_media():
    orchestrator, backend, sound_cues = _orchestrator()
    plan = AttachmentPlan(
        items=(_image_plan_item("photo.png"), _text_plan_item("notes.txt", "hello"))
    )

    result = await orchestrator.on_attachment_submission("check these", plan)

    assert result.reason is AttachmentSubmissionReason.ACCEPTED
    assert sound_cues.played == ["thinking"]
    [(messages, media)] = backend.calls
    assert messages[-1] == {
        "role": "user",
        "content": compose_turn_text("check these", plan),
        "images": list(compose_turn_images(plan)),
    }
    assert media == list(compose_turn_images(plan))


async def test_on_attachment_submission_normalizes_audio_and_appends_clip_and_cue():
    orchestrator, backend, _sound_cues = _orchestrator()
    plan = AttachmentPlan(items=(_audio_plan_item("memo.wav", duration_seconds=2.0),))

    await orchestrator.on_attachment_submission("", plan)

    [(messages, media)] = backend.calls
    assert len(media) == 1  # one <=30s clip for a 2s file
    assert messages[-1]["content"] == "[Attached audio: memo.wav, 2.0 s]"


async def test_on_attachment_submission_respects_configured_max_audio_clips():
    # 65 s of audio is 3 clips at the 30 s/clip window (30, 30, 5), which
    # the default cap (3) accepts but a configured cap of 2 must reject -
    # confirms build_app()'s settings.attachments.max_audio_clips actually
    # reaches normalize_audio_attachment(), not just its own default.
    bus = EventBus()
    events: list[SystemEvent] = []

    async def on_system_event(event: SystemEvent) -> None:
        events.append(event)

    bus.subscribe(SystemEvent, on_system_event)
    orchestrator, backend, _sound_cues = _orchestrator(
        bus=bus, max_audio_attachment_clips=2
    )
    plan = AttachmentPlan(
        items=(
            _text_plan_item("notes.txt", "hello"),
            _audio_plan_item("long.wav", duration_seconds=65.0),
        )
    )

    await orchestrator.on_attachment_submission("", plan)

    # the turn still went through with what was left (the text attachment)
    [(messages, _media)] = backend.calls
    assert "hello" in messages[-1]["content"]
    assert "[Attached audio" not in messages[-1]["content"]
    # ... and the audio-specific rejection was not silently dropped
    assert len(events) == 1
    assert events[0].level is EventLevel.WARN
    assert "exceeds" in events[0].message


async def test_on_attachment_submission_orders_media_images_then_audio():
    orchestrator, backend, _sound_cues = _orchestrator()
    plan = AttachmentPlan(
        items=(
            _image_plan_item("a.png"),
            _audio_plan_item("memo.wav", duration_seconds=1.0),
            _image_plan_item("b.png"),
        )
    )

    await orchestrator.on_attachment_submission("look and listen", plan)

    [(_messages, media)] = backend.calls
    image_b64 = base64.b64encode(b"png-bytes").decode()
    assert media[:2] == [image_b64, image_b64]  # images first, upload order
    assert len(media) == 3  # then the one audio clip


def _persisting_orchestrator(tmp_path, chat_impl=None):
    store = JournalStore(tmp_path)
    recorder = JournalRecorder(store, enabled=True)
    repository = SessionFileRepository(
        store.root,
        config=FilesSettings(),
        session_is_visible=lambda sid: bool(store.read_session(sid).records),
    )
    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=chat_impl,
        journal_recorder=recorder,
        session_file_repository=repository,
        session_file_scope=lambda: resolve_session_file_scope(
            store, recorder.session_id
        ),
    )
    return orchestrator, backend, store, recorder


def _upload(filename: str, data: bytes = b"payload") -> AttachmentUpload:
    return AttachmentUpload(filename=filename, content_type="", data=data)


async def test_persistent_upload_is_written_and_storage_name_surfaced(tmp_path):
    orchestrator, backend, store, recorder = _persisting_orchestrator(tmp_path)

    result = await orchestrator.on_attachment_submission(
        "keep this", AttachmentPlan(items=()), [_upload("plan.md", b"note body")]
    )

    assert result.reason is AttachmentSubmissionReason.ACCEPTED
    [outcome] = result.persisted_files
    assert outcome.persisted
    assert outcome.storage_name.startswith("plan-")
    assert outcome.storage_name.endswith(".md")
    assert outcome.bytes == len(b"note body")
    # The file is a loose file in the current session directory.
    session_dir = store.root / recorder.session_id
    assert (session_dir / outcome.storage_name).read_bytes() == b"note body"
    # Its storage name reaches the model in the same turn.
    [(messages, _media)] = backend.calls
    assert outcome.storage_name in messages[-1]["content"]


async def test_persistent_upload_works_on_first_turn_of_a_new_session(tmp_path):
    # No session exists before this turn: the hook flushes the just-recorded
    # user event so the write is not refused as no-active-session.
    orchestrator, _backend, store, recorder = _persisting_orchestrator(tmp_path)
    assert recorder.session_id is None

    result = await orchestrator.on_attachment_submission(
        "", AttachmentPlan(items=()), [_upload("note.txt", b"x")]
    )

    [outcome] = result.persisted_files
    assert outcome.persisted
    assert (store.root / recorder.session_id / outcome.storage_name).exists()


async def test_persistent_upload_preserves_current_turn_image_media(tmp_path):
    orchestrator, backend, _store, _recorder = _persisting_orchestrator(tmp_path)
    plan = AttachmentPlan(items=(_image_plan_item("photo.png"),))

    result = await orchestrator.on_attachment_submission(
        "look", plan, [_upload("photo.png", b"png-bytes")]
    )

    # Persisted AND still delivered as this turn's transient image media.
    assert result.persisted_files[0].persisted
    [(_messages, media)] = backend.calls
    assert media == list(compose_turn_images(plan))


async def test_persistent_upload_reports_repository_rejection(tmp_path):
    # A traversal filename is rejected by the repository and never becomes a
    # storage path; no turn-aborting exception escapes.
    orchestrator, _backend, store, recorder = _persisting_orchestrator(tmp_path)

    result = await orchestrator.on_attachment_submission(
        "hi", AttachmentPlan(items=()), [_upload("../escape.md", b"x")]
    )

    [outcome] = result.persisted_files
    assert not outcome.persisted
    assert outcome.error is not None
    assert list((store.root / recorder.session_id).glob("*.md")) == []


async def test_persistent_upload_reported_unavailable_without_repository(tmp_path):
    # Journal recorder present but no session-file repository wired: the
    # submission still proceeds and each marked file is reported unavailable.
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=JournalRecorder(JournalStore(tmp_path), enabled=True)
    )

    result = await orchestrator.on_attachment_submission(
        "hi", AttachmentPlan(items=()), [_upload("note.md", b"x")]
    )

    [outcome] = result.persisted_files
    assert not outcome.persisted
    assert outcome.error == "session files unavailable"


async def test_on_attachment_submission_reports_source_and_input_metadata():
    bus = EventBus()
    turn_recorder = _TurnAcceptedRecorder(bus)
    request_recorder = _RequestRecorder(bus)
    orchestrator, _backend, _sound_cues = _orchestrator(
        bus=bus, clock=lambda: 1700000200.0
    )
    plan = AttachmentPlan(
        items=(
            _image_plan_item("photo.png"),
            _text_plan_item("notes.txt"),
            _audio_plan_item("memo.wav", duration_seconds=3.0),
        )
    )

    await orchestrator.on_attachment_submission("hi", plan)

    assert turn_recorder.events == [TurnAccepted(source=TurnSource.ATTACHMENT)]
    assert len(request_recorder.events) == 1
    _assert_model_request_started(
        request_recorder.events[0],
        timestamp=1700000200.0,
        inputs=(
            ModelRequestInput.ATTACHMENT_IMAGE,
            ModelRequestInput.ATTACHMENT_TEXT,
            ModelRequestInput.ATTACHMENT_AUDIO,
        ),
        audio_duration_seconds=3.0,
    )


async def test_on_attachment_submission_undecodable_audio_warns_and_continues():
    bus = EventBus()
    orchestrator, backend, _sound_cues = _orchestrator(bus=bus)
    events: list[SystemEvent] = []

    async def on_system_event(event: SystemEvent) -> None:
        events.append(event)

    bus.subscribe(SystemEvent, on_system_event)
    plan = AttachmentPlan(
        items=(
            _text_plan_item("notes.txt", "hello"),
            _undecodable_audio_plan_item("broken.wav"),
        )
    )

    await orchestrator.on_attachment_submission("", plan)

    # the turn still went through with what was left (the text attachment)
    [(messages, media)] = backend.calls
    assert media is None
    assert "hello" in messages[-1]["content"]
    assert "[Attached audio" not in messages[-1]["content"]
    # ... and the audio-specific failure was not silently dropped
    assert len(events) == 1
    assert events[0].level is EventLevel.WARN
    assert "broken.wav" in events[0].message


async def test_attachment_media_is_not_stored_in_conversation_history():
    orchestrator, _backend, _sound_cues = _orchestrator()
    plan = AttachmentPlan(
        items=(_image_plan_item("photo.png"), _audio_plan_item("memo.wav")),
    )

    await orchestrator.on_attachment_submission("describe these", plan)
    await orchestrator.on_response_token(ResponseToken(text="Done."))
    await orchestrator.on_response_complete(_complete_event())

    messages = orchestrator._history.as_messages()
    assert all("images" not in message for message in messages)
    recorded_texts = " ".join(str(message["content"]) for message in messages)
    assert base64.b64encode(b"png-bytes").decode() not in recorded_texts


async def test_attachment_submission_is_ignored_while_busy():
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    journal_recorder = _FakeJournalRecorder()
    orchestrator, backend, sound_cues = _orchestrator(
        chat_impl=slow_chat, journal_recorder=journal_recorder
    )
    first = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let the first call start and set _busy
    await asyncio.sleep(0)  # task-v1.7.0-2: chat() now runs one hop later

    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1)
    )
    plan = AttachmentPlan(items=(_text_plan_item("notes.txt"),))
    result = await orchestrator.on_attachment_submission("ignored while busy", plan)

    assert result.reason is AttachmentSubmissionReason.BUSY
    assert len(backend.calls) == 1  # the attachment submission was ignored
    assert sound_cues.played == ["thinking"]  # only the in-flight turn's cue
    assert journal_recorder.user_texts == []  # no user event was journaled

    still_busy.set()
    await first
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    # the pending screenshot from before the rejected submission survived
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"c", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls[-1][1]) == 2  # audio + the surviving screenshot


async def test_attachment_submission_rejects_plan_with_no_turn_content():
    orchestrator, backend, sound_cues = _orchestrator()
    plan = AttachmentPlan(
        items=(
            AttachmentPlanItem(
                filename="manual.pdf",
                attachment_class=None,
                accepted=False,
                rejection_reason="manual.pdf: unsupported file type.",
            ),
        )
    )

    result = await orchestrator.on_attachment_submission("", plan)

    assert result.reason is AttachmentSubmissionReason.NO_ACCEPTED_CONTENT
    assert backend.calls == []
    assert sound_cues.played == []


async def test_attachment_submission_backend_failure_plays_error_and_clears_busy():
    async def failing_chat() -> None:
        raise ValueError("boom")

    orchestrator, backend, sound_cues = _orchestrator(chat_impl=failing_chat)
    plan = AttachmentPlan(items=(_text_plan_item("notes.txt"),))

    await orchestrator.on_attachment_submission("hi", plan)

    assert sound_cues.played == ["thinking", "error"]

    # busy was cleared, so a subsequent submission is not ignored
    await orchestrator.on_attachment_submission("hi again", plan)
    assert len(backend.calls) == 2


async def test_attachment_submission_records_journal_with_attachment_source():
    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=journal_recorder
    )
    plan = AttachmentPlan(items=(_text_plan_item("notes.txt", "hello"),))

    await orchestrator.on_attachment_submission("check this", plan)

    assert journal_recorder.user_text_sources == ["attachment"]
    assert journal_recorder.user_texts == [compose_turn_text("check this", plan)]


async def test_on_response_token_plays_speaking_cue_only_once():
    orchestrator, _backend, sound_cues = _orchestrator()

    await orchestrator.on_response_token(ResponseToken(text="Привет"))
    await orchestrator.on_response_token(ResponseToken(text=", мир"))

    assert sound_cues.played.count("speaking") == 1


async def test_on_response_complete_records_history():
    orchestrator, _backend, _sound_cues = _orchestrator()

    await orchestrator.on_response_token(ResponseToken(text="Привет"))
    await orchestrator.on_response_token(ResponseToken(text=", мир"))
    await orchestrator.on_response_complete(_complete_event())

    messages = orchestrator._history.as_messages()
    assert messages[-2] == {"role": "user", "content": "[голосовое сообщение]"}
    assert messages[-1] == {"role": "assistant", "content": "Привет, мир"}


async def test_on_response_complete_records_plain_response_text_in_history():
    orchestrator, _backend, _sound_cues = _orchestrator()

    await orchestrator.on_response_token(ResponseToken(text="Ответ через API готов."))
    await orchestrator.on_response_complete(_complete_event())

    messages = orchestrator._history.as_messages()
    assert messages[-1] == {"role": "assistant", "content": "Ответ через API готов."}


async def test_journal_recorder_receives_turn_inputs_and_final_response_only():
    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=journal_recorder
    )

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"voice clip", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_token(ResponseToken(text="final "))
    await orchestrator.on_response_token(ResponseToken(text="answer"))
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()
    await orchestrator.on_clipboard(
        ClipboardSubmitted(text="clipboard text", truncated=False, is_empty=False)
    )

    assert journal_recorder.voice_wavs == [b"voice clip"]
    assert journal_recorder.user_texts == ["clipboard text"]
    assert journal_recorder.assistant_texts == ["final answer"]


async def test_journal_recorder_ignores_completion_without_accepted_user_turn():
    journal_recorder = _FakeJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=journal_recorder
    )

    await orchestrator.on_response_complete(_complete_event())

    assert journal_recorder.voice_wavs == []
    assert journal_recorder.user_texts == []
    assert journal_recorder.assistant_texts == []


async def test_fork_from_journal_session_seeds_history_and_records_provenance(
    tmp_path,
):
    store = JournalStore(tmp_path)
    source_session_id = "20260718-150000-ab12"
    source_end_timestamp = "2026-07-18T15:01:00+01:00"
    store.append(
        JournalEvent(
            session_id=source_session_id,
            timestamp="2026-07-18T15:00:00+01:00",
            source="dock",
            role="user",
            text="remember the relay",
            media=[],
            transcript=None,
        )
    )
    store.append(
        JournalEvent(
            session_id=source_session_id,
            timestamp=source_end_timestamp,
            source="assistant",
            role="assistant",
            text="The relay is stable.",
            media=[],
            transcript=None,
        )
    )
    source_log = tmp_path / source_session_id / "events.jsonl"
    source_bytes_before = source_log.read_bytes()
    history = ConversationHistory()
    recorder = JournalRecorder(
        store, clock=lambda: datetime.fromisoformat("2026-07-19T10:00:00+01:00")
    )
    orchestrator = Orchestrator(
        _FakeBackend(), history, _FakeSoundCues(), journal_recorder=recorder
    )

    result = await orchestrator.fork_from_journal_session(
        source_session_id=source_session_id,
        replay=store.read_session(source_session_id),
        source_end_timestamp=source_end_timestamp,
        seed_budget_chars=1000,
    )
    await recorder.wait_for_pending()

    assert result.accepted
    assert result.new_session_id is not None
    assert source_log.read_bytes() == source_bytes_before
    expected_provenance = main_module._fork_provenance_seed_line(source_end_timestamp)
    assert history.as_messages() == [
        {"role": "system", "content": expected_provenance},
        {"role": "user", "content": "remember the relay"},
        {"role": "assistant", "content": "The relay is stable."},
    ]
    fork_events = store.read_session(result.new_session_id).events
    assert len(fork_events) == 1
    assert fork_events[0].role == "system"
    assert fork_events[0].source == "fork"
    assert fork_events[0].text == expected_provenance
    assert fork_events[0].metadata == {
        "continued_from": source_session_id,
        "seed": {
            "dropped_turns": 0,
            "skipped_events": 0,
            "excluded_events": 0,
            "truncated": False,
        },
    }


async def test_fork_from_journal_session_rejects_busy_without_changing_history():
    history = ConversationHistory()
    history.add("user", "existing")
    orchestrator = Orchestrator(_FakeBackend(), history, _FakeSoundCues())
    orchestrator._busy = True

    result = await orchestrator.fork_from_journal_session(
        source_session_id="20260718-150000-ab12",
        replay=main_module.JournalReplay(
            records=[
                JournalEventRecord(
                    JournalEventRef("20260718-150000-ab12", 0),
                    JournalEvent(
                        session_id="20260718-150000-ab12",
                        timestamp="2026-07-18T15:00:00+01:00",
                        source="dock",
                        role="user",
                        text="new seed",
                        media=[],
                        transcript=None,
                    ),
                )
            ],
            corrupt_lines=0,
        ),
        source_end_timestamp="2026-07-18T15:00:00+01:00",
        seed_budget_chars=1000,
    )

    assert result.reason is ForkSessionReason.BUSY
    assert history.as_messages() == [{"role": "user", "content": "existing"}]


async def test_fork_from_journal_session_reports_oversize_turn():
    orchestrator = Orchestrator(_FakeBackend(), ConversationHistory(), _FakeSoundCues())

    result = await orchestrator.fork_from_journal_session(
        source_session_id="20260718-150000-ab12",
        replay=main_module.JournalReplay(
            records=[
                JournalEventRecord(
                    JournalEventRef("20260718-150000-ab12", 0),
                    JournalEvent(
                        session_id="20260718-150000-ab12",
                        timestamp="2026-07-18T15:00:00+01:00",
                        source="dock",
                        role="user",
                        text="too long",
                        media=[],
                        transcript=None,
                    ),
                )
            ],
            corrupt_lines=0,
        ),
        source_end_timestamp="2026-07-18T15:00:00+01:00",
        seed_budget_chars=3,
    )

    assert result.reason is ForkSessionReason.OVERSIZE_TURN
    assert result.oversize_turn_chars == len("too long")
    assert result.max_chars == 3


async def test_start_new_context_clears_history_and_records_blank_session(
    tmp_path,
):
    prompts = ["base v1", "base v2"]

    def next_prompt(_solo: bool = False) -> str:
        return prompts.pop(0)

    store = JournalStore(tmp_path)
    recorder = JournalRecorder(
        store, clock=lambda: datetime.fromisoformat("2026-07-19T10:00:00+01:00")
    )
    history = ConversationHistory()
    history.add("user", "old context")
    backend = _FakeBackend()
    orchestrator = Orchestrator(
        backend,
        history,
        _FakeSoundCues(),
        journal_recorder=recorder,
        system_prompt_provider=next_prompt,
    )

    result = await orchestrator.start_new_context()

    assert result.accepted
    assert result.session_id == recorder.session_id
    assert history.as_messages() == []
    replay = store.read_session(result.session_id)
    [event] = replay.events
    assert event.role == "system"
    assert event.source == "context"
    assert event.text == main_module._new_context_provenance_line()
    assert event.metadata == {"kind": "new_context"}

    await orchestrator.submit_text_input("after reset")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "base v2"}


async def test_start_new_context_rejects_busy_without_changing_history():
    history = ConversationHistory()
    history.add("user", "existing")
    orchestrator = Orchestrator(_FakeBackend(), history, _FakeSoundCues())
    orchestrator._busy = True

    result = await orchestrator.start_new_context()

    assert result.reason is NewContextReason.BUSY
    assert history.as_messages() == [{"role": "user", "content": "existing"}]


async def test_system_prompt_provider_is_sampled_on_session_start_only():
    prompts = ["base v1", "base v2", "base v3"]

    def next_prompt(_solo: bool = False) -> str:
        return prompts.pop(0)

    backend = _FakeBackend()
    history = ConversationHistory()
    orchestrator = Orchestrator(
        backend,
        history,
        _FakeSoundCues(),
        system_prompt_provider=next_prompt,
    )

    await orchestrator.submit_text_input("first")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "base v1"}
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    await orchestrator.submit_text_input("second while same session")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "base v1"}
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    orchestrator.clear()
    await orchestrator.submit_text_input("after reset")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "base v2"}


async def test_system_prompt_provider_receives_solo_state_at_session_start():
    def prompt_for(solo: bool) -> str:
        return "solo prompt" if solo else "normal prompt"

    bus = EventBus()
    solo = SoloSessionState(bus, enabled=False)
    backend = _FakeBackend()
    orchestrator = Orchestrator(
        backend,
        ConversationHistory(),
        _FakeSoundCues(),
        system_prompt_provider=prompt_for,
        solo_session_state=solo,
    )

    await orchestrator.submit_text_input("first")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "normal prompt"}
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    # Toggling solo mid-conversation must not retroactively change the
    # prompt already baked into this running session - only the next
    # session-start moment (clear()) re-samples it.
    await solo.set_enabled(True)
    await orchestrator.submit_text_input("still same session")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "normal prompt"}
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    orchestrator.clear()
    await orchestrator.submit_text_input("after new context, solo still on")
    assert backend.calls[-1][0][0] == {"role": "system", "content": "solo prompt"}


async def test_busy_utterance_is_ignored_until_previous_turn_completes():
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    orchestrator, backend, _sound_cues = _orchestrator(chat_impl=slow_chat)

    first = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let the first call start and set _busy
    await asyncio.sleep(0)  # task-v1.7.0-2: chat() now runs one hop later
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )

    assert len(backend.calls) == 1  # second utterance was ignored while busy

    still_busy.set()
    await first


async def test_ignored_utterance_while_busy_does_not_consume_pending_screenshot():
    """Regression test for a real bug: on_utterance() used to consume
    _pending_screenshot_b64 before _start_turn()'s busy-guard could reject
    the turn, permanently losing a screenshot meant for the next turn if
    the utterance that happened to arrive while busy already had one
    pending. The busy-check must happen before any screenshot consumption."""
    still_busy = asyncio.Event()

    async def slow_chat() -> None:
        await still_busy.wait()

    orchestrator, backend, _sound_cues = _orchestrator(chat_impl=slow_chat)

    first = asyncio.create_task(
        orchestrator.on_utterance(
            UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
        )
    )
    await asyncio.sleep(0)  # let the first call start and set _busy

    await orchestrator.on_screenshot(
        ScreenshotCaptured(png_bytes=b"png", mode="full", width=1, height=1)
    )
    # ignored while busy - the screenshot above must survive this
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )

    still_busy.set()
    await first
    await orchestrator.on_response_complete(_complete_event())
    await orchestrator.finish_turn()

    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"c", start_seconds=0, end_seconds=1)
    )

    assert len(backend.calls) == 2  # "b" was ignored; "a" and "c" went through
    assert (
        len(backend.calls[-1][1]) == 2
    )  # "c" still got the screenshot from before "b"


async def test_finish_turn_cooldown_rejects_a_self_heard_echo():
    """Regression test for a real bug: after Jarvis stops speaking,
    audio_in.py can still be sitting on a self-heard "utterance" (its own
    voice picked up by the mic - no echo cancellation in v1.0) for up to
    request_end_pause_seconds before it publishes it. If busy had already
    cleared by then, that echo was accepted and answered as if it were a
    genuine new question - Jarvis talking to itself. finish_turn()'s
    cooldown keeps busy True for that whole window."""
    orchestrator, backend, _sound_cues = _orchestrator()
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"a", start_seconds=0, end_seconds=1)
    )
    await orchestrator.on_response_complete(_complete_event())

    finish_task = asyncio.create_task(orchestrator.finish_turn(cooldown_seconds=0.05))
    await asyncio.sleep(0)  # let finish_turn() start its cooldown sleep

    # still within the cooldown: a self-heard echo must be rejected, same as mid-turn
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"echo", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls) == 1

    await finish_task  # cooldown elapses, busy clears

    # a genuine new utterance after the cooldown is accepted
    await orchestrator.on_utterance(
        UtteranceChunk(wav_bytes=b"b", start_seconds=0, end_seconds=1)
    )
    assert len(backend.calls) == 2


async def test_finish_turn_waits_for_pending_journal_writes():
    """Regression (task-v1.7.0-2 review): JournalRecorder schedules its
    actual disk write as a background task rather than blocking on it
    (JournalRecorder._schedule()), so finish_turn() returning - and the
    caller announcing the turn is over - used to race ahead of it. Masked
    for a normal turn's multi-second duration (generation + TTS gives the
    write plenty of time), but a turn ending very quickly - an interrupt
    during the "thinking" phase, confirmed live - could return before the
    write, and the live Journal panel's update, had happened at all.
    finish_turn() is the one place both a normal completion and an
    interrupt converge to end a turn, so the fix belongs here rather than
    duplicated in each caller."""
    write_finished = asyncio.Event()

    class _SlowJournalRecorder:
        def __init__(self) -> None:
            self.wait_calls = 0

        async def wait_for_pending(self) -> None:
            self.wait_calls += 1
            await write_finished.wait()

    journal_recorder = _SlowJournalRecorder()
    orchestrator, _backend, _sound_cues = _orchestrator(
        journal_recorder=journal_recorder
    )
    orchestrator._busy = True

    finish_task = asyncio.create_task(orchestrator.finish_turn())
    await asyncio.sleep(0)

    assert journal_recorder.wait_calls == 1
    assert orchestrator.is_busy is True  # finish_turn() has not returned yet

    write_finished.set()
    await finish_task

    assert orchestrator.is_busy is False
