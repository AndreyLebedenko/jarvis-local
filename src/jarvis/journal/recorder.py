from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from jarvis.core.bus import EventBus
from jarvis.journal.events import (
    JournalEvent,
    JournalEventAppended,
    JSONValue,
    new_session_id,
)
from jarvis.journal.fork import ForkSeedDropReport
from jarvis.journal.store import JournalStore


class JournalRecorder:
    def __init__(
        self,
        store: JournalStore,
        *,
        enabled: bool = True,
        bus: EventBus | None = None,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._enabled = enabled
        self._bus = bus
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._logger = logger or logging.getLogger(__name__)
        self._session_id: str | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._tail: asyncio.Task[None] | None = None
        self._media_counter = 0

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def record_voice_user(
        self, wav_bytes: bytes, *, screenshot_png_bytes: bytes | None = None
    ) -> None:
        if not self._enabled:
            return
        timestamp = self._now()
        session_id = self._session(timestamp)
        media_name = self._next_media_name(timestamp, ".wav")
        screenshot_name = (
            self._next_media_name(timestamp, ".png")
            if screenshot_png_bytes is not None
            else None
        )
        self._schedule(
            self._write_voice_user(
                session_id=session_id,
                timestamp=timestamp,
                media_name=media_name,
                wav_bytes=bytes(wav_bytes),
                screenshot_name=screenshot_name,
                screenshot_png_bytes=(
                    bytes(screenshot_png_bytes)
                    if screenshot_png_bytes is not None
                    else None
                ),
            )
        )

    async def record_text_user(self, text: str, *, source: str = "text") -> None:
        if not self._enabled:
            return
        timestamp = self._now()
        session_id = self._session(timestamp)
        self._schedule(
            self._append_event(
                session_id=session_id,
                timestamp=timestamp,
                source=source,
                role="user",
                text=text,
                media=(),
            )
        )

    async def record_assistant(self, text: str) -> None:
        if not self._enabled:
            return
        timestamp = self._now()
        session_id = self._session(timestamp)
        self._schedule(
            self._append_event(
                session_id=session_id,
                timestamp=timestamp,
                source="assistant",
                role="assistant",
                text=text,
                media=(),
            )
        )

    async def start_fork_session(
        self,
        *,
        source_session_id: str,
        provenance_text: str,
        seed_drop_report: ForkSeedDropReport,
    ) -> str | None:
        if not self._enabled:
            return None
        timestamp = self._now()
        self._session_id = new_session_id(timestamp)
        self._media_counter = 0
        await self._append_event(
            session_id=self._session_id,
            timestamp=timestamp,
            source="fork",
            role="system",
            text=provenance_text,
            media=(),
            metadata={
                "continued_from": source_session_id,
                "seed": {
                    "dropped_turns": seed_drop_report.dropped_turns,
                    "skipped_events": seed_drop_report.skipped_events,
                    "truncated": seed_drop_report.truncated,
                },
            },
        )
        return self._session_id

    async def start_blank_session(self, *, provenance_text: str) -> str | None:
        if not self._enabled:
            return None
        timestamp = self._now()
        self._session_id = new_session_id(timestamp)
        self._media_counter = 0
        await self._append_event(
            session_id=self._session_id,
            timestamp=timestamp,
            source="context",
            role="system",
            text=provenance_text,
            media=(),
            metadata={"kind": "new_context"},
        )
        return self._session_id

    async def wait_for_pending(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    def _now(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("journal recorder clock must return an aware datetime")
        return timestamp

    def _session(self, timestamp: datetime) -> str:
        if self._session_id is None:
            self._session_id = new_session_id(timestamp)
        return self._session_id

    def _next_media_name(self, timestamp: datetime, suffix: str) -> str:
        self._media_counter += 1
        stamp = timestamp.strftime("%Y%m%d-%H%M%S")
        return f"utterance-{stamp}-{self._media_counter:04d}{suffix}"

    def _schedule(self, coroutine: Awaitable[None]) -> None:
        previous = self._tail

        async def run_after_previous() -> None:
            if previous is not None:
                await asyncio.gather(previous, return_exceptions=True)
            await coroutine

        task = asyncio.create_task(run_after_previous())
        self._tail = task
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except Exception:
            self._logger.warning("Journal write failed", exc_info=True)

    async def _write_voice_user(
        self,
        *,
        session_id: str,
        timestamp: datetime,
        media_name: str,
        wav_bytes: bytes,
        screenshot_name: str | None,
        screenshot_png_bytes: bytes | None,
    ) -> None:
        await asyncio.to_thread(
            self._store.write_media,
            session_id=session_id,
            name=media_name,
            contents=wav_bytes,
        )
        media = [media_name]
        if screenshot_name is not None and screenshot_png_bytes is not None:
            await asyncio.to_thread(
                self._store.write_media,
                session_id=session_id,
                name=screenshot_name,
                contents=screenshot_png_bytes,
            )
            media.append(screenshot_name)
        await self._append_event(
            session_id=session_id,
            timestamp=timestamp,
            source="voice",
            role="user",
            text="",
            media=tuple(media),
        )

    async def _append_event(
        self,
        *,
        session_id: str,
        timestamp: datetime,
        source: str,
        role: str,
        text: str,
        media: tuple[str, ...],
        metadata: dict[str, JSONValue] | None = None,
    ) -> None:
        event = JournalEvent(
            session_id=session_id,
            timestamp=timestamp.isoformat(),
            source=source,
            role=role,
            text=text,
            media=media,
            transcript=None,
            metadata=metadata or {},
        )
        await asyncio.to_thread(self._store.append, event)
        if self._bus is not None:
            await self._bus.publish(JournalEventAppended, JournalEventAppended(event))
