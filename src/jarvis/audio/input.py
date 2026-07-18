"""Microphone capture plus Silero VAD end-of-utterance chunking.

VadChunker is pure segmentation logic. AudioInput owns live capture,
privacy sleep, speech auto-pause, and bus publication.
"""

import asyncio
import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import sounddevice as sd
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

from jarvis.audio.utils import samples_to_wav_bytes
from jarvis.core.bus import EventBus
from jarvis.core.config import HotkeySettings, VadSettings
from jarvis.inputs.hotkeys import HotkeyProvider, run_hotkey_provider

SAMPLE_RATE = 16000

# Lead-in kept ahead of any point of interest when the capture buffer is
# trimmed: pre-roll before an in-progress utterance, context retained for
# speech that starts in the next block, and pre-roll behind a published
# utterance. Bounding the buffer this way is what keeps the per-block VAD
# scan within the real-time budget during long silence - see the
# post-mute-first-capture-degraded bug report in tasks/bug_reports/.
BUFFER_LEAD_SECONDS = 1.0

logger = logging.getLogger(__name__)


class InputStreamLike(Protocol):
    """Shape of sd.InputStream that run_microphone_loop() relies on -
    lets tests inject a fake without a type-erasing Any."""

    def __enter__(self) -> "InputStreamLike": ...
    def __exit__(self, *exc_info: object) -> bool | None: ...
    def read(self, frames: int) -> tuple[np.ndarray, bool]: ...
    def stop(self) -> None: ...
    def start(self) -> None: ...


StreamFactory = Callable[[int], InputStreamLike]


def _default_stream_factory(block_samples: int, device: str = "") -> InputStreamLike:
    return sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=block_samples,
        device=device or None,
    )


def stream_factory_for_device(device: str) -> StreamFactory:
    """Binds a specific sounddevice device name (config.microphone.device,
    "" for the system default - see config.py's MicrophoneSettings) into a
    StreamFactory, so callers needing the real device selection (main.py's
    build_app()) don't need to know _default_stream_factory's extra
    parameter, and AudioInput's own constructor/StreamFactory type keep
    their existing single-argument shape - no test-injection seam changes
    for anything that already passes a fake stream_factory."""
    return functools.partial(_default_stream_factory, device=device)


@dataclass(frozen=True)
class UtteranceChunk:
    wav_bytes: bytes
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class MicSleepToggled:
    is_awake: bool


def _merge_close_segments(segments: list[dict], max_gap_seconds: float) -> list[dict]:
    if not segments:
        return []
    merged = [dict(segments[0])]
    for segment in segments[1:]:
        gap = segment["start"] - merged[-1]["end"]
        if gap < max_gap_seconds:
            merged[-1]["end"] = segment["end"]
        else:
            merged.append(dict(segment))
    return merged


def _cap_segment_durations(
    segments: list[dict], max_duration_seconds: float
) -> list[dict]:
    capped = []
    for segment in segments:
        start = segment["start"]
        end = segment["end"]
        while end - start > max_duration_seconds:
            capped.append({"start": start, "end": start + max_duration_seconds})
            start += max_duration_seconds
        capped.append({"start": start, "end": end})
    return capped


class VadChunker:
    def __init__(self, settings: VadSettings, model=None) -> None:
        self._settings = settings
        self._model = model if model is not None else load_silero_vad()

    @property
    def settings(self) -> VadSettings:
        return self._settings

    def chunk(self, samples: torch.Tensor) -> list[UtteranceChunk]:
        raw_segments = get_speech_timestamps(
            samples,
            self._model,
            threshold=self._settings.threshold,
            sampling_rate=SAMPLE_RATE,
            return_seconds=True,
        )
        merged = _merge_close_segments(
            raw_segments, self._settings.request_end_pause_seconds
        )
        capped = _cap_segment_durations(merged, float(self._settings.max_chunk_seconds))

        chunks = []
        for stamp in capped:
            start_sample = int(stamp["start"] * SAMPLE_RATE)
            end_sample = int(stamp["end"] * SAMPLE_RATE)
            segment = samples[start_sample:end_sample]
            chunks.append(
                UtteranceChunk(
                    wav_bytes=samples_to_wav_bytes(segment, SAMPLE_RATE),
                    start_seconds=stamp["start"],
                    end_seconds=stamp["end"],
                )
            )
        return chunks


class AudioInput:
    def __init__(
        self,
        bus: EventBus,
        chunker: VadChunker,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self._bus = bus
        self._chunker = chunker
        self._stream_factory = stream_factory or _default_stream_factory
        self._user_wants_awake = True
        self._auto_paused_for_speech = False
        self._awake = asyncio.Event()
        self._awake.set()
        self._stop_requested = False
        self._active_stream: InputStreamLike | None = None
        # Set on every transition into pause/sleep; run_microphone_loop()
        # discards its accumulated buffer (and the read that observed the
        # flag) before processing any further audio. This is what makes
        # buffer hygiene independent of stream.read() returning promptly -
        # see the stale-buffer-replay bug report in tasks/bug_reports/.
        self._buffer_invalidated = False
        # Set while run_microphone_loop() is NOT running. stop() awaits it
        # so that once stop() returns, the loop can submit no further
        # executor jobs - the deterministic boundary run_until_shutdown()
        # needs before cancelling tasks and tearing down the loop/executor
        # (see the shutdown-race bug report in tasks/bug_reports/).
        self._loop_exited = asyncio.Event()
        self._loop_exited.set()

    @property
    def is_awake(self) -> bool:
        """The actual, combined capture state - see module docstring."""
        return self._awake.is_set()

    async def toggle_user_sleep(self) -> None:
        self._user_wants_awake = not self._user_wants_awake
        await self._apply_combined_state()
        await self._bus.publish(
            MicSleepToggled, MicSleepToggled(is_awake=self._user_wants_awake)
        )

    async def auto_pause_for_speech(self) -> None:
        self._auto_paused_for_speech = True
        await self._apply_combined_state()

    async def auto_resume_after_speech(self) -> None:
        self._auto_paused_for_speech = False
        await self._apply_combined_state()

    async def _apply_combined_state(self) -> None:
        if self._user_wants_awake and not self._auto_paused_for_speech:
            self._awake.set()
        else:
            was_awake = self._awake.is_set()
            self._awake.clear()
            self._buffer_invalidated = True
            # Stop the stream so a stream.read() the loop is currently
            # blocked in gets interrupted (same mechanism stop() uses for
            # shutdown). Without this, a device that stops delivering
            # frames (hardware mute, USB stall) leaves the loop blocked in
            # read() with a stale buffer that replays as a fresh utterance
            # when frames eventually resume - verified live, see the bug
            # report referenced on _buffer_invalidated.
            if was_awake and self._active_stream is not None:
                await asyncio.to_thread(self._active_stream.stop)

    async def publish_from_samples(self, samples: torch.Tensor) -> None:
        for chunk in self._chunker.chunk(samples):
            await self._bus.publish(UtteranceChunk, chunk)

    async def stop(self) -> None:
        """Terminal shutdown: request the loop to exit, interrupt a
        blocked read, then wait - unconditionally - until the loop has
        actually finished. After this returns, the microphone code can
        submit no further executor job, and a microphone loop started
        after stop() exits immediately without opening a stream.
        stream.stop() interrupting a blocked read is verified device
        behavior (see the stale-buffer-replay fix); a driver whose read
        never returns even then would need its own explicit
        degraded-shutdown design, not a silent timeout here."""
        self._stop_requested = True
        self._awake.set()
        if self._active_stream is not None:
            await asyncio.to_thread(self._active_stream.stop)
        await self._loop_exited.wait()

    async def _read_stream_block(
        self, stream: InputStreamLike, block_samples: int
    ) -> np.ndarray | None:
        try:
            data, overflowed = await asyncio.to_thread(stream.read, block_samples)
        except Exception:
            if self._stop_requested or not self._awake.is_set():
                return None
            if self._buffer_invalidated:
                return None
            raise
        if self._stop_requested or not self._awake.is_set():
            return None
        if self._buffer_invalidated:
            return None
        if overflowed:
            logger.warning(
                "PortAudio input overflow: the capture loop fell behind "
                "and audio was dropped before this read"
            )
        return data[:, 0]

    async def _publish_and_trim(
        self, buffer: np.ndarray, published_end_seconds: float
    ) -> tuple[np.ndarray, float]:
        request_end_pause_seconds = self._chunker.settings.request_end_pause_seconds
        buffer_duration = len(buffer) / SAMPLE_RATE
        utterances = self._chunker.chunk(torch.from_numpy(buffer))
        for utterance in utterances:
            already_published = utterance.end_seconds <= published_end_seconds
            still_extending = (
                buffer_duration - utterance.end_seconds < request_end_pause_seconds
            )
            if already_published or still_extending:
                continue
            await self._bus.publish(UtteranceChunk, utterance)
            published_end_seconds = utterance.end_seconds

        # Trim audio that can no longer contribute to a future utterance.
        # The buffer must stay bounded even when nothing is ever published:
        # the whole buffer is re-scanned by VAD on every block, and an
        # unbounded silence buffer pushes that scan past the real-time
        # budget until the input ring overflows and drops audio.
        unpublished_starts = [
            utterance.start_seconds
            for utterance in utterances
            if utterance.end_seconds > published_end_seconds
        ]
        if unpublished_starts:
            keep_from_seconds = min(unpublished_starts) - BUFFER_LEAD_SECONDS
        else:
            keep_from_seconds = buffer_duration - BUFFER_LEAD_SECONDS
        trim_seconds = max(
            published_end_seconds - BUFFER_LEAD_SECONDS, keep_from_seconds, 0.0
        )
        if trim_seconds > 0:
            buffer = buffer[int(trim_seconds * SAMPLE_RATE) :]
            published_end_seconds = max(published_end_seconds - trim_seconds, 0.0)
        return buffer, published_end_seconds

    async def run_microphone_loop(self, poll_interval_seconds: float = 0.3) -> None:
        """Records microphone audio until cancelled or stopped."""
        self._loop_exited.clear()
        try:
            await self._run_microphone_loop(poll_interval_seconds)
        finally:
            self._loop_exited.set()

    async def _run_microphone_loop(self, poll_interval_seconds: float) -> None:
        buffer = np.zeros(0, dtype=np.float32)
        published_end_seconds = 0.0
        block_samples = int(SAMPLE_RATE * poll_interval_seconds)

        # Deliberately no reset of _stop_requested here: stop() is
        # terminal, and a loop that starts after stop() must exit at once
        # (sleep/wake is a separate mechanism, not a loop restart).
        while not self._stop_requested:
            await self._awake.wait()
            if self._stop_requested:
                break
            if self._buffer_invalidated:
                buffer = np.zeros(0, dtype=np.float32)
                published_end_seconds = 0.0
                self._buffer_invalidated = False

            # A paused sounddevice stream is closed by the context manager.
            # The next active period must enter a fresh stream instead of
            # calling start() on the object that PortAudio rejected after
            # wake on Windows MME.
            with self._stream_factory(block_samples) as stream:
                self._active_stream = stream
                try:
                    while self._awake.is_set() and not self._stop_requested:
                        block = await self._read_stream_block(stream, block_samples)
                        if block is None:
                            break
                        buffer = np.concatenate([buffer, block])
                        buffer, published_end_seconds = await self._publish_and_trim(
                            buffer, published_end_seconds
                        )
                finally:
                    self._active_stream = None

            if not self._awake.is_set() or self._buffer_invalidated:
                buffer = np.zeros(0, dtype=np.float32)
                published_end_seconds = 0.0
                self._buffer_invalidated = False


async def run_hotkey_listener(
    audio_input: AudioInput,
    hotkeys: HotkeySettings,
    provider: HotkeyProvider | None = None,
) -> None:
    """Binds the microphone privacy-toggle hotkey until cancelled."""
    loop = asyncio.get_running_loop()

    def on_toggle() -> None:
        asyncio.run_coroutine_threadsafe(audio_input.toggle_user_sleep(), loop)

    await run_hotkey_provider([(hotkeys.mic_sleep_toggle, on_toggle)], provider)
