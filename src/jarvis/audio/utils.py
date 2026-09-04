"""Shared audio encoding helper.

No project-module dependencies by design - used by both audio_in.py
(input) and tts.py (output) so neither has to depend on the other just
to get a wav-bytes encoder.
"""

import hashlib
import io

import numpy as np
import soundfile as sf
import torch


def pad_samples_to_min_duration(
    samples: torch.Tensor,
    sample_rate: int,
    *,
    min_duration_seconds: float,
    padding_noise_rms: float,
) -> torch.Tensor:
    target_samples = round(min_duration_seconds * sample_rate)
    if target_samples <= len(samples):
        return samples

    total_padding = target_samples - len(samples)
    leading_padding = total_padding // 2
    trailing_padding = total_padding - leading_padding
    source = samples.detach().cpu().numpy().astype(np.float32, copy=False)
    if padding_noise_rms == 0.0:
        leading = np.zeros(leading_padding, dtype=np.float32)
        trailing = np.zeros(trailing_padding, dtype=np.float32)
    else:
        seed_material = (
            source.tobytes()
            + str(sample_rate).encode("ascii")
            + str(target_samples).encode("ascii")
            + repr(float(padding_noise_rms)).encode("ascii")
        )
        seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        leading = rng.normal(0.0, padding_noise_rms, leading_padding).astype(np.float32)
        trailing = rng.normal(0.0, padding_noise_rms, trailing_padding).astype(
            np.float32
        )
        np.clip(leading, -1.0, 1.0, out=leading)
        np.clip(trailing, -1.0, 1.0, out=trailing)
    return torch.from_numpy(np.concatenate([leading, source, trailing]))


def samples_to_wav_bytes(samples: torch.Tensor, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, samples.numpy(), sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
