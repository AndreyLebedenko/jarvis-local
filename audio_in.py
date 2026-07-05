"""Microphone capture plus Silero VAD end-of-utterance chunking.

Segments continuous 16 kHz mono audio into utterance chunks and publishes
each finished chunk as a wav payload on the bus.

VadChunker is pure segmentation logic: it takes a complete 16 kHz mono
audio tensor and returns UtteranceChunk objects, with no file or
microphone I/O. This is what's testable against prerecorded fixtures
without a microphone (per PROJECT.md's testing protocol).

Silero's get_speech_timestamps() splits raw speech into small segments at
any internal pause (~100 ms, not exposed here). That is a within-request
micro-pause, not a request boundary: two segments separated by a breath
or a thinking pause shorter than config.vad.request_end_pause_seconds are
merged into a single utterance. Only a gap at least that long - absence
of detected speech, not necessarily full digital silence - is treated as
the user actually finishing. The merged result is then capped at
config.vad.max_chunk_seconds (PROJECT.md's verified 30 s limit).

AudioInput wires VadChunker's output onto the bus. Its microphone-capture
loop is hardware-dependent and covered by the manual handoff, not
automated tests - but it feeds live audio into the same VadChunker.chunk()
used by the fixture tests, per this module's task card. It uses the same
request_end_pause_seconds threshold to decide when a merged utterance is
safe to finalize and publish (no further speech can still be merged into
it once that much trailing buffer has passed with no new segment).

Sleep mode (task-09, v1.1): AudioInput.sleep()/wake() toggle a privacy
pause driven from outside the module (a hotkey, wired in task-10) - a
genuine capture pause, not just discarding results while still listening.
run_microphone_loop() reuses the same sd.InputStream across sleep/wake
cycles via its own .stop()/.start() (reconstructing it would add
wake-latency and is unnecessary), blocks efficiently on an asyncio.Event
while asleep (no busy-polling), and resets the accumulated buffer on the
sleep transition: without that reset, speech captured just before sleep
could still be sitting in the buffer, unconfirmed, when new speech
arrives after wake, and the VAD/merge pipeline could stitch them into one
utterance spanning a real gap where nothing was actually being captured.
Any not-yet-confirmed audio in the buffer at the moment sleep triggers is
therefore discarded, not published - consistent with sleep being a
privacy pause, not a "flush first" action.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import sounddevice as sd
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

from audio_utils import samples_to_wav_bytes
from bus import EventBus
from config import VadSettings

SAMPLE_RATE = 16000


class InputStreamLike(Protocol):
    """Shape of sd.InputStream that run_microphone_loop() relies on -
    lets tests inject a fake without a type-erasing Any."""

    def __enter__(self) -> "InputStreamLike": ...
    def __exit__(self, *exc_info: object) -> bool | None: ...
    def read(self, frames: int) -> tuple[np.ndarray, bool]: ...
    def stop(self) -> None: ...
    def start(self) -> None: ...


StreamFactory = Callable[[int], InputStreamLike]


def _default_stream_factory(block_samples: int) -> InputStreamLike:
    return sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=block_samples
    )


@dataclass(frozen=True)
class UtteranceChunk:
    wav_bytes: bytes
    start_seconds: float
    end_seconds: float


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


def _cap_segment_durations(segments: list[dict], max_duration_seconds: float) -> list[dict]:
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
        merged = _merge_close_segments(raw_segments, self._settings.request_end_pause_seconds)
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
        self._awake = asyncio.Event()
        self._awake.set()

    @property
    def is_awake(self) -> bool:
        return self._awake.is_set()

    async def sleep(self) -> None:
        self._awake.clear()

    async def wake(self) -> None:
        self._awake.set()

    async def publish_from_samples(self, samples: torch.Tensor) -> None:
        for chunk in self._chunker.chunk(samples):
            await self._bus.publish(UtteranceChunk, chunk)

    async def run_microphone_loop(self, poll_interval_seconds: float = 0.3) -> None:
        """Continuously records from the default input device at 16 kHz
        mono, re-running the chunker over the accumulated buffer every
        poll interval. An utterance is published once it is followed by
        settings.request_end_pause_seconds of buffered audio with no
        further speech merged into it (confirming it has actually ended,
        not just paused mid-request). Runs until cancelled.

        While asleep, the loop blocks on self._awake.wait() instead of
        reading the stream, and the buffer is dropped on the sleep
        transition (see module docstring for why).
        """
        request_end_pause_seconds = self._chunker.settings.request_end_pause_seconds
        buffer = np.zeros(0, dtype=np.float32)
        published_end_seconds = 0.0
        block_samples = int(SAMPLE_RATE * poll_interval_seconds)

        with self._stream_factory(block_samples) as stream:
            while True:
                if not self._awake.is_set():
                    await asyncio.to_thread(stream.stop)
                    buffer = np.zeros(0, dtype=np.float32)
                    published_end_seconds = 0.0
                    await self._awake.wait()
                    await asyncio.to_thread(stream.start)
                    continue

                data, _ = await asyncio.to_thread(stream.read, block_samples)
                buffer = np.concatenate([buffer, data[:, 0]])
                buffer_duration = len(buffer) / SAMPLE_RATE

                for utterance in self._chunker.chunk(torch.from_numpy(buffer)):
                    already_published = utterance.end_seconds <= published_end_seconds
                    still_extending = (
                        buffer_duration - utterance.end_seconds < request_end_pause_seconds
                    )
                    if already_published or still_extending:
                        continue
                    await self._bus.publish(UtteranceChunk, utterance)
                    published_end_seconds = utterance.end_seconds

                trim_seconds = max(published_end_seconds - 1.0, 0.0)
                if trim_seconds > 0:
                    buffer = buffer[int(trim_seconds * SAMPLE_RATE):]
                    published_end_seconds -= trim_seconds
