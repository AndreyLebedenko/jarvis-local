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
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import numpy as np
import sounddevice as sd
import soundfile as sf

from jarvis.audio.tts import (
    SpeechUnitBuffer,
    TtsEngine,
    _routes_share_one_engine,
)
from jarvis.audio.tts_mute import TtsMuteState
from jarvis.core.config import TtsSettings
from jarvis.journal.events import JournalEvent, JournalEventRecord, JournalEventRef
from jarvis.journal.store import JournalStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextReply:
    """A playable segment synthesized from stored text (an assistant reply,
    story-v1.8.3)."""

    text: str


@dataclass(frozen=True)
class VoiceReply:
    """A playable segment decoded from a stored .wav (a voice user turn plays
    its own recording, not a re-synthesis - story-v1.8.3 task 3)."""

    wav_path: Path


PlayItem = TextReply | VoiceReply


@dataclass(frozen=True)
class ReplayProgress:
    """Which reply a running sequence is now playing, or None when the
    sequence has ended or been stopped (story-v1.8.3 task 2). The UI moves the
    now-playing highlight to this reference, or clears it on None."""

    reference: JournalEventRef | None


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


class _OutputStream(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def abort(self) -> None: ...
    def close(self) -> None: ...


StreamFactory = Callable[
    [int, int, Callable[..., None], Callable[[], None]], _OutputStream
]


def _default_stream_factory(
    samplerate: int,
    channels: int,
    callback: Callable[..., None],
    finished_callback: Callable[[], None],
) -> _OutputStream:
    return sd.OutputStream(
        samplerate=samplerate,
        channels=channels,
        dtype="float32",
        callback=callback,
        finished_callback=finished_callback,
    )


class PausablePlayback:
    """A single clip of float32 frames played through a callback OutputStream
    with a preserved playback-position marker, so it can pause (suspend at the
    current frame) and resume (continue from it). Source-agnostic: the frames
    may be synthesized PCM (an assistant reply) or a decoded .wav (a voice user
    turn), and pause/resume behave identically for both (story-v1.8.3 task 1).

    PortAudio invokes the stream callback on its own thread; the finished
    callback also fires when the stream is merely stopped for a pause, so a
    pause-induced stop is distinguished from a real end by the position marker
    (only pos >= len, or an explicit stop(), is a real finish)."""

    def __init__(
        self,
        frames: np.ndarray,
        samplerate: int,
        playback_lock: asyncio.Lock,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self._frames = frames
        self._samplerate = int(samplerate)
        self._channels = 1 if frames.ndim == 1 else int(frames.shape[1])
        self._lock = playback_lock
        self._stream_factory = stream_factory or _default_stream_factory
        self._pos = 0
        self._paused = False
        self._stopped = False
        self._stream: _OutputStream | None = None
        self._finished = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def position(self) -> int:
        return self._pos

    @property
    def is_paused(self) -> bool:
        return self._paused

    async def play_to_completion(self) -> None:
        self._loop = asyncio.get_running_loop()
        async with self._lock:
            self._stream = self._stream_factory(
                self._samplerate, self._channels, self._callback, self._on_finished
            )
            self._stream.start()
            try:
                await self._finished.wait()
            finally:
                self._stream.close()
                self._stream = None

    def pause(self) -> None:
        if self._stream is not None and not self._paused and not self._stopped:
            self._paused = True
            self._stream.stop()

    def resume(self) -> None:
        if self._stream is not None and self._paused and not self._stopped:
            self._paused = False
            self._stream.start()

    def stop(self) -> None:
        self._stopped = True
        if self._stream is not None:
            self._stream.abort()
        self._on_finished()

    def _callback(self, outdata: np.ndarray, frames: int, *_: object) -> None:
        remaining = len(self._frames) - self._pos
        if self._stopped or remaining <= 0:
            raise sd.CallbackStop
        take = min(frames, remaining)
        chunk = self._frames[self._pos : self._pos + take]
        if self._channels == 1:
            outdata[:take, 0] = chunk
        else:
            outdata[:take] = chunk
        if take < frames:
            outdata[take:] = 0
        self._pos += take
        if self._pos >= len(self._frames):
            raise sd.CallbackStop

    def _on_finished(self) -> None:
        # PortAudio calls this whenever the stream stops. Only a deliberate
        # pause (pause() sets _paused before stopping) keeps the clip open to
        # resume from the marker; every other stop - reaching the end, an
        # explicit stop(), or an unexpected device/callback stop mid-clip -
        # completes it. Keying this on _paused rather than the position marker
        # is load-bearing: an early device stop leaves pos < len yet is not a
        # pause, and treating it as one would wait forever for a finish that
        # never comes, hanging the whole sequence on that segment.
        if self._paused and not self._stopped and self._pos < len(self._frames):
            return
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._finished.set)
        else:
            self._finished.set()


class ReplayPlayer:
    def __init__(
        self,
        settings: TtsSettings,
        engine: TtsEngine,
        play: Callable[[bytes], Awaitable[None]] | None = None,
        playback_lock: asyncio.Lock | None = None,
        mute_state: TtsMuteState | None = None,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._playback_lock = playback_lock or asyncio.Lock()
        self._mute_state = mute_state
        self._play = play or self._default_play
        self._stream_factory = stream_factory
        self._current_playback: PausablePlayback | None = None
        self._task: asyncio.Task | None = None

    @property
    def is_active(self) -> bool:
        return self._task is not None and not self._task.done()

    async def replay(self, text: str) -> ReplayOutcome:
        return await self.replay_items([TextReply(text)])

    async def replay_many(
        self,
        texts: list[str],
        on_reply_start: Callable[[int], Awaitable[None]] | None = None,
    ) -> ReplayOutcome:
        return await self.replay_items(
            [TextReply(text) for text in texts], on_reply_start
        )

    async def replay_items(
        self,
        items: list[PlayItem],
        on_reply_start: Callable[[int], Awaitable[None]] | None = None,
    ) -> ReplayOutcome:
        """Plays a heterogeneous run of replies back to back as one logical
        replay (a single task, so is_active spans the whole run and cancel()
        ends all of it - story-v1.8.3). A TextReply is synthesized (segmented
        on its own so speech units never carry across a boundary); a VoiceReply
        plays its stored .wav directly. on_reply_start(index) is awaited just
        before a reply's audio starts, where index is that reply's position in
        items, so a caller can follow which reply is now playing. A VoiceReply
        whose wav is unreadable is skipped (no on_reply_start) and the run
        continues."""
        if self._mute_state is not None and not self._mute_state.enabled:
            return ReplayOutcome.DISABLED
        if self.is_active:
            return ReplayOutcome.BUSY
        groups: list[tuple[int, PlayItem, list[tuple[str, str]]]] = []
        for index, item in enumerate(items):
            if isinstance(item, TextReply):
                units = self._segment(item.text)
                if units:
                    groups.append((index, item, units))
            else:
                groups.append((index, item, []))
        if not groups:
            return ReplayOutcome.EMPTY
        self._task = asyncio.create_task(self._run(groups, on_reply_start))
        return ReplayOutcome.STARTED

    @property
    def is_paused(self) -> bool:
        return self._current_playback is not None and self._current_playback.is_paused

    def cancel(self) -> bool:
        """Stops an in-progress replay. Wired to the same Ctrl+Alt+I
        interrupt path that stops a live turn (story-v1.8.2). Returns
        whether there was a replay to cancel; safe to call when idle."""
        if not self.is_active:
            return False
        assert self._task is not None
        if self._current_playback is not None:
            self._current_playback.stop()
        self._task.cancel()
        return True

    def pause(self) -> bool:
        """Suspends the current clip at its playback position (story-v1.8.3).
        Returns whether there was a playing clip to pause."""
        if self._current_playback is None or self._current_playback.is_paused:
            return False
        self._current_playback.pause()
        return True

    def resume(self) -> bool:
        """Continues a paused clip from its held position (story-v1.8.3).
        Returns whether there was a paused clip to resume."""
        if self._current_playback is None or not self._current_playback.is_paused:
            return False
        self._current_playback.resume()
        return True

    async def wait_for_pending(self) -> None:
        if self._task is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(
        self,
        groups: list[tuple[int, PlayItem, list[tuple[str, str]]]],
        on_reply_start: Callable[[int], Awaitable[None]] | None,
    ) -> None:
        for index, item, units in groups:
            if isinstance(item, VoiceReply):
                audio = self._read_voice_wav(item.wav_path)
                if audio is None:
                    continue
                if on_reply_start is not None:
                    await on_reply_start(index)
                await self._play(audio)
                continue
            if on_reply_start is not None:
                await on_reply_start(index)
            for text, language in units:
                audio = await self._engine.synthesize(text, language)
                await self._play(audio)

    def _read_voice_wav(self, path: Path) -> bytes | None:
        """Reads a voice turn's stored wav for direct playback, validating it
        decodes. A missing or corrupt file is skipped (logged), not fatal, so
        the sequence continues (story-v1.8.3 task 3)."""
        try:
            data = path.read_bytes()
            sf.read(io.BytesIO(data), dtype="float32")
        except (OSError, sf.SoundFileError) as error:
            logger.warning("Skipping unplayable voice reply %s: %s", path, error)
            return None
        return data

    def _segment(self, text: str) -> list[tuple[str, str]]:
        buffer = SpeechUnitBuffer(
            carry_connectives=_routes_share_one_engine(self._settings)
        )
        units = buffer.feed(text)
        units.extend(buffer.flush())
        return units

    async def _default_play(self, wav_bytes: bytes) -> None:
        data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        playback = PausablePlayback(
            data, sample_rate, self._playback_lock, stream_factory=self._stream_factory
        )
        self._current_playback = playback
        try:
            await playback.play_to_completion()
        finally:
            self._current_playback = None


class SequencePlayer:
    """Plays a session's playable turns from a chosen event forward: assistant
    replies (re-synthesized) and voice user turns (their stored .wav played
    directly) interleaved in journal order (story-v1.8.3 tasks 2-3). It knows
    the journal; the ReplayPlayer owns the single-task playback loop so
    pause/resume/cancel and busy rejection keep their v1.8.2 semantics at the
    grain of the whole sequence."""

    def __init__(self, store: JournalStore, player: ReplayPlayer) -> None:
        self._store = store
        self._player = player

    def _assistant_records(self, start: JournalEventRef) -> list[JournalEventRecord]:
        replay = self._store.read_session(start.session_id)
        return [
            record
            for record in replay.records
            if record.reference.event_position >= start.event_position
            and record.event.role == "assistant"
        ]

    def texts_from(self, start: JournalEventRef) -> list[str]:
        return [record.event.text for record in self._assistant_records(start)]

    def _play_item(self, event: JournalEvent) -> PlayItem | None:
        """The playable source for one event (story-v1.8.3 task 3 accessor):
        an assistant reply's text to synthesize, a voice user turn's stored
        wav to play directly, or None for a typed-user or system event. The
        v1.9.0 seam stays: the assistant branch still returns text and later
        retargets to the mode-3 derivative."""
        if event.role == "assistant":
            return TextReply(event.text)
        if event.role == "user" and event.source == "voice":
            wav = next(
                (name for name in event.media if name.lower().endswith(".wav")), None
            )
            if wav is None:
                return None
            try:
                return VoiceReply(self._store.media_path(event.session_id, wav))
            except ValueError:
                return None
        return None

    async def play_from(
        self,
        start: JournalEventRef,
        on_segment: Callable[[JournalEventRef], Awaitable[None]] | None = None,
    ) -> ReplayOutcome:
        """Plays every playable turn from start forward. on_segment(ref) is
        awaited as each turn begins so the UI can move the now-playing
        highlight across rows before its audio starts (story-v1.8.3)."""
        replay = self._store.read_session(start.session_id)
        items: list[PlayItem] = []
        refs: list[JournalEventRef] = []
        for record in replay.records:
            if record.reference.event_position < start.event_position:
                continue
            item = self._play_item(record.event)
            if item is None:
                continue
            items.append(item)
            refs.append(record.reference)
        on_reply_start = None
        if on_segment is not None:

            async def on_reply_start(index: int) -> None:
                await on_segment(refs[index])

        return await self._player.replay_items(items, on_reply_start=on_reply_start)
