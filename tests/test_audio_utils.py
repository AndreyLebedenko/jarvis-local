import ast
import io
from pathlib import Path

import pytest
import soundfile as sf
import torch

from jarvis.audio.utils import pad_samples_to_min_duration, samples_to_wav_bytes

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Other modules in this repo. audio_utils.py must not import any of them -
# that is the whole point of factoring it out (task-05 review: tts.py was
# importing audio_in.py just to reuse this one function).
_OTHER_PROJECT_MODULES = {
    "bus",
    "config",
    "backend",
    "audio_in",
    "tts",
    "capture",
    "main",
}


def test_samples_to_wav_bytes_round_trips_sample_count_and_rate():
    samples = torch.zeros(1600)

    wav_bytes = samples_to_wav_bytes(samples, sample_rate=16000)
    decoded, sample_rate = sf.read(io.BytesIO(wav_bytes))

    assert sample_rate == 16000
    assert len(decoded) == 1600


def test_pad_samples_to_min_duration_leaves_long_samples_unchanged():
    samples = torch.linspace(-0.5, 0.5, steps=1600)

    padded = pad_samples_to_min_duration(
        samples,
        sample_rate=16000,
        min_duration_seconds=0.05,
        padding_noise_rms=0.002,
    )

    assert padded is samples


def test_pad_samples_to_min_duration_adds_symmetric_silence():
    samples = torch.ones(4)

    padded = pad_samples_to_min_duration(
        samples,
        sample_rate=10,
        min_duration_seconds=1.0,
        padding_noise_rms=0.0,
    )

    assert padded.tolist() == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]


def test_pad_samples_to_min_duration_adds_deterministic_noise_without_altering_speech():
    samples = torch.tensor([0.25, -0.25], dtype=torch.float32)

    first = pad_samples_to_min_duration(
        samples,
        sample_rate=10,
        min_duration_seconds=1.0,
        padding_noise_rms=0.002,
    )
    second = pad_samples_to_min_duration(
        samples,
        sample_rate=10,
        min_duration_seconds=1.0,
        padding_noise_rms=0.002,
    )

    assert torch.equal(first, second)
    assert first[4:6].tolist() == pytest.approx(samples.tolist())
    assert torch.count_nonzero(first[:4]) > 0
    assert torch.count_nonzero(first[6:]) > 0


def test_audio_utils_has_no_other_project_module_imports():
    source = (PROJECT_ROOT / "src/jarvis/audio/utils.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_top_level_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_top_level_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported_top_level_names.add(node.module.split(".")[0])

    coupled = imported_top_level_names & _OTHER_PROJECT_MODULES
    assert not coupled, f"audio_utils.py imports other project modules: {coupled}"
