"""WAV inputs of the personal-proxy spike: control signals and the corpus manifest.

The recorder writes one WAV per utterance plus a manifest of SHA-256 values;
the harness verifies the directory against that manifest before it uses it, so
a replaced or missing recording is refused instead of silently measured.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from manual.personal_proxy_corpus import (
    CONTROL_SAMPLE_RATE,
    CORPUS,
    NOISE_RMS,
    NOISE_SEED,
    Control,
    ControlKind,
    corpus_fingerprint,
)

MANIFEST_NAME = "manifest.json"


class WavDirectoryError(RuntimeError):
    pass


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def control_audio(control: Control) -> bytes | None:
    """The WAV bytes of a control, or None for the no-media control."""
    if control.kind is ControlKind.NO_MEDIA:
        return None
    samples = int(control.seconds * CONTROL_SAMPLE_RATE)
    if control.kind is ControlKind.DIGITAL_SILENCE:
        signal = np.zeros(samples, dtype=np.float32)
    else:
        rng = np.random.default_rng(NOISE_SEED)
        signal = np.clip(rng.normal(0.0, NOISE_RMS, samples), -1.0, 1.0).astype(
            np.float32
        )
    buffer = io.BytesIO()
    sf.write(buffer, signal, CONTROL_SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def wav_duration_seconds(data: bytes) -> float:
    info = sf.info(io.BytesIO(data))
    return info.frames / info.samplerate


@dataclass(frozen=True)
class ManifestEntry:
    utterance_id: str
    sha256: str
    bytes: int
    duration_seconds: float


def write_manifest(directory: Path, entries: list[ManifestEntry]) -> Path:
    path = directory / MANIFEST_NAME
    document = {
        "corpus_fingerprint": corpus_fingerprint(),
        "entries": {
            entry.utterance_id: {
                "sha256": entry.sha256,
                "bytes": entry.bytes,
                "duration_seconds": entry.duration_seconds,
            }
            for entry in entries
        },
    }
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def wav_path(directory: Path, utterance_id: str) -> Path:
    return directory / f"{utterance_id}.wav"


class WavDirectory:
    """A verified recording directory: every corpus utterance present and
    matching the manifest, recorded against the same frozen corpus."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._manifest = self._read_manifest()
        self._audio = {u.utterance_id: self._load(u.utterance_id) for u in CORPUS}

    def _read_manifest(self) -> dict:
        path = self._directory / MANIFEST_NAME
        if not path.exists():
            raise WavDirectoryError(f"no {MANIFEST_NAME} in {self._directory}")
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["corpus_fingerprint"] != corpus_fingerprint():
            raise WavDirectoryError(
                "the recordings were made against a different corpus; record again"
            )
        return document["entries"]

    def _load(self, utterance_id: str) -> bytes:
        path = wav_path(self._directory, utterance_id)
        entry = self._manifest.get(utterance_id)
        if entry is None or not path.exists():
            raise WavDirectoryError(f"missing recording: {utterance_id}")
        data = path.read_bytes()
        if sha256_hex(data) != entry["sha256"]:
            raise WavDirectoryError(f"{utterance_id}.wav differs from the manifest")
        return data

    def audio_for(self, utterance_id: str) -> bytes:
        return self._audio[utterance_id]

    def duration_for(self, utterance_id: str) -> float:
        return self._manifest[utterance_id]["duration_seconds"]

    def set_hash(self) -> str:
        joined = "".join(
            f"{uid}:{entry['sha256']};" for uid, entry in sorted(self._manifest.items())
        )
        return sha256_hex(joined.encode("ascii"))
