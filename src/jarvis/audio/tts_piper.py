"""Piper-specific model loading, synthesis settings, and WAV encoding."""

import asyncio
import io
import wave
from pathlib import Path
from typing import Protocol

from jarvis.audio.tts import TtsEngineLoadError
from jarvis.core.config import PiperTtsSettings


class VoiceLoader(Protocol):
    def __call__(
        self,
        *,
        model_path: Path,
        config_path: Path,
        use_cuda: bool,
        espeak_data_dir: str | None,
        download_dir: str | None,
    ) -> object: ...


def resolve_existing_path(path: str | Path, description: str) -> Path:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"{description} does not exist: {resolved}")
    if not resolved.is_file():
        raise FileNotFoundError(f"{description} is not a file: {resolved}")
    return resolved


def resolve_piper_config(model_path: Path, config_path: str | Path | None) -> Path:
    if config_path is not None:
        return resolve_existing_path(config_path, "Piper config file")

    derived = Path(f"{model_path}.json")
    if derived.exists() and derived.is_file():
        return derived
    raise FileNotFoundError(
        f"No Piper config file was supplied and the default {derived} was not found."
    )


def load_piper_voice(
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
    return PiperVoice.load(**kwargs)


def piper_chunks_to_wav_bytes(chunks) -> bytes:
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


class PiperEngine:
    def __init__(
        self,
        route: PiperTtsSettings,
        *,
        voice_loader: VoiceLoader = load_piper_voice,
    ) -> None:
        self._route = route
        self._voice_loader = voice_loader
        self._voice = None
        self._synthesis_config = None
        self._load_error: TtsEngineLoadError | None = None
        self._load_lock = asyncio.Lock()

    async def synthesize(self, text: str, language: str = "ru") -> bytes:
        del language
        voice = await self._ensure_voice()
        return await asyncio.to_thread(
            piper_chunks_to_wav_bytes,
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

        model_path = resolve_existing_path(self._route.model, "Piper model file")
        config_path = resolve_piper_config(model_path, self._route.config_path)
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
