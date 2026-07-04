"""Sentence-buffered Silero TTS output.

Buffers backend.py's streamed response tokens to sentence boundaries,
synthesizes each completed sentence (Russian, Silero TTS), and plays
them back in order while generation continues - per PROJECT.md's
"sentence-level streaming is mandatory" requirement for tts.py.

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
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

import sounddevice as sd
import soundfile as sf
from num2words import num2words

from audio_utils import samples_to_wav_bytes
from backend import ResponseComplete, ResponseToken
from config import TtsSettings

SAMPLE_RATE = 48000

# Filenames Silero's own downloader produces for this exact model/speaker
# (see setup_tts_model.py). Hardcoded rather than parsed from the models
# manifest, to avoid an extra dependency (omegaconf) for a single, fixed
# model choice - revisit if the speaker/model choice ever changes.
_MODELS_MANIFEST_FILENAME = "latest_silero_models.yml"
_MODEL_CACHE_FILENAME = "v3_1_ru.pt"

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


class TtsModelNotCachedError(RuntimeError):
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


class OrderedPlayback:
    """Plays (index, audio) results in strict index order, regardless of
    the order they are submitted in - so concurrent synthesis of several
    sentences can never cause a later one to play before an earlier one.
    """

    def __init__(self, player: Callable[[bytes], Awaitable[None]]) -> None:
        self._player = player
        self._pending: dict[int, bytes] = {}
        self._next_index = 0
        self._lock = asyncio.Lock()

    async def submit(self, index: int, audio: bytes) -> None:
        async with self._lock:
            self._pending[index] = audio
            while self._next_index in self._pending:
                ready = self._pending.pop(self._next_index)
                await self._player(ready)
                self._next_index += 1


class TtsOutput:
    def __init__(
        self,
        settings: TtsSettings,
        synthesize: Callable[[str], Awaitable[bytes]] | None = None,
        play: Callable[[bytes], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._buffer = SentenceBuffer()
        self._synthesize = synthesize or self._default_synthesize
        self._playback = OrderedPlayback(play or self._default_play)
        self._next_index = 0
        self._model = None
        self._pending_tasks: set[asyncio.Task] = set()

    async def on_token(self, event: ResponseToken) -> None:
        for sentence in self._buffer.feed(event.text):
            self._schedule(sentence)

    async def on_response_complete(self, event: ResponseComplete) -> None:
        trailing = self._buffer.flush()
        if trailing:
            self._schedule(trailing)

    async def wait_for_pending(self) -> None:
        """Awaits every synthesis/playback task scheduled so far. Useful
        both for tests and for a graceful shutdown that lets in-flight
        speech finish rather than cutting it off mid-sentence."""
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks)

    def _schedule(self, sentence: str) -> None:
        index = self._next_index
        self._next_index += 1
        task = asyncio.create_task(self._synthesize_and_submit(index, sentence))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _synthesize_and_submit(self, index: int, sentence: str) -> None:
        audio = await self._synthesize(sentence)
        await self._playback.submit(index, audio)

    async def _default_synthesize(self, sentence: str) -> bytes:
        model = await self._ensure_model()
        audio_tensor = await asyncio.to_thread(
            model.apply_tts,
            text=normalize_numbers(sentence),
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

    @staticmethod
    async def _default_play(wav_bytes: bytes) -> None:
        import io

        data, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        await asyncio.to_thread(sd.play, data, sample_rate)
        await asyncio.to_thread(sd.wait)
