import ast
import io
from pathlib import Path

import soundfile as sf
import torch

from jarvis.audio.utils import samples_to_wav_bytes

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Other modules in this repo. audio_utils.py must not import any of them -
# that is the whole point of factoring it out (task-05 review: tts.py was
# importing audio_in.py just to reuse this one function).
_OTHER_PROJECT_MODULES = {"bus", "config", "backend", "audio_in", "tts", "capture", "main"}


def test_samples_to_wav_bytes_round_trips_sample_count_and_rate():
    samples = torch.zeros(1600)

    wav_bytes = samples_to_wav_bytes(samples, sample_rate=16000)
    decoded, sample_rate = sf.read(io.BytesIO(wav_bytes))

    assert sample_rate == 16000
    assert len(decoded) == 1600


def test_audio_utils_has_no_other_project_module_imports():
    source = (PROJECT_ROOT / "src/jarvis/audio/utils.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_top_level_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_top_level_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imported_top_level_names.add(node.module.split(".")[0])

    coupled = imported_top_level_names & _OTHER_PROJECT_MODULES
    assert not coupled, f"audio_utils.py imports other project modules: {coupled}"
