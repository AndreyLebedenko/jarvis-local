"""Shared audio encoding helper.

No project-module dependencies by design - used by both audio_in.py
(input) and tts.py (output) so neither has to depend on the other just
to get a wav-bytes encoder.
"""

import io

import soundfile as sf
import torch


def samples_to_wav_bytes(samples: torch.Tensor, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, samples.numpy(), sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
