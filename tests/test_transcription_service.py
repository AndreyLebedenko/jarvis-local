from __future__ import annotations

import asyncio
import base64
import logging
import threading
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path

import pytest

from jarvis.journal.events import JournalEvent, JournalEventRef, JSONValue
from jarvis.journal.store import JournalStore
from jarvis.journal.transcript import (
    TRANSCRIPT_MAX_TEXT_LENGTH,
    TranscriptOverlayRepository,
    TranscriptReadStatus,
    TranscriptSource,
    TranscriptUpsertResult,
    TranscriptUpsertStatus,
)
from jarvis.journal.transcription import (
    DEFAULT_TRANSCRIPTION_INSTRUCTION,
    JournalStoreTranscriptionSource,
    OllamaTranscriptionBackend,
    TranscriptionBackendError,
    TranscriptionBackendMetadata,
    TranscriptionMessage,
    TranscriptionOutcome,
    TranscriptionResult,
    TranscriptionRun,
    TranscriptionService,
    build_transcription_messages,
    build_transcription_request,
    select_audio_media,
)

_SESSION = "20260801-120000-ab12"
_TIMESTAMP = "2026-08-01T12:00:00+00:00"
_META = TranscriptionBackendMetadata(
    model="gemma4:12b-it-qat", reasoning="off", options=(("num_ctx", "65536"),)
)


def _event(*media: str, role: str = "user", source: str = "voice") -> JournalEvent:
    return JournalEvent(
        session_id=_SESSION,
        timestamp=_TIMESTAMP,
        source=source,
        role=role,
        text="",
        media=tuple(media),
        transcript=None,
        metadata={},
    )


def _write_voice_event(
    store: JournalStore,
    *,
    wav_bytes: bytes = b"RIFFfakewav",
    with_screenshot: bool = False,
    position_suffix: str = "0001",
) -> JournalEventRef:
    wav_name = f"utterance-{position_suffix}.wav"
    store.write_media(_SESSION, wav_name, wav_bytes)
    media = [wav_name]
    if with_screenshot:
        png_name = f"shot-{position_suffix}.png"
        store.write_media(_SESSION, png_name, b"fakepng")
        media.append(png_name)
    return store.append(_event(*media))


class _FakeBackend:
    def __init__(
        self,
        text: str = "привет мир",
        error: Exception | None = None,
        metadata: TranscriptionBackendMetadata = _META,
    ) -> None:
        self.text = text
        self.error = error
        self.metadata = metadata
        self.calls: list[tuple[tuple[TranscriptionMessage, ...], tuple[str, ...]]] = []

    async def run_transcription(
        self,
        messages: Sequence[TranscriptionMessage],
        images_b64: Sequence[str],
    ) -> TranscriptionRun:
        self.calls.append((tuple(messages), tuple(images_b64)))
        if self.error is not None:
            raise self.error
        return TranscriptionRun(self.text, self.metadata)


def _service(
    store: JournalStore,
    repo: TranscriptOverlayRepository,
    backend: _FakeBackend,
    *,
    max_concurrency: int = 1,
) -> TranscriptionService:
    return TranscriptionService(
        JournalStoreTranscriptionSource(store),
        backend,
        repo,
        max_concurrency=max_concurrency,
    )


def _repo(tmp_path: Path) -> TranscriptOverlayRepository:
    return TranscriptOverlayRepository(tmp_path / "derived", _AllExist())


class _AllExist:
    def event_exists(self, reference: JournalEventRef) -> bool:
        return True


class TestRequestConstruction:
    def test_build_request_encodes_media_and_records_source(self) -> None:
        ref = JournalEventRef(_SESSION, 3)
        request = build_transcription_request(
            ref,
            instruction="расшифруй",
            audio_media=["a.wav", "b.wav"],
            media_bytes=[b"\x00\x01", b"\xff"],
        )
        assert request.reference == ref
        assert request.messages == (
            TranscriptionMessage(role="user", content="расшифруй"),
        )
        assert request.images_b64 == (
            base64.b64encode(b"\x00\x01").decode("ascii"),
            base64.b64encode(b"\xff").decode("ascii"),
        )
        assert request.source_media == ("a.wav", "b.wav")

    def test_messages_are_a_single_user_turn(self) -> None:
        assert build_transcription_messages("say") == (
            TranscriptionMessage(role="user", content="say"),
        )

    def test_default_instruction_is_nonempty(self) -> None:
        assert DEFAULT_TRANSCRIPTION_INSTRUCTION.strip()


class TestSelectAudioMedia:
    def test_selects_wav_and_ignores_screenshot(self) -> None:
        assert select_audio_media(_event("u.wav", "s.png")) == ("u.wav",)

    def test_is_case_insensitive_on_extension(self) -> None:
        assert select_audio_media(_event("U.WAV")) == ("U.WAV",)

    def test_empty_when_no_audio(self) -> None:
        assert select_audio_media(_event("s.png")) == ()
        assert select_audio_media(_event()) == ()


class TestTranscribeHappyPath:
    async def test_writes_generated_overlay_and_reports_success(
        self, tmp_path: Path
    ) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend(text="  привет мир  ")
        ref = _write_voice_event(store, with_screenshot=True)
        service = _service(store, repo, backend)

        result = await service.transcribe_event(ref)

        assert result.outcome is TranscriptionOutcome.TRANSCRIBED
        assert result.transcript == "привет мир"
        assert result.source_media == ("utterance-0001.wav",)

        read = repo.read_transcript(ref)
        assert read.found
        assert read.overlay is not None
        assert read.overlay.text == "привет мир"
        assert read.overlay.source is TranscriptSource.GENERATED

    async def test_records_actual_backend_metadata(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend(
            metadata=TranscriptionBackendMetadata(
                model="real-model", reasoning="off", options=(("num_ctx", "65536"),)
            )
        )
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)

        result = await service.transcribe_event(ref)

        assert result.metadata is not None
        assert result.metadata.model == "real-model"
        assert result.metadata.reasoning == "off"
        assert result.metadata.options == (("num_ctx", "65536"),)

    async def test_backend_receives_audio_and_instruction(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend()
        ref = _write_voice_event(store, wav_bytes=b"RIFFdata", with_screenshot=True)
        service = _service(store, repo, backend)

        await service.transcribe_event(ref)

        (messages, images) = backend.calls[0]
        assert images == (base64.b64encode(b"RIFFdata").decode("ascii"),)
        assert messages == (
            TranscriptionMessage(
                role="user", content=DEFAULT_TRANSCRIPTION_INSTRUCTION
            ),
        )

    async def test_reprocessing_overwrites_the_overlay(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend(text="first")
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)

        await service.transcribe_event(ref)
        backend.text = "second"
        result = await service.transcribe_event(ref)

        assert result.transcript == "second"
        assert repo.read_transcript(ref).overlay.text == "second"


class TestRefusals:
    async def test_unknown_event_is_refused(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend()
        service = _service(store, repo, backend)

        result = await service.transcribe_event(JournalEventRef(_SESSION, 7))

        assert result.outcome is TranscriptionOutcome.UNKNOWN_EVENT
        assert result.metadata is None
        assert backend.calls == []
        assert (
            repo.read_transcript(JournalEventRef(_SESSION, 7)).status
            is TranscriptReadStatus.NOT_FOUND
        )

    async def test_event_without_audio_is_refused(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend()
        store.write_media(_SESSION, "shot.png", b"png")
        ref = store.append(_event("shot.png"))
        service = _service(store, repo, backend)

        result = await service.transcribe_event(ref)

        assert result.outcome is TranscriptionOutcome.NO_AUDIO_MEDIA
        assert backend.calls == []
        assert repo.read_transcript(ref).status is TranscriptReadStatus.NOT_FOUND

    async def test_text_turn_is_refused(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend()
        ref = store.append(
            JournalEvent(
                session_id=_SESSION,
                timestamp=_TIMESTAMP,
                source="text",
                role="user",
                text="hello",
                media=(),
                transcript=None,
                metadata={},
            )
        )
        service = _service(store, repo, backend)

        result = await service.transcribe_event(ref)

        assert result.outcome is TranscriptionOutcome.NO_AUDIO_MEDIA
        assert backend.calls == []

    async def test_missing_media_file_is_refused(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend()
        # Event references a wav that was never written to disk.
        ref = store.append(_event("utterance-gone.wav"))
        service = _service(store, repo, backend)

        result = await service.transcribe_event(ref)

        assert result.outcome is TranscriptionOutcome.MEDIA_UNREADABLE
        assert backend.calls == []
        assert repo.read_transcript(ref).status is TranscriptReadStatus.NOT_FOUND

    async def test_empty_transcript_is_not_written(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend(text="   \n  ")
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)

        result = await service.transcribe_event(ref)

        assert result.outcome is TranscriptionOutcome.EMPTY_TRANSCRIPT
        assert result.metadata is not None
        assert repo.read_transcript(ref).status is TranscriptReadStatus.NOT_FOUND

    async def test_over_limit_transcript_is_rejected(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend(text="x" * (TRANSCRIPT_MAX_TEXT_LENGTH + 1))
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)

        result = await service.transcribe_event(ref)

        assert result.outcome is TranscriptionOutcome.TRANSCRIPT_REJECTED
        assert result.detail == "text_too_long"
        assert repo.read_transcript(ref).status is TranscriptReadStatus.NOT_FOUND

    async def test_backend_failure_is_auditable_and_unwritten(
        self, tmp_path: Path
    ) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend(error=RuntimeError("ollama down"))
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)

        result = await service.transcribe_event(ref)

        assert result.outcome is TranscriptionOutcome.BACKEND_FAILED
        assert result.detail == "ollama down"
        assert result.metadata is None
        assert repo.read_transcript(ref).status is TranscriptReadStatus.NOT_FOUND


class TestConcurrency:
    async def test_concurrency_limit_serializes_backend_calls(
        self, tmp_path: Path
    ) -> None:
        peak = await self._run_with_limit(tmp_path, max_concurrency=1)
        assert peak == 1

    async def test_higher_limit_allows_overlap(self, tmp_path: Path) -> None:
        peak = await self._run_with_limit(tmp_path, max_concurrency=2)
        assert peak == 2

    async def _run_with_limit(self, tmp_path: Path, *, max_concurrency: int) -> int:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)

        class _Tracking:
            def __init__(self) -> None:
                self.active = 0
                self.peak = 0

            async def run_transcription(
                self,
                messages: Sequence[TranscriptionMessage],
                images_b64: Sequence[str],
            ) -> TranscriptionRun:
                self.active += 1
                self.peak = max(self.peak, self.active)
                await asyncio.sleep(0.02)
                self.active -= 1
                return TranscriptionRun("text", _META)

        backend = _Tracking()
        ref_a = _write_voice_event(store, position_suffix="0001")
        ref_b = _write_voice_event(store, position_suffix="0002")
        service = TranscriptionService(
            JournalStoreTranscriptionSource(store),
            backend,
            repo,
            max_concurrency=max_concurrency,
        )
        await asyncio.gather(
            service.transcribe_event(ref_a),
            service.transcribe_event(ref_b),
        )
        return backend.peak

    async def test_same_reference_joins_one_job(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        release = asyncio.Event()

        class _Counting:
            def __init__(self) -> None:
                self.calls = 0

            async def run_transcription(
                self,
                messages: Sequence[TranscriptionMessage],
                images_b64: Sequence[str],
            ) -> TranscriptionRun:
                self.calls += 1
                await release.wait()
                return TranscriptionRun("text", _META)

        backend = _Counting()
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)

        first = asyncio.create_task(service.transcribe_event(ref))
        second = asyncio.create_task(service.transcribe_event(ref))
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(first, second)

        assert backend.calls == 1
        assert all(r.outcome is TranscriptionOutcome.TRANSCRIBED for r in results)

    def test_rejects_zero_concurrency(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        with pytest.raises(ValueError):
            _service(store, repo, _FakeBackend(), max_concurrency=0)


class _BlockingBackend:
    """Backend that parks in the model call until released."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_transcription(
        self,
        messages: Sequence[TranscriptionMessage],
        images_b64: Sequence[str],
    ) -> TranscriptionRun:
        self.started.set()
        await self.release.wait()
        return TranscriptionRun("never", _META)


class _BlockingWriter:
    """Transcript writer that parks inside the SQLite write until released.

    The write runs in a worker thread (via `asyncio.to_thread`), so `entered`
    and `allow` are `threading.Event`s the test drives across that boundary.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.allow = threading.Event()
        self.writes = 0

    def upsert_transcript(
        self,
        reference: JournalEventRef,
        text: str,
        source: TranscriptSource,
    ) -> TranscriptUpsertResult:
        self.writes += 1
        self.entered.set()
        self.allow.wait(timeout=5)
        return TranscriptUpsertResult(TranscriptUpsertStatus.ACCEPTED)


async def _wait_flag(flag: threading.Event) -> None:
    for _ in range(500):
        if flag.is_set():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("flag was not set in time")


class TestCancellation:
    async def test_cancel_all_stops_job_without_writing(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _BlockingBackend()
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)
        task = asyncio.create_task(service.transcribe_event(ref))
        await asyncio.wait_for(backend.started.wait(), timeout=1)

        assert service.active_references() == (ref,)
        service.cancel_all()
        result = await asyncio.wait_for(task, timeout=1)

        assert result.outcome is TranscriptionOutcome.CANCELLED
        assert repo.read_transcript(ref).status is TranscriptReadStatus.NOT_FOUND
        assert service.active_references() == ()

    async def test_cancel_by_reference_targets_one_job(self, tmp_path: Path) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _BlockingBackend()
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)
        task = asyncio.create_task(service.transcribe_event(ref))
        await asyncio.wait_for(backend.started.wait(), timeout=1)

        assert service.cancel(JournalEventRef(_SESSION, 999)) is False
        assert service.cancel(ref) is True
        result = await asyncio.wait_for(task, timeout=1)
        assert result.outcome is TranscriptionOutcome.CANCELLED

    async def test_joined_waiter_cancellation_leaves_shared_job(
        self, tmp_path: Path
    ) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _BlockingBackend()
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)

        owner = asyncio.create_task(service.transcribe_event(ref))
        await asyncio.wait_for(backend.started.wait(), timeout=1)
        waiter = asyncio.create_task(service.transcribe_event(ref))
        await asyncio.sleep(0)

        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        # The owner's job must survive the joined waiter's cancellation.
        backend.release.set()
        result = await asyncio.wait_for(owner, timeout=1)
        assert result.outcome is TranscriptionOutcome.TRANSCRIBED
        assert repo.read_transcript(ref).found

    async def test_cancellation_during_write_reports_the_write(
        self, tmp_path: Path
    ) -> None:
        store = JournalStore(tmp_path / "journal")
        backend = _FakeBackend(text="привет")
        writer = _BlockingWriter()
        ref = _write_voice_event(store)
        service = TranscriptionService(
            JournalStoreTranscriptionSource(store), backend, writer
        )
        task = asyncio.create_task(service.transcribe_event(ref))
        await _wait_flag(writer.entered)

        # Cancel while the SQLite write is already running in its worker thread.
        service.cancel_all()
        await asyncio.sleep(0)
        writer.allow.set()

        result = await asyncio.wait_for(task, timeout=2)
        # The write committed, so the outcome must reflect it - never a
        # CANCELLED result paired with a completed overlay write.
        assert result.outcome is TranscriptionOutcome.TRANSCRIBED
        assert writer.writes == 1

    async def test_owner_cancel_during_write_keeps_job_joinable(
        self, tmp_path: Path
    ) -> None:
        store = JournalStore(tmp_path / "journal")
        backend = _FakeBackend(text="привет")
        writer = _BlockingWriter()
        ref = _write_voice_event(store)
        service = TranscriptionService(
            JournalStoreTranscriptionSource(store), backend, writer
        )

        owner = asyncio.create_task(service.transcribe_event(ref))
        await _wait_flag(writer.entered)

        # Externally cancel the owning caller while the overlay write is still
        # committing. The shared job must remain tracked, not be dropped.
        owner.cancel()
        await asyncio.sleep(0)
        assert service.active_references() == (ref,)

        # A fresh request for the same reference must join the surviving job
        # rather than start a second transcription/write of the same event.
        joiner = asyncio.create_task(service.transcribe_event(ref))
        await asyncio.sleep(0)
        writer.allow.set()

        with pytest.raises(asyncio.CancelledError):
            await owner
        result = await asyncio.wait_for(joiner, timeout=2)

        assert result.outcome is TranscriptionOutcome.TRANSCRIBED
        assert len(backend.calls) == 1
        assert writer.writes == 1
        assert service.active_references() == ()


class TestOllamaBackendAdapter:
    async def test_concatenates_content_ignores_thinking_and_reads_metadata(
        self,
    ) -> None:
        chunks: list[Mapping[str, JSONValue]] = [
            {"message": {"thinking": "reasoning..."}},
            {"message": {"content": "прив"}},
            {"message": {"content": "ет"}},
            {"done": True, "message": {"content": ""}},
        ]

        class _Chat:
            def __init__(self) -> None:
                self.built: list[Sequence[Mapping[str, object]]] = []

            def build_payload(
                self,
                messages: Sequence[Mapping[str, object]],
                images_b64: Sequence[str] | None = None,
            ) -> Mapping[str, JSONValue]:
                self.built.append(list(messages))
                return {
                    "model": "gemma4:12b-it-qat",
                    "think": False,
                    "options": {"num_ctx": 65536, "kv_cache_type": "q8_0"},
                }

            async def iter_chat(
                self,
                messages: Sequence[Mapping[str, object]],
                images_b64: Sequence[str] | None = None,
            ) -> AsyncIterator[Mapping[str, JSONValue]]:
                for chunk in chunks:
                    yield chunk

        chat = _Chat()
        adapter = OllamaTranscriptionBackend(chat)
        run = await adapter.run_transcription(
            build_transcription_messages("say"), ["b64"]
        )

        assert run.text == "привет"
        assert run.metadata.model == "gemma4:12b-it-qat"
        assert run.metadata.reasoning == "off"
        assert run.metadata.options == (
            ("kv_cache_type", '"q8_0"'),
            ("num_ctx", "65536"),
        )
        assert chat.built[0] == [{"role": "user", "content": "say"}]

    async def test_stream_failure_carries_prepared_metadata(self) -> None:
        class _Chat:
            def build_payload(
                self,
                messages: Sequence[Mapping[str, object]],
                images_b64: Sequence[str] | None = None,
            ) -> Mapping[str, JSONValue]:
                return {
                    "model": "gemma4:12b-it-qat",
                    "think": False,
                    "options": {"num_ctx": 65536},
                }

            async def iter_chat(
                self,
                messages: Sequence[Mapping[str, object]],
                images_b64: Sequence[str] | None = None,
            ) -> AsyncIterator[Mapping[str, JSONValue]]:
                yield {"message": {"content": "partial"}}
                raise RuntimeError("stream died")

        adapter = OllamaTranscriptionBackend(_Chat())
        with pytest.raises(TranscriptionBackendError) as excinfo:
            await adapter.run_transcription(
                build_transcription_messages("say"), ["b64"]
            )
        assert "stream died" in str(excinfo.value)
        assert excinfo.value.metadata is not None
        assert excinfo.value.metadata.model == "gemma4:12b-it-qat"
        assert excinfo.value.metadata.options == (("num_ctx", "65536"),)


class TestAudit:
    async def test_backend_failure_preserves_prepared_metadata(
        self, tmp_path: Path
    ) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        metadata = TranscriptionBackendMetadata(
            model="real-model", reasoning="off", options=(("num_ctx", "65536"),)
        )
        backend = _FakeBackend(
            error=TranscriptionBackendError("stream died", metadata=metadata)
        )
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)

        result = await service.transcribe_event(ref)

        assert result.outcome is TranscriptionOutcome.BACKEND_FAILED
        assert result.detail == "stream died"
        assert result.metadata == metadata
        assert repo.read_transcript(ref).status is TranscriptReadStatus.NOT_FOUND

    async def test_log_records_reasoning_and_options(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        store = JournalStore(tmp_path / "journal")
        repo = _repo(tmp_path)
        backend = _FakeBackend()
        ref = _write_voice_event(store)
        service = _service(store, repo, backend)

        with caplog.at_level(logging.INFO, logger="jarvis.journal.transcription"):
            await service.transcribe_event(ref)

        logged = "\n".join(caplog.messages)
        assert "reasoning=off" in logged
        assert "options=num_ctx=65536" in logged


def test_result_transcribed_flag() -> None:
    ok = TranscriptionResult(
        JournalEventRef(_SESSION, 0), TranscriptionOutcome.TRANSCRIBED
    )
    fail = TranscriptionResult(
        JournalEventRef(_SESSION, 0), TranscriptionOutcome.BACKEND_FAILED
    )
    assert ok.transcribed
    assert not fail.transcribed
