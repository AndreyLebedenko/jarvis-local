"""Common TTS streaming, routing, playback, events, and engine contracts."""

import asyncio
import io
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

import sounddevice as sd
import soundfile as sf

from jarvis.audio.language_segments import (
    DEFAULT_LANGUAGE,
    CharsetLanguageStream,
)
from jarvis.core.bus import EventBus
from jarvis.core.config import TtsSettings
from jarvis.dialog.backend import ResponseComplete, ResponseToken

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TtsSynthesisResult:
    """Outcome of synthesizing one speech unit. Raw health signal for
    ModuleHealthTracker; playback is unaffected either way (a failed unit
    is skipped, see _synthesize_and_submit)."""

    language: str
    succeeded: bool


@dataclass(frozen=True)
class TtsEngineLoadFailed:
    """A route could not lazy-load its configured engine/model."""

    language: str
    engine: str
    model: str
    message: str


FINAL_PLAYBACK_TAIL_SECONDS = 1.0


class TtsEngineLoadError(RuntimeError):
    def __init__(self, engine: str, model: str, detail: str) -> None:
        super().__init__(f"{engine} model {model!r} failed to load: {detail}")
        self.engine = engine
        self.model = model
        self.detail = detail


_T = TypeVar("_T")


class LazyAsyncLoad(Generic[_T]):
    """Loads a value at most once, the first time it is needed.

    A successful load is cached and returned on every later call without
    re-running the loader. A failed load is wrapped in TtsEngineLoadError
    and that same error is cached and re-raised on every later call too -
    a broken model/voice does not get retried per synthesis request. Used
    by SileroEngine and PiperEngine, whose lazy-load-and-cache-error
    pattern was otherwise identical except for what gets loaded."""

    def __init__(self, engine: str, model: str) -> None:
        self._engine = engine
        self._model = model
        self._value: _T | None = None
        self._error: TtsEngineLoadError | None = None
        self._lock = asyncio.Lock()

    async def get(self, loader: Callable[[], Awaitable[_T]]) -> _T:
        if self._error is not None:
            raise self._error
        if self._value is not None:
            return self._value
        async with self._lock:
            if self._error is not None:
                raise self._error
            if self._value is not None:
                return self._value
            try:
                self._value = await loader()
            except Exception as exc:
                self._error = TtsEngineLoadError(self._engine, self._model, str(exc))
                raise self._error from exc
        return self._value


class TtsEngine(Protocol):
    """Synthesis boundary: text in, wav-encoded audio bytes out. The wav
    container header is the sample-rate contract - playback reads it from
    the bytes, so engines with different native rates need no side channel.

    `language` is the routing hint carried by language_segments.py's segments.
    Per-language configuration chooses the engine independently; the verified
    Silero/ru + Piper/en production setup is not a required mapping. Child
    engines may ignore the routing hint because their typed route already
    selects the concrete model language; Russian-only normalization remains a
    Silero route concern."""

    async def synthesize(
        self, text: str, language: str = DEFAULT_LANGUAGE
    ) -> bytes: ...


def _append_wav_tail_silence(wav_bytes: bytes, seconds: float) -> bytes:
    if seconds <= 0:
        return wav_bytes

    data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=True)
    tail_frames = round(sample_rate * seconds)
    if tail_frames <= 0:
        return wav_bytes

    import numpy as np

    tail = np.zeros((tail_frames, data.shape[1]), dtype=data.dtype)
    padded = np.concatenate((data, tail), axis=0)
    output = io.BytesIO()
    sf.write(output, padded, sample_rate, format="WAV")
    return output.getvalue()


# Common Russian abbreviations that end in a period but do not end a
# sentence. Not exhaustive - deliberately biased toward under-splitting:
# a missed boundary just merges two sentences into one slightly longer
# utterance; a false boundary would cut off mid-abbreviation and produce
# broken speech, which is the worse failure mode.
_ABBREVIATIONS = {
    "т.е",
    "т.д",
    "т.п",
    "др",
    "пр",
    "см",
    "мм",
    "кг",
    "г",
    "гг",
    "им",
    "проф",
    "акад",
    "руб",
    "коп",
    "стр",
    "рис",
    "табл",
    "гл",
    "ст",
    "разд",
    "тов",
    "г-н",
    "г-жа",
}

_BOUNDARY_RE = re.compile(r"[.!?]+(?=\s)")
_TRAILING_WORD_RE = re.compile(r"\S+$")


class SentenceBuffer:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        sentences = []
        search_start = 0
        while True:
            match = _BOUNDARY_RE.search(self._buffer, search_start)
            if match is None:
                break
            if self._is_abbreviation(match.start()):
                search_start = match.end()
                continue
            sentences.append(self._buffer[: match.end()].strip())
            self._buffer = self._buffer[match.end() :]
            search_start = 0
        return sentences

    def flush(self) -> str | None:
        sentence = self._buffer.strip()
        self._buffer = ""
        return sentence or None

    def _is_abbreviation(self, punctuation_start: int) -> bool:
        word_match = _TRAILING_WORD_RE.search(self._buffer[:punctuation_start])
        if word_match is None:
            return False
        word = word_match.group().strip(".").lower()
        return word in _ABBREVIATIONS


_WORD_CHAR_RE = re.compile(r"\w")
_SENTENCE_PUNCT_RE = re.compile(r"[.!?]")

# A language-switch remainder with at most this many word characters and no
# sentence-ending punctuation is carried into the following segment instead
# of becoming its own tiny synthesis call - story-v1.2.8's AC forbids
# unnatural standalone calls, and for spans this short prosody matters more
# than language attribution. Only valid while every configured route uses
# ONE engine (the Silero-only default, whose transliteration covers either
# direction): with distinct per-language engines, carrying moves text into
# an engine that cannot pronounce it at all - verified live in the v1.2.9
# task-4 handoff, where a carried Russian "Для" was spelled out letter by
# letter by Piper. SpeechUnitBuffer's carry_connectives flag gates this.
_CONNECTIVE_MAX_WORD_CHARS = 3


class SpeechUnitBuffer:
    """Streams response tokens into ordered (text, language) speech units.

    Language segmentation happens BEFORE sentence buffering: tokens go
    through CharsetLanguageStream, so Russian/English routing no longer
    depends on the model emitting XML-like control tags. Within a language
    run, SentenceBuffer provides the usual sentence-boundary flushes; a
    language switch is an additional unit boundary, which is what lets a
    short foreign insert start synthesis before any ". " arrives.
    """

    def __init__(self, carry_connectives: bool = True) -> None:
        self._segments = CharsetLanguageStream()
        self._sentences = SentenceBuffer()
        self._language = DEFAULT_LANGUAGE
        self._carry_connectives = carry_connectives

    def feed(self, text: str) -> list[tuple[str, str]]:
        units: list[tuple[str, str]] = []
        for piece in self._segments.feed(text):
            self._feed_piece(units, piece.language, piece.text)
        return units

    def flush(self) -> list[tuple[str, str]]:
        """Ends the current response turn: flushes everything speakable and
        resets language-segmentation state."""
        units: list[tuple[str, str]] = []
        for piece in self._segments.close():
            self._feed_piece(units, piece.language, piece.text)
        remainder = self._sentences.flush()
        if remainder and _WORD_CHAR_RE.search(remainder):
            units.append((remainder, self._language))
        self._segments = CharsetLanguageStream()
        self._language = DEFAULT_LANGUAGE
        return units

    def _feed_piece(
        self, units: list[tuple[str, str]], language: str, text: str
    ) -> None:
        if language != self._language:
            remainder = self._sentences.flush()
            if remainder:
                if self._carry_connectives and self._is_connective(remainder):
                    text = f"{remainder} {text}"
                else:
                    units.append((remainder, self._language))
            self._language = language
        for sentence in self._sentences.feed(text):
            units.append((sentence, self._language))

    @staticmethod
    def _is_connective(text: str) -> bool:
        return (
            _SENTENCE_PUNCT_RE.search(text) is None
            and len(_WORD_CHAR_RE.findall(text)) <= _CONNECTIVE_MAX_WORD_CHARS
        )


class OrderedPlayback:
    """Plays (index, audio) results in strict index order, regardless of
    the order they are submitted in - so concurrent synthesis of several
    sentences can never cause a later one to play before an earlier one.

    Every scheduled index MUST eventually be submitted, or playback stalls
    forever at the gap; a failed synthesis therefore submits audio=None,
    which advances the order without playing anything. The player receives
    the index alongside the audio so the caller can make play-time
    decisions (TtsOutput's final-unit tail guard needs to know, at the
    moment sound reaches the device, whether a later unit exists yet).
    """

    def __init__(self, player: Callable[[int, bytes], Awaitable[None]]) -> None:
        self._player = player
        self._pending: dict[int, bytes | None] = {}
        self._next_index = 0
        self._lock = asyncio.Lock()

    async def submit(self, index: int, audio: bytes | None) -> None:
        async with self._lock:
            self._pending[index] = audio
            while self._next_index in self._pending:
                ready = self._pending.pop(self._next_index)
                if ready is not None:
                    await self._player(self._next_index, ready)
                self._next_index += 1


class BilingualTtsEngine:
    def __init__(self, engines: dict[str, TtsEngine]) -> None:
        self._engines = dict(engines)

    async def synthesize(self, text: str, language: str = DEFAULT_LANGUAGE) -> bytes:
        try:
            engine = self._engines[language]
        except KeyError as exc:
            available = ", ".join(sorted(self._engines))
            raise ValueError(
                f"Unsupported TTS language for configured routing: {language!r}. "
                f"Configured languages: {available}"
            ) from exc
        return await engine.synthesize(text, language)


def _routes_share_one_engine(settings: TtsSettings) -> bool:
    return len({route.engine for route in settings.languages.values()}) == 1


class TtsOutput:
    def __init__(
        self,
        settings: TtsSettings,
        engine: TtsEngine,
        play: Callable[[bytes], Awaitable[None]] | None = None,
        playback_lock: asyncio.Lock | None = None,
        bus: "EventBus | None" = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        # Carrying a short language-switch remainder into the next unit is
        # only safe when one engine voices everything; with per-language
        # engines it would hand text to an engine that cannot pronounce it
        # (see _CONNECTIVE_MAX_WORD_CHARS).
        self._units = SpeechUnitBuffer(
            carry_connectives=_routes_share_one_engine(settings)
        )
        self._engine = engine
        # Shared with SoundCuePlayer (see main.py's build_app()) so a sound
        # cue can never physically overlap a spoken sentence on the
        # output device: sounddevice's play()/wait() convenience API
        # shares one implicit default stream per process, and two
        # concurrent play() calls stop/replace each other rather than
        # mixing - the cause of audible crackling/tempo artifacts if
        # cues and speech land at the same time (verified live).
        self._playback_lock = playback_lock or asyncio.Lock()
        self._uses_default_play = play is None
        self._play = play or self._default_play
        self._playback = OrderedPlayback(self._play_unit)
        self._next_index = 0
        self._pending_tasks: set[asyncio.Task] = set()
        self._reported_load_failures: set[tuple[str, str, str]] = set()

    async def on_token(self, event: ResponseToken) -> None:
        for text, language in self._units.feed(event.text):
            self._schedule(text, language)

    async def on_response_complete(self, event: ResponseComplete) -> None:
        for text, language in self._units.flush():
            self._schedule(text, language)

    async def wait_for_pending(self) -> None:
        """Awaits every synthesis/playback task scheduled so far. Useful
        both for tests and for a graceful shutdown that lets in-flight
        speech finish rather than cutting it off mid-sentence."""
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks)

    def _schedule(self, text: str, language: str) -> None:
        index = self._next_index
        self._next_index += 1
        task = asyncio.create_task(self._synthesize_and_submit(index, text, language))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _synthesize_and_submit(
        self, index: int, text: str, language: str
    ) -> None:
        try:
            audio = await self._engine.synthesize(text, language)
        except TtsEngineLoadError as exc:
            failure_key = (language, exc.engine, exc.model)
            if failure_key not in self._reported_load_failures:
                self._reported_load_failures.add(failure_key)
                logger.exception(
                    "TTS engine load failed (language=%r, engine=%r, model=%r)",
                    language,
                    exc.engine,
                    exc.model,
                )
                await self._publish_load_failure(language, exc)
            await self._playback.submit(index, None)
            return
        except Exception:
            # OrderedPlayback requires every index to arrive or all later
            # units stay buffered forever; a failed unit must therefore
            # still advance the order. Losing one sentence of speech is
            # recoverable, silently losing all speech for the rest of the
            # session is not.
            logger.exception(
                "TTS synthesis failed for unit %d (language=%r); skipping its playback",
                index,
                language,
            )
            await self._publish_result(language, succeeded=False)
            await self._playback.submit(index, None)
            return
        await self._publish_result(language, succeeded=True)
        await self._playback.submit(index, audio)

    async def _publish_result(self, language: str, succeeded: bool) -> None:
        if self._bus is not None:
            await self._bus.publish(
                TtsSynthesisResult,
                TtsSynthesisResult(language=language, succeeded=succeeded),
            )

    async def _publish_load_failure(
        self, language: str, error: TtsEngineLoadError
    ) -> None:
        if self._bus is not None:
            await self._bus.publish(
                TtsEngineLoadFailed,
                TtsEngineLoadFailed(
                    language=language,
                    engine=error.engine,
                    model=error.model,
                    message=error.detail,
                ),
            )

    async def _play_unit(self, index: int, audio: bytes) -> None:
        """Playback callback for OrderedPlayback, applying the final-unit
        tail guard at the last responsible moment.

        The last unit of a response gets FINAL_PLAYBACK_TAIL_SECONDS of
        silent post-roll: without it, human testing across Silero and Piper
        heard final phrase endings clipped when the output device shut down.
        Which unit is final is only knowable once ResponseComplete arrives,
        but its playback can legitimately happen earlier (verified live:
        deciding at synthesis time against an index recorded by
        on_response_complete lost the race whenever the last sentence was
        flushed mid-stream and synthesized quickly - the clipping came back
        intermittently). So the decision is made here, when sound actually
        reaches the device: pad iff no later unit has been scheduled yet.
        For the true final unit that is always true. A mid-stream unit can
        match too, when generation is slow enough that the next sentence
        has not been scheduled yet - then the pause is masked by waiting
        for that next sentence anyway (worst case: up to the tail length
        of extra pause at one sentence boundary)."""
        if self._uses_default_play and index == self._next_index - 1:
            audio = _append_wav_tail_silence(audio, FINAL_PLAYBACK_TAIL_SECONDS)
        await self._play(audio)

    async def _default_play(self, wav_bytes: bytes) -> None:
        import io

        data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        async with self._playback_lock:
            await asyncio.to_thread(sd.play, data, sample_rate)
            await asyncio.to_thread(sd.wait)
