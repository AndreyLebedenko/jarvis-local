"""Encodes a capture clip the way the backend takes audio: a WAV in `images`."""

from __future__ import annotations

import base64

import numpy as np
import torch

from jarvis.audio.utils import samples_to_wav_bytes
from jarvis.personal_proxy.stt.silero_probabilities import SAMPLE_RATE


def clip_to_wav_base64(clip: np.ndarray) -> str:
    wav = samples_to_wav_bytes(torch.from_numpy(clip), SAMPLE_RATE)
    return base64.b64encode(wav).decode("ascii")
