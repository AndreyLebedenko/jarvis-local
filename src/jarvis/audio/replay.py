"""On-demand replay of a past assistant reply (story-v1.8.2, task 1).

Re-synthesizes stored reply text through the TTS engine when the user asks
to hear it again - no audio is stored. The playback path is a sibling of
TtsOutput, not a reuse of its token-stream entry points: TtsOutput.cancel()
resets per-turn OrderedPlayback/buffer state for a live streaming turn, and
routing replay through that would entangle replay with turn semantics. What
they deliberately share is the process-wide playback_lock (so replay can
never physically overlap live speech or a sound cue on the output device)
and the TtsMuteState (a global TTS-off must silence replay too).

Whether a live turn is currently speaking is not decided here - it is the
Orchestrator's is_busy, checked by the app-level caller. This class only
guards against a second concurrent replay of its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
from collections.abc import Awaitable, Callable
from enum import Enum

import sounddevice as sd
import soundfile as sf

from jarvis.audio.tts import (
    SpeechUnitBuffer,
    TtsEngine,
    _routes_share_one_engine,
)
from jarvis.audio.tts_mute import TtsMuteState
from jarvis.core.config import TtsSettings
from jarvis.journal.events import JournalEventRef
from jarvis.journal.store import JournalStore

logger = logging.getLogger(__name__)


class ReplayOutcome(Enum):
    STARTED = "started"
    DISABLED = "disabled"
    BUSY = "busy"
    EMPTY = "empty"


def reply_speech_text(store: JournalStore, reference: JournalEventRef) -> str | None:
    """The single 'text to speak for this turn' accessor (story-v1.8.2
    forward seam): returns a past assistant reply's stored text for an
    arbitrary turn, or None when the reference is not an assistant reply or
    its session does not exist. v1.9.0's mode-3 spoken derivative will later
    retarget this accessor without touching the replay/playback path."""
    replay = store.read_session(reference.session_id)
    for record in replay.records:
        if record.reference == reference:
            if record.event.role != "assistant":
                return None
            return record.event.text
    return None


class ReplayPlayer:
    def __init__(
        self,
        settings: TtsSettings,
        engine: TtsEngine,
        play: Callable[[bytes], Awaitable[None]] | None = None,
        playback_lock: asyncio.Lock | None = None,
        mute_state: TtsMuteState | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._playback_lock = playback_lock or asyncio.Lock()
        self._mute_state = mute_state
        self._uses_default_play = play is None
        self._play = play or self._default_play
        self._task: asyncio.Task | None = None

    @property
    def is_active(self) -> bool:
        return self._task is not None and not self._task.done()

    async def replay(self, text: str) -> ReplayOutcome:
        if self._mute_state is not None and not self._mute_state.enabled:
            return ReplayOutcome.DISABLED
        if self.is_active:
            return ReplayOutcome.BUSY
        units = self._segment(text)
        if not units:
            return ReplayOutcome.EMPTY
        self._task = asyncio.create_task(self._run(units))
        return ReplayOutcome.STARTED

    def cancel(self) -> bool:
        """Stops an in-progress replay. Wired to the same Ctrl+Alt+I
        interrupt path that stops a live turn (story-v1.8.2). Returns
        whether there was a replay to cancel; safe to call when idle."""
        if not self.is_active:
            return False
        assert self._task is not None
        self._task.cancel()
        if self._uses_default_play:
            sd.stop()
        return True

    async def wait_for_pending(self) -> None:
        if self._task is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self, units: list[tuple[str, str]]) -> None:
        for text, language in units:
            audio = await self._engine.synthesize(text, language)
            await self._play(audio)

    def _segment(self, text: str) -> list[tuple[str, str]]:
        buffer = SpeechUnitBuffer(
            carry_connectives=_routes_share_one_engine(self._settings)
        )
        units = buffer.feed(text)
        units.extend(buffer.flush())
        return units

    async def _default_play(self, wav_bytes: bytes) -> None:
        data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        async with self._playback_lock:
            await asyncio.to_thread(sd.play, data, sample_rate)
            await asyncio.to_thread(sd.wait)
