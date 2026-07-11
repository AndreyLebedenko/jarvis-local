"""Sentence-buffered, charset-language-aware Silero TTS output.

Streams backend.py's response tokens through language_segments.py's
incremental Russian/English segmenter, buffers each language run to
sentence boundaries - a language switch is an additional flush boundary -
then synthesizes each completed unit and plays them back in order while
generation continues, per PROJECT.md's "sentence-level streaming is
mandatory" requirement for tts.py. The language reaches TtsEngine as a
routing hint: the default Silero-only engine ignores it (transliteration
fallback), while a configured bilingual route dispatches ru to Silero and
en to Piper through BilingualTtsEngine (v1.2.9).

Per bus.py's handler contract, on_token()/on_response_complete() only
feed the sentence buffer and schedule synthesis as a background task;
they never synthesize or play inline, so a slow synthesis call cannot
stall bus dispatch to any other subscriber.

TtsSettings.rate is intentionally unused here: adjusting speech rate
would require SSML/prosody control, which this task's card puts out of
scope for v1.0 (reserved for a later, XTTS-v2-era revision).

Verified live (manual handoff): the v3_1_ru model's symbol set
(model.symbols) has no digit characters at all - prepare_text_input()
silently strips any digit before synthesis, so raw numbers are never
voiced (not an error, just silence where the number should be). This is
a model limitation, not a bug in sentence buffering: normalize_numbers()
converts digit runs to Russian words before synthesis, applied only at
the point text is handed to Silero - sentence-boundary detection still
runs on the original text (its decimal-number handling is unrelated to
whether the model can pronounce digits).

Offline policy (PROJECT.md: "runtime must not require network access"):
loading the Silero TTS model is a one-time setup step requiring network
access, exactly like `ollama pull` is for the backend model - it is not
part of this module's runtime behavior. Run `python setup_tts_model.py`
once beforehand. _load_model() checks the local cache explicitly before
ever calling into silero and raises TtsModelNotCachedError with that
instruction if the cache is missing, rather than silently reaching for
the network at runtime.
"""

import asyncio
import io
import logging
import re
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

import sounddevice as sd
import soundfile as sf
from num2words import num2words

from audio_utils import samples_to_wav_bytes
from backend import ResponseComplete, ResponseToken
from config import SILERO_MODEL, TtsLanguageSettings, TtsSettings
from language_segments import DEFAULT_LANGUAGE, ENGLISH, CharsetLanguageStream

logger = logging.getLogger(__name__)

SAMPLE_RATE = 48000
FINAL_PLAYBACK_TAIL_SECONDS = 1.0

# Filenames Silero's own downloader produces for this exact model/speaker
# (see setup_tts_model.py). Hardcoded rather than parsed from the models
# manifest, to avoid an extra dependency (omegaconf) for a single, fixed
# model choice - revisit if the speaker/model choice ever changes.
_MODELS_MANIFEST_FILENAME = "latest_silero_models.yml"
_MODEL_CACHE_FILENAME = "v3_1_ru.pt"

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


class TtsModelNotCachedError(RuntimeError):
    pass


class VoiceLoader(Protocol):
    def __call__(
        self, *, model_path: Path, config_path: Path, use_cuda: bool
    ) -> object:
        pass


class EngineBuilder(Protocol):
    def __call__(self, route: TtsLanguageSettings) -> "TtsEngine":
        pass


class TtsEngine(Protocol):
    """Synthesis boundary: text in, wav-encoded audio bytes out. The wav
    container header is the sample-rate contract - playback reads it from
    the bytes, so engines with different native rates need no side channel.

    `language` is the routing hint carried by language_segments.py's segments.
    Per-language configuration chooses the engine independently; the verified
    Silero/ru + Piper/en production setup is not a required mapping. An engine
    that cannot switch languages may ignore the hint - SileroEngine does,
    since its transliteration fallback already covers non-Russian text."""

    async def synthesize(self, text: str, language: str = DEFAULT_LANGUAGE) -> bytes:
        pass


def _ensure_model_cached(silero_module, repo_root: Path | None = None) -> None:
    """Fails clearly and offline rather than letting silero_tts() fall
    through to a network download when the local cache is missing.

    Two independent things must be true:
    1. The manifest and model weights actually exist next to this code
       (repo-root-relative, not CWD-relative - so this check itself is
       correct regardless of the caller's current working directory).
    2. silero_tts() looks for the manifest by that exact filename
       relative to the process's *current working directory* - a
       third-party quirk with no override parameter. The rest of this
       project already assumes the process is launched from the repo
       root (config.toml's default path, sound cue paths, etc.), so this
       is an existing constraint, not a new one - but it is flagged
       precisely here rather than silently reached past.
    """
    repo_root = repo_root or Path(__file__).resolve().parent
    repo_manifest = repo_root / _MODELS_MANIFEST_FILENAME
    model_path = Path(silero_module.__file__).parent / "model" / _MODEL_CACHE_FILENAME

    if not repo_manifest.exists() or not model_path.exists():
        raise TtsModelNotCachedError(
            f"Silero TTS model not cached ({repo_manifest} and/or "
            f"{model_path} missing). Run `python setup_tts_model.py` once "
            "(requires network) before starting the offline runtime."
        )

    if not Path(_MODELS_MANIFEST_FILENAME).exists():
        raise TtsModelNotCachedError(
            f"{repo_manifest} exists, but the process's current working "
            f"directory has no {_MODELS_MANIFEST_FILENAME} - silero_tts() "
            "looks for it relative to the working directory, not next to "
            "this file. Launch the app with the repo root as the working "
            "directory."
        )


def _resolve_existing_path(path: str | Path, description: str) -> Path:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"{description} does not exist: {resolved}")
    if not resolved.is_file():
        raise FileNotFoundError(f"{description} is not a file: {resolved}")
    return resolved


def _resolve_piper_config(model_path: Path, config_path: str | Path | None) -> Path:
    if config_path is not None:
        return _resolve_existing_path(config_path, "Piper config file")

    derived = Path(f"{model_path}.json")
    if derived.exists() and derived.is_file():
        return derived
    raise FileNotFoundError(
        f"No Piper config file was supplied and the default {derived} was not found."
    )


def _load_piper_voice(*, model_path: Path, config_path: Path, use_cuda: bool):
    from piper.voice import PiperVoice

    return PiperVoice.load(
        model_path=str(model_path),
        config_path=str(config_path),
        use_cuda=use_cuda,
    )


def _piper_chunks_to_wav_bytes(chunks) -> bytes:
    chunk_list = list(chunks)
    if not chunk_list:
        raise RuntimeError("Piper returned no audio chunks")

    buffer = io.BytesIO()
    sample_rate: int | None = None
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        for chunk in chunk_list:
            current_sample_rate = int(chunk.sample_rate)
            if sample_rate is None:
                sample_rate = current_sample_rate
                wav_file.setframerate(sample_rate)
            elif current_sample_rate != sample_rate:
                raise RuntimeError(
                    f"Piper returned mixed sample rates: {sample_rate} and "
                    f"{current_sample_rate}"
                )
            wav_file.writeframes(chunk.audio_int16_array.tobytes())
    return buffer.getvalue()


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


def normalize_numbers(text: str) -> str:
    """Converts digit runs (integers and single-decimal numbers, with
    either '.' or ',' as the decimal separator) to Russian words, e.g.
    "3.14" -> "три целых четырнадцать сотых". Does not handle thousands
    separators, dates, currency, or other richer number formats - out of
    scope for what this task needs."""

    def replace(match: re.Match) -> str:
        token = match.group().replace(",", ".")
        value = float(token) if "." in token else int(token)
        return num2words(value, lang="ru")

    return _NUMBER_RE.sub(replace, text)


_LATIN_RUN_RE = re.compile(r"[a-zA-Z]+")

_LATIN_DIGRAPHS = {"sh": "ш", "ch": "ч", "ck": "к", "ph": "ф", "qu": "кв", "th": "т"}

_LATIN_LETTERS = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "w": "в", "x": "кс", "y": "й", "z": "з",
}


def transliterate_latin(text: str) -> str:
    """Best-effort phonetic transliteration of Latin-script runs into
    Cyrillic, e.g. "gemma" -> "гемма". Crude per-letter/digraph mapping,
    not linguistically rigorous (English spelling isn't phonetic) - done
    because the alternative is worse: verified live, Silero's v3_1_ru
    symbol set (model.symbols) has no Latin characters at all, so without
    this, Latin-script words are silently stripped and never voiced
    ("gemma4" - the digit was spoken via normalize_numbers, the word
    was not, same root cause as the digit-stripping bug)."""

    def replace(match: re.Match) -> str:
        word = match.group().lower()
        pieces = []
        i = 0
        while i < len(word):
            digraph = word[i : i + 2]
            if digraph in _LATIN_DIGRAPHS:
                pieces.append(_LATIN_DIGRAPHS[digraph])
                i += 2
                continue
            pieces.append(_LATIN_LETTERS.get(word[i], word[i]))
            i += 1
        return "".join(pieces)

    return _LATIN_RUN_RE.sub(replace, text)


# Common Russian abbreviations that end in a period but do not end a
# sentence. Not exhaustive - deliberately biased toward under-splitting:
# a missed boundary just merges two sentences into one slightly longer
# utterance; a false boundary would cut off mid-abbreviation and produce
# broken speech, which is the worse failure mode.
_ABBREVIATIONS = {
    "т.е", "т.д", "т.п", "др", "пр", "см", "мм", "кг", "г", "гг",
    "им", "проф", "акад", "руб", "коп", "стр", "рис", "табл", "гл",
    "ст", "разд", "тов", "г-н", "г-жа",
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
            self._buffer = self._buffer[match.end():]
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

    def _feed_piece(self, units: list[tuple[str, str]], language: str, text: str) -> None:
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


class SileroEngine:
    def __init__(self, settings: TtsSettings) -> None:
        self._settings = settings
        self._model = None

    async def synthesize(self, text: str, language: str = DEFAULT_LANGUAGE) -> bytes:
        del language  # any language goes through the transliteration fallback
        model = await self._ensure_model()
        audio_tensor = await asyncio.to_thread(
            model.apply_tts,
            text=transliterate_latin(normalize_numbers(text)),
            speaker=self._settings.voice,
            sample_rate=SAMPLE_RATE,
        )
        return samples_to_wav_bytes(audio_tensor, SAMPLE_RATE)

    async def _ensure_model(self):
        if self._model is None:
            self._model = await asyncio.to_thread(self._load_model)
        return self._model

    @staticmethod
    def _load_model():
        import silero

        _ensure_model_cached(silero)
        model, _ = silero.silero_tts(language="ru", speaker="v3_1_ru")
        return model


class PiperEngine:
    def __init__(
        self,
        model_path: str | Path,
        *,
        config_path: str | Path | None = None,
        use_cuda: bool = False,
        voice_loader: VoiceLoader = _load_piper_voice,
    ) -> None:
        self.model_path = _resolve_existing_path(model_path, "Piper model file")
        self.config_path = _resolve_piper_config(self.model_path, config_path)
        self._use_cuda = use_cuda
        self._voice_loader = voice_loader
        self._voice = None

    async def synthesize(self, text: str, language: str = DEFAULT_LANGUAGE) -> bytes:
        del language
        voice = await self._ensure_voice()
        return await asyncio.to_thread(_piper_chunks_to_wav_bytes, voice.synthesize(text))

    async def _ensure_voice(self):
        if self._voice is None:
            self._voice = await asyncio.to_thread(
                self._voice_loader,
                model_path=self.model_path,
                config_path=self.config_path,
                use_cuda=self._use_cuda,
            )
        return self._voice


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


# The languages charset segmentation actually emits (language_segments.py):
# any Latin run becomes an ENGLISH unit regardless of configuration, so a
# bilingual routing table must cover both or it is guaranteed to fail at
# runtime on the first English word.
_ROUTED_LANGUAGES = (DEFAULT_LANGUAGE, ENGLISH)


def _is_default_silero_only(settings: TtsSettings) -> bool:
    return settings.languages == {
        DEFAULT_LANGUAGE: TtsLanguageSettings(engine="silero", model=SILERO_MODEL)
    }


def _routes_share_one_engine(settings: TtsSettings) -> bool:
    return len({route.engine for route in settings.languages.values()}) == 1


def _build_silero_engine(settings: TtsSettings, route: TtsLanguageSettings) -> "TtsEngine":
    if route.model != SILERO_MODEL:
        raise ValueError(
            f"SileroEngine supports only model {SILERO_MODEL!r} (its cache "
            f"filenames and speaker are bound to it), got {route.model!r}"
        )
    return SileroEngine(settings)


def _default_engine_builders(settings: TtsSettings) -> dict[str, EngineBuilder]:
    return {
        "silero": lambda route: _build_silero_engine(settings, route),
        "piper": lambda route: PiperEngine(route.model),
    }


def build_tts_engine(
    settings: TtsSettings,
    engine_builders: dict[str, EngineBuilder] | None = None,
) -> TtsEngine:
    if _is_default_silero_only(settings):
        return SileroEngine(settings)

    missing = [
        language
        for language in _ROUTED_LANGUAGES
        if language not in settings.languages
    ]
    if missing:
        raise ValueError(
            "Configured TTS language routes must cover "
            f"{', '.join(_ROUTED_LANGUAGES)}: charset segmentation emits all "
            f"of them regardless of configuration. Missing: {', '.join(missing)}. "
            "Add the missing [tts.languages.*] route or remove the section to "
            "use the Silero-only default."
        )

    builders = engine_builders or _default_engine_builders(settings)
    engines: dict[str, TtsEngine] = {}
    for language, route in settings.languages.items():
        try:
            builder = builders[route.engine]
        except KeyError as exc:
            available = ", ".join(sorted(builders))
            raise ValueError(
                f"Unsupported TTS engine for configured routing: {route.engine!r}. "
                f"Available builders: {available}"
            ) from exc
        engines[language] = builder(route)
    return BilingualTtsEngine(engines)


class TtsOutput:
    def __init__(
        self,
        settings: TtsSettings,
        engine: TtsEngine | None = None,
        play: Callable[[bytes], Awaitable[None]] | None = None,
        playback_lock: asyncio.Lock | None = None,
    ) -> None:
        self._settings = settings
        # Carrying a short language-switch remainder into the next unit is
        # only safe when one engine voices everything; with per-language
        # engines it would hand text to an engine that cannot pronounce it
        # (see _CONNECTIVE_MAX_WORD_CHARS).
        self._units = SpeechUnitBuffer(
            carry_connectives=_routes_share_one_engine(settings)
        )
        self._engine = engine or build_tts_engine(settings)
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

    async def _synthesize_and_submit(self, index: int, text: str, language: str) -> None:
        try:
            audio = await self._engine.synthesize(text, language)
        except Exception:
            # OrderedPlayback requires every index to arrive or all later
            # units stay buffered forever; a failed unit must therefore
            # still advance the order. Losing one sentence of speech is
            # recoverable, silently losing all speech for the rest of the
            # session is not.
            logger.exception(
                "TTS synthesis failed for unit %d (language=%r); "
                "skipping its playback",
                index,
                language,
            )
            await self._playback.submit(index, None)
            return
        await self._playback.submit(index, audio)

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
