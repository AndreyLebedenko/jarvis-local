"""Whisper large-v3-turbo through faster-whisper, run with the settings the
v2.1.0 spikes measured."""

from __future__ import annotations

import os
import site
import sysconfig
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.core.config import PersonalProxySettings
from jarvis.personal_proxy.stt.stt_engine import (
    MissingSpeechDependencyError,
    SpeechDeviceError,
    SpeechModelUnavailableError,
)
from jarvis.personal_proxy.stt.stt_result import Segment, Transcription, Word

BEAM_SIZE = 5
COMPUTE_TYPE_BY_DEVICE = {"cuda": "float16", "cpu": "int8"}
SETUP_COMMAND = "python setup_stt_model.py"


_registered_dll_directories: dict[str, object] = {}


def _site_packages_directories() -> list[Path]:
    candidates = [
        Path(sysconfig.get_paths()["purelib"]),
        Path(sysconfig.get_paths()["platlib"]),
        Path(site.getusersitepackages()),
    ]
    return list(dict.fromkeys(candidates))


def _add_nvidia_dll_directories(site_packages: Sequence[Path] | None = None) -> None:
    """CTranslate2 on Windows finds cuBLAS and cuDNN only through the PATH.
    The handles stay in a module-level dict: a closed handle removes the entry."""
    for base in (
        site_packages if site_packages is not None else _site_packages_directories()
    ):
        for directory in sorted((base / "nvidia").glob("*/bin")):
            key = str(directory)
            if key in _registered_dll_directories:
                continue
            _registered_dll_directories[key] = os.add_dll_directory(key)
            os.environ["PATH"] = key + os.pathsep + os.environ.get("PATH", "")


def _import_whisper_model(device: str) -> Any:
    try:
        if device == "cuda":
            _add_nvidia_dll_directories()
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise MissingSpeechDependencyError(
            "faster-whisper is not installed; run 'pip install -r requirements-stt.txt'"
        ) from error
    except OSError as error:
        raise SpeechDeviceError(
            _device_message("load faster-whisper", device, error)
        ) from error
    return WhisperModel


def _device_message(action: str, device: str, error: Exception) -> str:
    hint = (
        "check the CUDA 12 libraries (cuBLAS, cuDNN from requirements-stt.txt) and the "
        'GPU driver, or set stt_device = "cpu" under [personal_proxy]'
        if device == "cuda"
        else "check the model's compute type and the available memory"
    )
    return f"cannot {action} on {device!r} ({type(error).__name__}: {error}); {hint}"


def load_whisper_model(model_name: str, device: str) -> Any:
    """Loads from the local cache only: the runtime never downloads weights."""
    whisper_model = _import_whisper_model(device)
    try:
        return whisper_model(
            model_name,
            device=device,
            compute_type=COMPUTE_TYPE_BY_DEVICE[device],
            local_files_only=True,
        )
    except (FileNotFoundError, ValueError) as error:
        raise SpeechModelUnavailableError(
            f"the speech model {model_name!r} is not available from local files "
            f"({type(error).__name__}: {error}); if it is not cached yet, run "
            f"'{SETUP_COMMAND}' once with network access"
        ) from error
    except Exception as error:
        raise SpeechDeviceError(
            _device_message(f"load the speech model {model_name!r}", device, error)
        ) from error


class FasterWhisperEngine:
    def __init__(self, settings: PersonalProxySettings) -> None:
        self._language = settings.stt_language
        self._model = load_whisper_model(settings.stt_model, settings.stt_device)

    def transcribe(self, clip: np.ndarray) -> Transcription:
        segments, _ = self._model.transcribe(
            clip,
            language=self._language,
            beam_size=BEAM_SIZE,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
            word_timestamps=True,
        )
        found = list(segments)
        return Transcription(
            text=" ".join(segment.text.strip() for segment in found).strip(),
            words=tuple(
                Word(word.word.strip(), word.start, word.end, word.probability)
                for segment in found
                for word in (segment.words or [])
            ),
            segments=tuple(
                Segment(
                    segment.text.strip(),
                    segment.avg_logprob,
                    segment.no_speech_prob,
                    segment.compression_ratio,
                )
                for segment in found
            ),
        )
