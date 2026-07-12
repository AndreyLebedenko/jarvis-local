"""Silero-specific TTS loading, preprocessing, and synthesis adapter."""

import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from num2words import num2words

from jarvis.audio.tts import TtsEngineLoadError
from jarvis.audio.utils import samples_to_wav_bytes
from jarvis.core.config import SileroTtsSettings

_MODELS_MANIFEST_FILENAME = "latest_silero_models.yml"
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
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


class TtsModelNotCachedError(RuntimeError):
    pass


class LoadedSileroModel(Protocol):
    def synthesize(self, text: str): ...


class SileroModelLoader(Protocol):
    def __call__(self, route: SileroTtsSettings) -> LoadedSileroModel: ...


def ensure_model_cached(
    silero_module,
    route: SileroTtsSettings,
    repo_root: Path | None = None,
) -> None:
    """Reject a missing local model before Silero can download it."""
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


def normalize_numbers(text: str) -> str:
    """Convert numeric runs to Russian words for models without digits."""

    def replace(match: re.Match) -> str:
        token = match.group().replace(",", ".")
        value = float(token) if "." in token else int(token)
        return num2words(value, lang="ru")

    return _NUMBER_RE.sub(replace, text)


def transliterate_latin(text: str) -> str:
    """Best-effort phonetic transliteration for Russian-only models."""

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


class PackageSileroModel:
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


class JitSileroModel:
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


def load_silero_model(route: SileroTtsSettings) -> LoadedSileroModel:
    import silero

    ensure_model_cached(silero, route)
    loaded = silero.silero_tts(language=route.language, speaker=route.model)
    if len(loaded) == 2:
        model, _metadata = loaded
        return PackageSileroModel(model, route)
    if len(loaded) == 5:
        model, symbols, native_sample_rate, _example, apply_tts = loaded
        return JitSileroModel(model, symbols, native_sample_rate, apply_tts, route)
    raise RuntimeError(
        f"Silero returned an unsupported loader result for {route.model!r}"
    )


class SileroEngine:
    def __init__(
        self,
        route: SileroTtsSettings,
        *,
        model_loader: SileroModelLoader = load_silero_model,
    ) -> None:
        self._route = route
        self._model_loader = model_loader
        self._model: LoadedSileroModel | None = None
        self._load_error: TtsEngineLoadError | None = None
        self._load_lock = asyncio.Lock()

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        del language
        model = await self._ensure_model()
        prepared = text
        if self._route.language == "ru":
            prepared = transliterate_latin(normalize_numbers(text))
        audio_tensor = await asyncio.to_thread(model.synthesize, prepared)
        return samples_to_wav_bytes(audio_tensor, self._route.sample_rate)

    async def _ensure_model(self) -> LoadedSileroModel:
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
