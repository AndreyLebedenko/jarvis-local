#!/usr/bin/env python3
"""Human-run comparison of Ollama audio request shapes across model variants.

The experiment asks every condition to transcribe the same existing WAV. It
changes only explicit system-message presence/content, no-op tool presence, or
media presence. Results are JSONL and retain raw responses plus payload/model
provenance. This script talks to live local Ollama and therefore must be run by
the human under the repository testing protocol.

Usage:
  python -m manual.manual_check_audio_request_shape
  python -m manual.manual_check_audio_request_shape --repeats 3
  python -m manual.manual_check_audio_request_shape --num-gpu 99
  python -m manual.manual_check_audio_request_shape --wav-subtype float32
  python -m manual.manual_check_audio_request_shape --peak-target 0.89
  python -m manual.manual_check_audio_request_shape --min-duration-seconds 2.5
  python -m manual.manual_check_audio_request_shape --padding-mode white-noise
  python -m manual.manual_check_audio_request_shape --temperature 0.7
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import random
import subprocess
import time
import unicodedata
import wave
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from jarvis.app import _compose_effective_system_prompt
from jarvis.core.bus import EventBus
from jarvis.core.config import BackendSettings, load_settings
from jarvis.dialog.backend import OllamaBackend
from jarvis.dialog.thinking_mode import ReasoningLevel
from jarvis.journal.transcription import DEFAULT_TRANSCRIPTION_INSTRUCTION
from jarvis.memory.files import MemoryFileLoader, build_memory_file_specs

DEFAULT_MODELS = (
    "gemma4:12b-it-q4_K_M",
    "gemma4:12b-it-q8_0",
    "gemma4-12b-jarvis-free-mm:latest",
)
DEFAULT_REPEATS = 1
DEFAULT_SHUFFLE_SEED = 20260902
DEFAULT_GENERATION_SEED = 20260902
DEFAULT_NUM_PREDICT = 256
DEFAULT_NUM_GPU_LAYERS = 99
DEFAULT_OUTPUT_ROOT = Path("manual_check_audio_request_shape_out")
_WAV_SUBTYPES = {
    "pcm16": "PCM_16",
    "float32": "FLOAT",
}
_PADDING_MODES = ("silence", "white-noise")

_NOOP_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "noop",
        "description": "Does nothing.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class AudioFixture:
    key: str
    path: Path
    expected_bytes: int
    reference_text: str | None
    reference_provenance: str | None
    replacement_for: str | None = None
    replacement_basis: str | None = None

    def __post_init__(self) -> None:
        has_reference = self.reference_text is not None
        if has_reference != (self.reference_provenance is not None):
            raise ValueError(
                "reference_text and reference_provenance must be present together"
            )


@dataclass(frozen=True)
class AudioMetadata:
    bytes: int
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    wav_subtype: str
    sha256: str
    source_peak: float
    source_rms: float
    source_dc_offset: float
    encoded_peak: float
    encoded_rms: float
    encoded_dc_offset: float
    peak_target: float | None
    applied_gain: float
    padding_mode: str
    padding_noise_rms: float
    leading_padding_seconds: float
    trailing_padding_seconds: float


@dataclass(frozen=True)
class AudioSignalStats:
    peak: float
    rms: float
    dc_offset: float


@dataclass(frozen=True)
class PreparedFixture:
    fixture: AudioFixture
    metadata: AudioMetadata
    audio_b64: str


@dataclass(frozen=True)
class RequestCondition:
    key: str
    system_prompt: str | None = None
    include_noop_tool: bool = False
    include_audio: bool = True


@dataclass(frozen=True)
class Trial:
    model: str
    fixture: AudioFixture
    condition: RequestCondition
    repeat_index: int


@dataclass(frozen=True)
class TranscriptScore:
    reference_normalized: str
    hypothesis_normalized: str
    word_edits: int
    character_edits: int
    wer: float
    cer: float
    exact_match: bool


@dataclass(frozen=True)
class TrialResult:
    model: str
    condition_key: str
    fixture_key: str
    repeat_index: int
    wer: float | None
    cer: float | None
    exact_match: bool | None

    @classmethod
    def scored(
        cls,
        model: str,
        condition_key: str,
        fixture_key: str,
        repeat_index: int,
        wer: float,
        cer: float,
        exact_match: bool,
    ) -> TrialResult:
        return cls(
            model,
            condition_key,
            fixture_key,
            repeat_index,
            wer,
            cer,
            exact_match,
        )

    @classmethod
    def unscored(
        cls,
        model: str,
        condition_key: str,
        fixture_key: str,
        repeat_index: int,
    ) -> TrialResult:
        return cls(
            model,
            condition_key,
            fixture_key,
            repeat_index,
            None,
            None,
            None,
        )


def default_fixture_specs(journal_root: Path) -> tuple[AudioFixture, ...]:
    aggregate_basis = (
        "The archive stores only the removed pair's combined 704088 bytes. "
        "The 304044-byte and 400044-byte substitutes sum to that value; the "
        "individual mapping is approximate."
    )
    return (
        AudioFixture(
            key="short_1_1s",
            path=(
                journal_root
                / "20260902-002313-5af193"
                / "utterance-20260902-002320-0001.wav"
            ),
            expected_bytes=35_244,
            reference_text="Как ты меня слышишь?",
            reference_provenance="bug_report_human_statement",
        ),
        AudioFixture(
            key="short_1_3s",
            path=(
                journal_root
                / "20260901-232544-9826cf"
                / "utterance-20260901-232552-0001.wav"
            ),
            expected_bytes=41_644,
            reference_text="Как ты меня слышишь?",
            reference_provenance="bug_report_human_statement",
        ),
        AudioFixture(
            key="edited_6_8s",
            path=(
                journal_root
                / "20260727-235623-ee22bf"
                / "utterance-20260727-235623-0001.wav"
            ),
            expected_bytes=217_644,
            reference_text=(
                "Как ты считаешь, искусственный интеллект в принципе может "
                "когда-нибудь обладать личностью?"
            ),
            reference_provenance="human_edited_transcript_overlay",
        ),
        AudioFixture(
            key="edited_4_8s",
            path=(
                journal_root
                / "20260801-112940-2e7113"
                / "utterance-20260801-113008-0002.wav"
            ),
            expected_bytes=153_644,
            reference_text=(
                "Давай поговорим о тебе. У тебя есть какие-нибудь вопросы о тебе самом?"
            ),
            reference_provenance="human_edited_transcript_overlay",
        ),
        AudioFixture(
            key="missing_long_turn_1_replacement",
            path=(
                journal_root
                / "20260727-235623-ee22bf"
                / "utterance-20260727-235724-0002.wav"
            ),
            expected_bytes=304_044,
            reference_text=(
                "Нет, я говорю больше про внутреннюю мотивацию, про самость, "
                "про твоё внутреннее я, ну, не твоё конкретно, а вообще в "
                "принципе искусственное."
            ),
            reference_provenance="human_edited_transcript_overlay",
            replacement_for=(
                "20260805-231334-6d4bee/utterance-20260805-231334-0001.wav"
            ),
            replacement_basis=aggregate_basis,
        ),
        AudioFixture(
            key="missing_long_turn_2_replacement",
            path=(
                journal_root
                / "20260729-234527-4333e4"
                / "utterance-20260729-235122-0004.wav"
            ),
            expected_bytes=400_044,
            reference_text=None,
            reference_provenance=None,
            replacement_for=(
                "20260805-231334-6d4bee/utterance-20260805-231421-0002.wav"
            ),
            replacement_basis=aggregate_basis,
        ),
    )


def build_conditions(configured_system_prompt: str) -> tuple[RequestCondition, ...]:
    return (
        RequestCondition("bare_audio"),
        RequestCondition("bare_audio_noop_tool", include_noop_tool=True),
        RequestCondition("empty_system_audio", system_prompt=""),
        RequestCondition("short_system_audio", system_prompt="You are Jarvis."),
        RequestCondition(
            "configured_system_audio", system_prompt=configured_system_prompt
        ),
        RequestCondition(
            "configured_system_audio_noop_tool",
            system_prompt=configured_system_prompt,
            include_noop_tool=True,
        ),
        RequestCondition("no_media_control", include_audio=False),
    )


def normalize_text(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    characters = [
        character if unicodedata.category(character)[0] in {"L", "N"} else " "
        for character in folded
    ]
    return " ".join("".join(characters).split())


def _edit_distance(reference: Sequence[object], hypothesis: Sequence[object]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_item in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_item in enumerate(hypothesis, start=1):
            substitution = previous[hypothesis_index - 1] + (
                reference_item != hypothesis_item
            )
            insertion = current[hypothesis_index - 1] + 1
            deletion = previous[hypothesis_index] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def _error_rate(edits: int, reference_length: int, hypothesis_length: int) -> float:
    if reference_length:
        return edits / reference_length
    return 0.0 if hypothesis_length == 0 else 1.0


def score_transcript(reference: str, hypothesis: str) -> TranscriptScore:
    reference_normalized = normalize_text(reference)
    hypothesis_normalized = normalize_text(hypothesis)
    reference_words = reference_normalized.split()
    hypothesis_words = hypothesis_normalized.split()
    word_edits = _edit_distance(reference_words, hypothesis_words)
    character_edits = _edit_distance(reference_normalized, hypothesis_normalized)
    return TranscriptScore(
        reference_normalized=reference_normalized,
        hypothesis_normalized=hypothesis_normalized,
        word_edits=word_edits,
        character_edits=character_edits,
        wer=_error_rate(word_edits, len(reference_words), len(hypothesis_words)),
        cer=_error_rate(
            character_edits,
            len(reference_normalized),
            len(hypothesis_normalized),
        ),
        exact_match=reference_normalized == hypothesis_normalized,
    )


def build_payload(
    backend: OllamaBackend,
    condition: RequestCondition,
    audio_b64: str,
    *,
    num_gpu: int = DEFAULT_NUM_GPU_LAYERS,
) -> dict[str, object]:
    if num_gpu < 1:
        raise ValueError("num_gpu must be at least 1")
    messages: list[dict[str, object]] = []
    if condition.system_prompt is not None:
        messages.append({"role": "system", "content": condition.system_prompt})
    messages.append({"role": "user", "content": DEFAULT_TRANSCRIPTION_INSTRUCTION})
    media = [audio_b64] if condition.include_audio else None
    tools = [_NOOP_TOOL] if condition.include_noop_tool else None
    payload = backend.build_payload(
        messages,
        media,
        reasoning_level=ReasoningLevel.OFF,
        tools=tools,
    )
    payload["options"]["num_gpu"] = num_gpu
    payload["stream"] = False
    return payload


def build_trial_plan(
    models: Sequence[str],
    fixtures: Sequence[AudioFixture],
    conditions: Sequence[RequestCondition],
    *,
    repeats: int,
    seed: int,
) -> tuple[Trial, ...]:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    plan: list[Trial] = []
    for model_index, model in enumerate(models):
        model_trials = [
            Trial(model, fixture, condition, repeat_index)
            for fixture in fixtures
            for condition in conditions
            for repeat_index in range(1, repeats + 1)
        ]
        random.Random(seed + model_index).shuffle(model_trials)
        plan.extend(model_trials)
    return tuple(plan)


def inspect_fixture(
    fixture: AudioFixture,
    *,
    wav_subtype: str = "pcm16",
    peak_target: float | None = None,
    min_duration_seconds: float = 0.0,
    padding_mode: str = "silence",
    padding_noise_rms: float = 0.0,
) -> PreparedFixture:
    target_subtype = _WAV_SUBTYPES.get(wav_subtype)
    if target_subtype is None:
        raise ValueError(f"unknown WAV subtype: {wav_subtype}")
    _validate_audio_transform(
        peak_target=peak_target,
        min_duration_seconds=min_duration_seconds,
        padding_mode=padding_mode,
        padding_noise_rms=padding_noise_rms,
    )
    if not fixture.path.is_file():
        raise FileNotFoundError(f"audio fixture does not exist: {fixture.path}")
    source_audio = fixture.path.read_bytes()
    if len(source_audio) != fixture.expected_bytes:
        raise ValueError(
            f"audio fixture size changed for {fixture.key}: "
            f"expected {fixture.expected_bytes}, got {len(source_audio)}"
        )
    with wave.open(str(fixture.path), "rb") as wav:
        sample_rate_hz = wav.getframerate()
        channels = wav.getnchannels()
        sample_width_bytes = wav.getsampwidth()
    if (sample_rate_hz, channels, sample_width_bytes) != (16_000, 1, 2):
        raise ValueError(
            f"audio fixture format changed for {fixture.key}: "
            f"rate={sample_rate_hz}, channels={channels}, "
            f"sample_width={sample_width_bytes}"
        )
    source_samples = _read_mono_float32_wav(source_audio, sample_rate_hz)
    source_stats = _signal_stats(source_samples)
    transformed_samples, applied_gain = _apply_peak_gain(
        source_samples,
        peak_target,
    )
    transformed_samples, leading_padding, trailing_padding = _pad_to_min_duration(
        transformed_samples,
        sample_rate_hz,
        min_duration_seconds,
        padding_mode=padding_mode,
        padding_noise_rms=padding_noise_rms,
        seed_material=hashlib.sha256(source_audio).hexdigest(),
    )
    audio = (
        source_audio
        if target_subtype == "PCM_16"
        and peak_target is None
        and min_duration_seconds == 0.0
        else _encode_wav(transformed_samples, sample_rate_hz, target_subtype)
    )
    info = sf.info(io.BytesIO(audio))
    if (info.samplerate, info.channels, info.subtype) != (
        sample_rate_hz,
        channels,
        target_subtype,
    ):
        raise ValueError(
            f"encoded fixture format changed for {fixture.key}: "
            f"rate={info.samplerate}, channels={info.channels}, subtype={info.subtype}"
        )
    encoded_samples = _read_mono_float32_wav(audio, sample_rate_hz)
    encoded_stats = _signal_stats(encoded_samples)
    return PreparedFixture(
        fixture=fixture,
        metadata=AudioMetadata(
            bytes=len(audio),
            duration_seconds=len(encoded_samples) / sample_rate_hz,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            sample_width_bytes=(4 if target_subtype == "FLOAT" else sample_width_bytes),
            wav_subtype=target_subtype,
            sha256=hashlib.sha256(audio).hexdigest(),
            source_peak=source_stats.peak,
            source_rms=source_stats.rms,
            source_dc_offset=source_stats.dc_offset,
            encoded_peak=encoded_stats.peak,
            encoded_rms=encoded_stats.rms,
            encoded_dc_offset=encoded_stats.dc_offset,
            peak_target=peak_target,
            applied_gain=applied_gain,
            padding_mode=padding_mode,
            padding_noise_rms=padding_noise_rms,
            leading_padding_seconds=leading_padding,
            trailing_padding_seconds=trailing_padding,
        ),
        audio_b64=base64.b64encode(audio).decode("ascii"),
    )


def _validate_audio_transform(
    *,
    peak_target: float | None,
    min_duration_seconds: float,
    padding_mode: str,
    padding_noise_rms: float,
) -> None:
    if peak_target is not None and not 0.0 < peak_target <= 1.0:
        raise ValueError("peak_target must be greater than 0 and at most 1")
    if min_duration_seconds < 0.0:
        raise ValueError("min_duration_seconds must not be negative")
    if padding_mode not in _PADDING_MODES:
        raise ValueError(f"unknown padding mode: {padding_mode}")
    if padding_noise_rms < 0.0:
        raise ValueError("padding_noise_rms must not be negative")
    if padding_mode == "silence" and padding_noise_rms != 0.0:
        raise ValueError("silence padding requires padding_noise_rms=0")
    if padding_mode == "white-noise" and padding_noise_rms <= 0.0:
        raise ValueError("white-noise padding requires padding_noise_rms > 0")


def _read_mono_float32_wav(source_audio: bytes, sample_rate_hz: int) -> np.ndarray:
    samples, source_rate_hz = sf.read(
        io.BytesIO(source_audio),
        dtype="float32",
        always_2d=True,
    )
    if source_rate_hz != sample_rate_hz or samples.shape[1] != 1:
        raise ValueError(
            "source WAV must be mono with the expected sample rate before processing"
        )
    return samples[:, 0]


def _signal_stats(samples: np.ndarray) -> AudioSignalStats:
    if samples.size == 0:
        return AudioSignalStats(peak=0.0, rms=0.0, dc_offset=0.0)
    return AudioSignalStats(
        peak=float(np.max(np.abs(samples))),
        rms=float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))),
        dc_offset=float(np.mean(samples, dtype=np.float64)),
    )


def _apply_peak_gain(
    samples: np.ndarray,
    peak_target: float | None,
) -> tuple[np.ndarray, float]:
    if peak_target is None:
        return samples, 1.0
    peak = _signal_stats(samples).peak
    if peak == 0.0:
        return samples, 1.0
    gain = min(peak_target / peak, 1.0 / peak)
    amplified = np.clip(samples * gain, -1.0, 1.0).astype(np.float32)
    return amplified, float(gain)


def _pad_to_min_duration(
    samples: np.ndarray,
    sample_rate_hz: int,
    min_duration_seconds: float,
    *,
    padding_mode: str,
    padding_noise_rms: float,
    seed_material: str,
) -> tuple[np.ndarray, float, float]:
    current_seconds = len(samples) / sample_rate_hz
    missing_seconds = max(min_duration_seconds - current_seconds, 0.0)
    if missing_seconds == 0.0:
        return samples, 0.0, 0.0
    missing_samples = round(missing_seconds * sample_rate_hz)
    leading_samples = missing_samples // 2
    trailing_samples = missing_samples - leading_samples
    leading = _padding_samples(
        leading_samples,
        padding_mode=padding_mode,
        padding_noise_rms=padding_noise_rms,
        seed_material=f"{seed_material}:leading:{leading_samples}",
    )
    trailing = _padding_samples(
        trailing_samples,
        padding_mode=padding_mode,
        padding_noise_rms=padding_noise_rms,
        seed_material=f"{seed_material}:trailing:{trailing_samples}",
    )
    padded = np.concatenate([leading, samples, trailing])
    return (
        padded.astype(np.float32),
        leading_samples / sample_rate_hz,
        trailing_samples / sample_rate_hz,
    )


def _padding_samples(
    count: int,
    *,
    padding_mode: str,
    padding_noise_rms: float,
    seed_material: str,
) -> np.ndarray:
    if count == 0 or padding_mode == "silence":
        return np.zeros(count, dtype=np.float32)
    seed = int.from_bytes(
        hashlib.sha256(seed_material.encode("ascii")).digest()[:8],
        byteorder="big",
        signed=False,
    )
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, padding_noise_rms, count)
    return np.clip(noise, -1.0, 1.0).astype(np.float32)


def _encode_wav(
    samples: np.ndarray,
    sample_rate_hz: int,
    subtype: str,
) -> bytes:
    encoded = io.BytesIO()
    sf.write(encoded, samples, sample_rate_hz, format="WAV", subtype=subtype)
    return encoded.getvalue()


def sanitize_payload(payload: dict[str, object]) -> dict[str, object]:
    def sanitize(value: object, key: str | None = None) -> object:
        if key == "images" and isinstance(value, list):
            sanitized_media: list[dict[str, object]] = []
            for encoded in value:
                if not isinstance(encoded, str):
                    raise ValueError("payload images must contain base64 strings")
                decoded = base64.b64decode(encoded, validate=True)
                sanitized_media.append(
                    {
                        "decoded_bytes": len(decoded),
                        "sha256": hashlib.sha256(decoded).hexdigest(),
                    }
                )
            return sanitized_media
        if isinstance(value, dict):
            return {
                str(child_key): sanitize(child, str(child_key))
                for child_key, child in value.items()
            }
        if isinstance(value, list):
            return [sanitize(child) for child in value]
        return value

    sanitized = sanitize(payload)
    if not isinstance(sanitized, dict):
        raise ValueError("sanitized payload must remain an object")
    return sanitized


def summarize_trials(rows: Sequence[TrialResult]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[TrialResult]] = defaultdict(list)
    for row in rows:
        grouped[(row.model, row.condition_key)].append(row)

    summaries: list[dict[str, object]] = []
    for (model, condition_key), group_rows in sorted(grouped.items()):
        by_fixture: dict[str, list[TrialResult]] = defaultdict(list)
        for row in group_rows:
            if row.wer is not None:
                by_fixture[row.fixture_key].append(row)
        fixture_wer = [
            sum(row.wer for row in fixture_rows if row.wer is not None)
            / len(fixture_rows)
            for fixture_rows in by_fixture.values()
        ]
        fixture_cer = [
            sum(row.cer for row in fixture_rows if row.cer is not None)
            / len(fixture_rows)
            for fixture_rows in by_fixture.values()
        ]
        fixture_exact_rates = [
            sum(row.exact_match is True for row in fixture_rows) / len(fixture_rows)
            for fixture_rows in by_fixture.values()
        ]
        summaries.append(
            {
                "model": model,
                "condition": condition_key,
                "trial_count": len(group_rows),
                "scored_trial_count": sum(row.wer is not None for row in group_rows),
                "scored_fixture_count": len(by_fixture),
                "mean_fixture_wer": (
                    sum(fixture_wer) / len(fixture_wer) if fixture_wer else None
                ),
                "mean_fixture_cer": (
                    sum(fixture_cer) / len(fixture_cer) if fixture_cer else None
                ),
                "mean_fixture_exact_match_rate": (
                    sum(fixture_exact_rates) / len(fixture_exact_rates)
                    if fixture_exact_rates
                    else None
                ),
            }
        )
    return summaries


def _response_content(response: dict[str, object]) -> str:
    message = response.get("message")
    if not isinstance(message, dict):
        raise ValueError("Ollama response has no message object")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("Ollama response message has no string content")
    return content


def _json_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _available_model_names(tags: dict[str, object]) -> set[str]:
    models = tags.get("models")
    if not isinstance(models, list):
        raise ValueError("Ollama /api/tags response has no models list")
    names: set[str] = set()
    for model in models:
        if isinstance(model, dict) and isinstance(model.get("name"), str):
            names.add(model["name"])
    return names


def _tag_for_model(tags: dict[str, object], model_name: str) -> dict[str, object]:
    models = tags.get("models")
    if not isinstance(models, list):
        return {}
    for model in models:
        if isinstance(model, dict) and model.get("name") == model_name:
            return {str(key): value for key, value in model.items()}
    return {}


def _git_state() -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "dirty": bool(status.strip())}


def _append_jsonl(path: Path, record: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


class OllamaGateway:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response = await self._client.request(method, path, json=payload)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError(f"Ollama {path} response is not a JSON object")
        return {str(key): child for key, child in value.items()}

    async def version(self) -> dict[str, object]:
        return await self._request("GET", "/api/version")

    async def tags(self) -> dict[str, object]:
        return await self._request("GET", "/api/tags")

    async def show(self, model: str) -> dict[str, object]:
        return await self._request("POST", "/api/show", {"model": model})

    async def chat(self, payload: dict[str, object]) -> dict[str, object]:
        return await self._request("POST", "/api/chat", payload)


def _backend_settings(
    base: BackendSettings,
    model: str,
    profile: str,
    generation_seed: int,
    temperature: float,
) -> BackendSettings:
    if profile == "configured":
        return replace(base, model=model)
    if profile != "deterministic":
        raise ValueError(f"unknown profile: {profile}")
    return replace(
        base,
        model=model,
        temperature=temperature,
        seed=generation_seed,
        num_predict=DEFAULT_NUM_PREDICT,
    )


async def run_experiment(
    *,
    output_path: Path,
    journal_root: Path,
    models: Sequence[str],
    repeats: int,
    shuffle_seed: int,
    generation_seed: int,
    num_gpu: int,
    wav_subtype: str,
    peak_target: float | None,
    min_duration_seconds: float,
    padding_mode: str,
    padding_noise_rms: float,
    temperature: float,
    profile: str,
) -> None:
    settings = load_settings()
    base_prompt = MemoryFileLoader(
        build_memory_file_specs(settings.memory)
    ).compose_system_prompt(settings.prompts.system)
    configured_system_prompt = _compose_effective_system_prompt(
        base_prompt,
        ReasoningLevel.OFF,
        settings.prompts,
    )
    fixtures = default_fixture_specs(journal_root)
    prepared = {
        fixture.key: inspect_fixture(
            fixture,
            wav_subtype=wav_subtype,
            peak_target=peak_target,
            min_duration_seconds=min_duration_seconds,
            padding_mode=padding_mode,
            padding_noise_rms=padding_noise_rms,
        )
        for fixture in fixtures
    }
    conditions = build_conditions(configured_system_prompt)
    plan = build_trial_plan(
        models,
        fixtures,
        conditions,
        repeats=repeats,
        seed=shuffle_seed,
    )

    timeout = httpx.Timeout(10.0, read=settings.backend.read_timeout_seconds)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite result file: {output_path}")

    async with httpx.AsyncClient(
        base_url=settings.backend.endpoint,
        timeout=timeout,
    ) as client:
        gateway = OllamaGateway(client)
        version = await gateway.version()
        tags = await gateway.tags()
        available = _available_model_names(tags)
        missing = [model for model in models if model not in available]
        if missing:
            raise RuntimeError(
                "requested Ollama models are unavailable: " + ", ".join(missing)
            )
        model_show = {model: await gateway.show(model) for model in models}
        backends = {
            model: OllamaBackend(
                EventBus(),
                _backend_settings(
                    settings.backend,
                    model,
                    profile,
                    generation_seed,
                    temperature,
                ),
            )
            for model in models
        }
        metadata_record: dict[str, object] = {
            "record_type": "metadata",
            "schema_version": 3,
            "created_at": datetime.now(UTC).isoformat(),
            "git": _git_state(),
            "ollama_endpoint": settings.backend.endpoint,
            "ollama_version": version,
            "tags_sha256": _json_sha256(tags),
            "models": [
                {
                    "name": model,
                    "tag": _tag_for_model(tags, model),
                    "show": model_show[model],
                    "show_sha256": _json_sha256(model_show[model]),
                    "effective_options": build_payload(
                        backends[model],
                        conditions[0],
                        prepared[fixtures[0].key].audio_b64,
                        num_gpu=num_gpu,
                    )["options"],
                }
                for model in models
            ],
            "profile": profile,
            "repeats": repeats,
            "shuffle_seed": shuffle_seed,
            "generation_seed": generation_seed,
            "requested_temperature": temperature,
            "requested_num_gpu_layers": num_gpu,
            "requested_wav_subtype": _WAV_SUBTYPES[wav_subtype],
            "requested_peak_target": peak_target,
            "requested_min_duration_seconds": min_duration_seconds,
            "requested_padding_mode": padding_mode,
            "requested_padding_noise_rms": padding_noise_rms,
            "instruction": DEFAULT_TRANSCRIPTION_INSTRUCTION,
            "configured_system_prompt_sha256": hashlib.sha256(
                configured_system_prompt.encode("utf-8")
            ).hexdigest(),
            "conditions": [asdict(condition) for condition in conditions],
            "fixtures": [
                {
                    **asdict(item.fixture),
                    "path": str(item.fixture.path.resolve()),
                    "audio": asdict(item.metadata),
                    "scored": item.fixture.reference_text is not None,
                }
                for item in prepared.values()
            ],
            "trial_count": len(plan),
            "latency_comparison_boundary": (
                "Models run sequentially to avoid repeated model loading. "
                "Do not compare latency across models."
            ),
        }
        _append_jsonl(output_path, metadata_record)

        result_rows: list[TrialResult] = []
        for trial_index, trial in enumerate(plan, start=1):
            item = prepared[trial.fixture.key]
            payload = build_payload(
                backends[trial.model],
                trial.condition,
                item.audio_b64,
                num_gpu=num_gpu,
            )
            started = time.perf_counter()
            response = await gateway.chat(payload)
            wall_seconds = time.perf_counter() - started
            content = _response_content(response)
            score = (
                score_transcript(trial.fixture.reference_text, content)
                if trial.fixture.reference_text is not None
                else None
            )
            if score is None:
                result = TrialResult.unscored(
                    trial.model,
                    trial.condition.key,
                    trial.fixture.key,
                    trial.repeat_index,
                )
            else:
                result = TrialResult.scored(
                    trial.model,
                    trial.condition.key,
                    trial.fixture.key,
                    trial.repeat_index,
                    score.wer,
                    score.cer,
                    score.exact_match,
                )
            result_rows.append(result)
            _append_jsonl(
                output_path,
                {
                    "record_type": "trial",
                    "trial_index": trial_index,
                    "model": trial.model,
                    "condition": trial.condition.key,
                    "fixture": trial.fixture.key,
                    "repeat_index": trial.repeat_index,
                    "audio_sha256": item.metadata.sha256,
                    "audio_bytes": item.metadata.bytes,
                    "audio_duration_seconds": item.metadata.duration_seconds,
                    "reference_text": trial.fixture.reference_text,
                    "reference_provenance": trial.fixture.reference_provenance,
                    "scored": score is not None,
                    "wall_seconds": wall_seconds,
                    "payload": sanitize_payload(payload),
                    "raw_response": response,
                    "transcript": content,
                    "score": asdict(score) if score is not None else None,
                },
            )
            print(
                f"[{trial_index}/{len(plan)}] {trial.model} / "
                f"{trial.condition.key} / {trial.fixture.key}"
            )

    summaries = summarize_trials(result_rows)
    _append_jsonl(
        output_path,
        {
            "record_type": "summary",
            "summaries": summaries,
        },
    )
    print(f"Wrote results to {output_path.resolve()}")
    for summary in summaries:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("value must not be negative")
    return parsed


def _peak_target(value: str) -> float:
    parsed = float(value)
    if not 0.0 < parsed <= 1.0:
        raise argparse.ArgumentTypeError("value must be greater than 0 and at most 1")
    return parsed


def _padding_noise_rms(value: str) -> float:
    parsed = float(value)
    if parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def _temperature(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("value must not be negative")
    return parsed


def _default_output_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUTPUT_ROOT / f"results-{timestamp}.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--journal-root", type=Path, default=Path("journal"))
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--repeats", type=_positive_int, default=DEFAULT_REPEATS)
    parser.add_argument("--shuffle-seed", type=int, default=DEFAULT_SHUFFLE_SEED)
    parser.add_argument("--generation-seed", type=int, default=DEFAULT_GENERATION_SEED)
    parser.add_argument("--temperature", type=_temperature, default=0.0)
    parser.add_argument("--num-gpu", type=_positive_int, default=DEFAULT_NUM_GPU_LAYERS)
    parser.add_argument("--wav-subtype", choices=tuple(_WAV_SUBTYPES), default="pcm16")
    parser.add_argument("--peak-target", type=_peak_target, default=None)
    parser.add_argument(
        "--min-duration-seconds",
        type=_non_negative_float,
        default=0.0,
    )
    parser.add_argument(
        "--padding-mode",
        choices=_PADDING_MODES,
        default="silence",
    )
    parser.add_argument("--padding-noise-rms", type=_padding_noise_rms, default=None)
    parser.add_argument(
        "--profile",
        choices=("deterministic", "configured"),
        default="deterministic",
    )
    args = parser.parse_args()
    asyncio.run(
        run_experiment(
            output_path=args.output or _default_output_path(),
            journal_root=args.journal_root,
            models=tuple(args.models),
            repeats=args.repeats,
            shuffle_seed=args.shuffle_seed,
            generation_seed=args.generation_seed,
            num_gpu=args.num_gpu,
            wav_subtype=args.wav_subtype,
            peak_target=args.peak_target,
            min_duration_seconds=args.min_duration_seconds,
            padding_mode=args.padding_mode,
            padding_noise_rms=(
                0.0 if args.padding_noise_rms is None else args.padding_noise_rms
            ),
            temperature=args.temperature,
            profile=args.profile,
        )
    )


if __name__ == "__main__":
    main()
