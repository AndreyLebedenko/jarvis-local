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
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import sounddevice as sd
import soundfile as sf
from num2words import num2words

from jarvis.audio.language_segments import (
    DEFAULT_LANGUAGE,
    ENGLISH,
    CharsetLanguageStream,
)
from jarvis.audio.utils import samples_to_wav_bytes
from jarvis.core.bus import EventBus
from jarvis.core.config import (
    PiperTtsSettings,
    SileroTtsSettings,
    TtsLanguageSettings,
    TtsSettings,
)
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


SAMPLE_RATE = 48000
FINAL_PLAYBACK_TAIL_SECONDS = 1.0

_MODELS_MANIFEST_FILENAME = "latest_silero_models.yml"

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


class TtsModelNotCachedError(RuntimeError):
    pass


class TtsEngineLoadError(RuntimeError):
    def __init__(self, engine: str, model: str, detail: str) -> None:
        super().__init__(f"{engine} model {model!r} failed to load: {detail}")
        self.engine = engine
        self.model = model
        self.detail = detail


class VoiceLoader(Protocol):
    def __call__(
        self,
        *,
        model_path: Path,
        config_path: Path,
        use_cuda: bool,
        espeak_data_dir: str | None,
        download_dir: str | None,
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
    Silero/ru + Piper/en production setup is not a required mapping. Child
    engines may ignore the routing hint because their typed route already
    selects the concrete model language; Russian-only normalization remains a
    Silero route concern."""

    async def synthesize(self, text: str, language: str = DEFAULT_LANGUAGE) -> bytes:
        pass


def _ensure_model_cached(
    silero_module,
    route: SileroTtsSettings,
    repo_root: Path | None = None,
) -> None:
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
    repo_root = repo_root or Path(__file__).resolve().parents[3]
    repo_manifest = repo_root / _MODELS_MANIFEST_FILENAME
    if not repo_manifest.is_file():
        raise TtsModelNotCachedError(
            f"Silero model manifest is missing: {repo_manifest}. Run "
            "`python setup_tts_model.py` once "
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

    from omegaconf import OmegaConf

    manifest = OmegaConf.load(repo_manifest)
    try:
        model_config = manifest.tts_models[route.language][route.model].latest
    except (AttributeError, KeyError, TypeError) as exc:
        raise TtsModelNotCachedError(
            f"Silero model {route.model!r} for language {route.language!r} is "
            f"not present in {repo_manifest}"
        ) from exc
    model_url = model_config.get("package") or model_config.get("jit")
    if not model_url:
        raise TtsModelNotCachedError(
            f"Silero model {route.model!r} has no package or jit asset in "
            f"{repo_manifest}"
        )
    model_path = Path(silero_module.__file__).parent / "model" / Path(model_url).name
    if not model_path.is_file():
        raise TtsModelNotCachedError(
            f"Silero TTS model not cached: {model_path}. Run "
            f"`python setup_tts_model.py --language {route.language} "
            f"--model {route.model}` once (requires network) before starting "
            "the offline runtime."
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


def _load_piper_voice(
    *,
    model_path: Path,
    config_path: Path,
    use_cuda: bool,
    espeak_data_dir: str | None,
    download_dir: str | None,
):
    from piper.voice import PiperVoice

    kwargs = {
        "model_path": str(model_path),
        "config_path": str(config_path),
        "use_cuda": use_cuda,
    }
    if espeak_data_dir is not None:
        kwargs["espeak_data_dir"] = espeak_data_dir
    if download_dir is not None:
        kwargs["download_dir"] = download_dir
    return PiperVoice.load(
        **kwargs,
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
    "a": "а",
    "b": "б",
    "c": "к",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "г",
    "h": "х",
    "i": "и",
    "j": "дж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "к",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "кс",
    "y": "й",
    "z": "з",
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


class _PackageSileroModel:
    def __init__(self, model, route: SileroTtsSettings) -> None:
        self._model = model
        self._route = route

    def synthesize(self, text: str):
        kwargs = {
            "text": text,
            "speaker": self._route.speaker,
            "sample_rate": self._route.sample_rate,
        }
        if self._route.put_accent is not None:
            kwargs["put_accent"] = self._route.put_accent
        if self._route.put_yo is not None:
            kwargs["put_yo"] = self._route.put_yo
        return self._model.apply_tts(**kwargs)


class _JitSileroModel:
    def __init__(
        self,
        model,
        symbols: str,
        native_sample_rate: int,
        apply_tts: Callable,
        route: SileroTtsSettings,
    ) -> None:
        if route.sample_rate != native_sample_rate:
            raise ValueError(
                f"Silero JIT model {route.model!r} requires sample_rate "
                f"{native_sample_rate}, got {route.sample_rate}"
            )
        self._model = model
        self._symbols = symbols
        self._sample_rate = native_sample_rate
        self._apply_tts = apply_tts

    def synthesize(self, text: str):
        import torch

        audios = self._apply_tts(
            texts=[text],
            model=self._model,
            sample_rate=self._sample_rate,
            symbols=self._symbols,
            device=torch.device("cpu"),
        )
        if not audios:
            raise RuntimeError("Silero returned no audio")
        return audios[0]


def _load_silero_model(route: SileroTtsSettings):
    import silero

    _ensure_model_cached(silero, route)
    loaded = silero.silero_tts(language=route.language, speaker=route.model)
    if len(loaded) == 2:
        model, _metadata = loaded
        return _PackageSileroModel(model, route)
    if len(loaded) == 5:
        model, symbols, native_sample_rate, _example, apply_tts = loaded
        return _JitSileroModel(model, symbols, native_sample_rate, apply_tts, route)
    raise RuntimeError(
        f"Silero returned an unsupported loader result for {route.model!r}"
    )


class SileroEngine:
    def __init__(
        self,
        route: SileroTtsSettings,
        *,
        model_loader: Callable[[SileroTtsSettings], object] = _load_silero_model,
    ) -> None:
        self._route = route
        self._model_loader = model_loader
        self._model = None
        self._load_error: TtsEngineLoadError | None = None
        self._load_lock = asyncio.Lock()

    async def synthesize(self, text: str, language: str = DEFAULT_LANGUAGE) -> bytes:
        del language  # the typed route owns the concrete Silero model language
        model = await self._ensure_model()
        prepared = text
        if self._route.language == "ru":
            prepared = transliterate_latin(normalize_numbers(text))
        audio_tensor = await asyncio.to_thread(
            model.synthesize,
            prepared,
        )
        return samples_to_wav_bytes(audio_tensor, self._route.sample_rate)

    async def _ensure_model(self):
        if self._load_error is not None:
            raise self._load_error
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._load_error is not None:
                raise self._load_error
            if self._model is not None:
                return self._model
            try:
                self._model = await asyncio.to_thread(self._model_loader, self._route)
            except Exception as exc:
                self._load_error = TtsEngineLoadError(
                    self._route.engine, self._route.model, str(exc)
                )
                raise self._load_error from exc
        return self._model


class PiperEngine:
    def __init__(
        self,
        route: PiperTtsSettings,
        *,
        voice_loader: VoiceLoader = _load_piper_voice,
    ) -> None:
        self._route = route
        self._voice_loader = voice_loader
        self._voice = None
        self._synthesis_config = None
        self._load_error: TtsEngineLoadError | None = None
        self._load_lock = asyncio.Lock()

    async def synthesize(self, text: str, language: str = DEFAULT_LANGUAGE) -> bytes:
        del language
        voice = await self._ensure_voice()
        return await asyncio.to_thread(
            _piper_chunks_to_wav_bytes,
            voice.synthesize(text, self._synthesis_config),
        )

    async def _ensure_voice(self):
        if self._load_error is not None:
            raise self._load_error
        if self._voice is not None:
            return self._voice
        async with self._load_lock:
            if self._load_error is not None:
                raise self._load_error
            if self._voice is not None:
                return self._voice
            try:
                self._voice, self._synthesis_config = await asyncio.to_thread(
                    self._load_voice
                )
            except Exception as exc:
                self._load_error = TtsEngineLoadError(
                    self._route.engine, self._route.model, str(exc)
                )
                raise self._load_error from exc
        return self._voice

    def _load_voice(self):
        from piper.config import SynthesisConfig

        model_path = _resolve_existing_path(self._route.model, "Piper model file")
        config_path = _resolve_piper_config(model_path, self._route.config_path)
        voice = self._voice_loader(
            model_path=model_path,
            config_path=config_path,
            use_cuda=self._route.use_cuda,
            espeak_data_dir=self._route.espeak_data_dir,
            download_dir=self._route.download_dir,
        )
        synthesis_config = SynthesisConfig(
            speaker_id=self._route.speaker_id,
            length_scale=self._route.length_scale,
            noise_scale=self._route.noise_scale,
            noise_w_scale=self._route.noise_w_scale,
            normalize_audio=self._route.normalize_audio,
            volume=self._route.volume,
        )
        return voice, synthesis_config


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
    return settings.languages == {DEFAULT_LANGUAGE: SileroTtsSettings()}


def _routes_share_one_engine(settings: TtsSettings) -> bool:
    return len({route.engine for route in settings.languages.values()}) == 1


def _default_engine_builders() -> dict[str, EngineBuilder]:
    return {
        "silero": lambda route: SileroEngine(route),
        "piper": lambda route: PiperEngine(route),
    }


def build_tts_engine(
    settings: TtsSettings,
    engine_builders: dict[str, EngineBuilder] | None = None,
) -> TtsEngine:
    if _is_default_silero_only(settings):
        return SileroEngine(SileroTtsSettings())

    missing = [
        language for language in _ROUTED_LANGUAGES if language not in settings.languages
    ]
    if missing:
        raise ValueError(
            "Configured TTS language routes must cover "
            f"{', '.join(_ROUTED_LANGUAGES)}: charset segmentation emits all "
            f"of them regardless of configuration. Missing: {', '.join(missing)}. "
            "Add the missing [tts.languages.*] route or remove the section to "
            "use the Silero-only default."
        )

    builders = engine_builders or _default_engine_builders()
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
