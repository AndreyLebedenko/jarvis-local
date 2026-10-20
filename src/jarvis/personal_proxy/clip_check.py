"""The one check of the audio clip handed to the speech stage."""

from __future__ import annotations

import numpy as np


class InvalidClipError(ValueError):
    pass


def require_valid_clip(clip: object) -> None:
    """The capture path delivers mono 16 kHz float32; empty is allowed."""
    if not isinstance(clip, np.ndarray):
        raise InvalidClipError(
            f"expected a float32 mono numpy array, got {type(clip).__name__}"
        )
    if clip.dtype != np.float32 or clip.ndim != 1:
        raise InvalidClipError(
            f"expected float32 mono, got {clip.dtype} shape {clip.shape}"
        )
    if not np.isfinite(clip).all():
        raise InvalidClipError("the clip contains NaN or infinite samples")
