"""Speech-to-text engine wrappers of spike v2.1.0-5.

Each engine imports its own heavy package lazily inside `load`, so this module
imports in any environment. The engines live in separate virtual environments
(`.venv-stt-whisper`, `.venv-stt-gigaam`); nothing here is a Jarvis runtime
dependency.
"""

from __future__ import annotations

import os
import subprocess
import sysconfig
import threading
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from manual.personal_proxy.stt_scoring import Engine

SAMPLE_RATE = 16000
WHISPER_MODEL = "large-v3-turbo"
GIGAAM_MODEL = "gigaam-v3-e2e-rnnt"


class SpeechEngine(Protocol):
    def load(self) -> None: ...

    def transcribe(self, samples: np.ndarray) -> str: ...


def _add_nvidia_dll_directories() -> None:
    """CTranslate2 on Windows finds cuBLAS and cuDNN only through the PATH."""
    base = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    for directory in sorted(base.glob("*/bin")):
        os.add_dll_directory(str(directory))
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")


@dataclass
class WhisperEngine:
    language: str | None
    device: str
    compute_type: str
    _model: Any = None

    def load(self) -> None:
        if self.device == "cuda":
            _add_nvidia_dll_directories()
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            WHISPER_MODEL, device=self.device, compute_type=self.compute_type
        )

    def transcribe(self, samples: np.ndarray) -> str:
        segments, _ = self._model.transcribe(
            samples,
            language=self.language,
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


@dataclass
class GigaamEngine:
    device: str
    quantization: str | None
    _model: Any = None

    def load(self) -> None:
        import onnx_asr
        import onnxruntime

        providers = ["CPUExecutionProvider"]
        if self.device == "cuda":
            onnxruntime.preload_dlls()
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._model = onnx_asr.load_model(
            GIGAAM_MODEL, quantization=self.quantization, providers=providers
        )

    def transcribe(self, samples: np.ndarray) -> str:
        return str(self._model.recognize(samples, sample_rate=SAMPLE_RATE)).strip()


def make_engine(engine: Engine) -> SpeechEngine:
    if engine is Engine.WHISPER_RU:
        return WhisperEngine("ru", "cuda", "float16")
    if engine is Engine.WHISPER_AUTO:
        return WhisperEngine(None, "cuda", "float16")
    if engine is Engine.WHISPER_RU_CPU:
        return WhisperEngine("ru", "cpu", "int8")
    if engine is Engine.GIGAAM:
        return GigaamEngine("cuda", None)
    return GigaamEngine("cpu", "int8")


def package_versions() -> dict[str, str]:
    found: dict[str, str] = {}
    for name in (
        "faster-whisper",
        "ctranslate2",
        "onnx-asr",
        "onnxruntime-gpu",
        "onnxruntime",
    ):
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return found


def gpu_memory_used_mib() -> int | None:
    try:
        output = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return int(output.strip().splitlines()[0])
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        return None


class PeakGpuMemory:
    """Samples the machine's used GPU memory from a thread; `peak` is the
    maximum seen while the context was open."""

    def __init__(self, interval_seconds: float = 0.25) -> None:
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self.peak: int | None = None

    def _sample(self) -> None:
        while not self._stop.is_set():
            used = gpu_memory_used_mib()
            if used is not None and (self.peak is None or used > self.peak):
                self.peak = used
            time.sleep(self._interval)

    def __enter__(self) -> PeakGpuMemory:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()
